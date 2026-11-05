import json
import secrets
import sqlite3
import time
import uuid

from app import main
from test_library import isolated_login_limits, service, logged, product, token, upload


def seed_legacy_agent_state(session):
    """An old installation with a live grant and both pending/completed imports."""
    secret = 'local_ai_' + secrets.token_urlsafe(32)
    session_hash = main.digest(session.cookies.get(main.COOKIE))
    grant_id = uuid.uuid4().hex
    with main.db() as con:
        con.executescript('''
            CREATE TABLE local_ai_grants (
                id TEXT PRIMARY KEY, hash TEXT NOT NULL UNIQUE,
                session_hash TEXT NOT NULL REFERENCES sessions(hash) ON DELETE CASCADE,
                created_at INTEGER NOT NULL);
            CREATE TABLE local_ai_batches (
                id TEXT PRIMARY KEY, grant_id TEXT NOT NULL, source TEXT NOT NULL,
                payload TEXT NOT NULL, preview TEXT NOT NULL, result TEXT,
                created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL);
        ''')
        con.execute('INSERT INTO local_ai_grants VALUES(?,?,?,?)',
                    (grant_id, main.digest(secret), session_hash, int(time.time())))
        for result in (None, '{}'):
            con.execute('INSERT INTO local_ai_batches VALUES(?,?,?,?,?,?,?,?)',
                        (uuid.uuid4().hex, grant_id, '旧导入记录', '{}', '{}', result, int(time.time()), int(time.time()) + 1800))
    (main.DATA / '.local-ai-credential.json').write_text(json.dumps({'token': secret}), encoding='utf-8')
    leftover = main.DATA / ('.local-ai-' + uuid.uuid4().hex + '.tmp')
    leftover.write_text('old temporary credential', encoding='utf-8')
    return secret, leftover


def assert_retired_tables_absent(con):
    assert con.execute("SELECT name FROM sqlite_master WHERE name IN ('local_ai_grants','local_ai_batches')").fetchall() == []


def test_upgrade_removes_old_permissions_but_keeps_products_images_and_readonly_tokens(logged):
    entry = product(logged, category='显示器')
    image = upload(logged, entry['id']).json()['image']
    readonly = token(logged)
    original = logged.get(image['download_url']).content
    main.audit('本机 AI 批量新建产品', 'local-ai:old', '历史操作记录')
    secret, leftover = seed_legacy_agent_state(logged)
    with main.db() as con:
        expected = {table: [tuple(row) for row in con.execute('SELECT * FROM ' + table + ' ORDER BY ' + ('hash' if table == 'sessions' else 'id'))]
                    for table in ['products', 'images', 'sessions', 'tokens', 'audit']}
    main.initialize()
    main.initialize()  # Repeated starts are safe, including after restoring an older database.
    with main.db() as con:
        assert_retired_tables_absent(con)
        for table, rows in expected.items():
            assert [tuple(row) for row in con.execute('SELECT * FROM ' + table + ' ORDER BY ' + ('hash' if table == 'sessions' else 'id'))] == rows
    assert not (main.DATA / '.local-ai-credential.json').exists()
    assert not leftover.exists()
    assert logged.get('/api/overview').status_code == 200
    assert logged.get(image['download_url']).content == original
    assert logged.get('/api/products', headers={'Authorization': 'Bearer ' + readonly['token']}).status_code == 200
    assert logged.post('/api/products', headers={'Authorization': 'Bearer ' + secret},
                       json={'code': 'forbidden', 'name': '禁止写入'}).status_code == 401


def test_removed_routes_assets_and_documentation_are_unavailable(logged):
    paths = {
        '/api/local-ai/access': ['GET', 'POST', 'DELETE'],
        '/api/local-ai/tool-status': ['GET'],
        '/api/local-ai/batches': ['POST'],
        '/api/local-ai/batches/old': ['GET'],
        '/api/local-ai/batches/old/commit': ['POST'],
        '/api/local-ai/history': ['GET'],
        '/api/local-ai/history/old': ['GET'],
    }
    for path, methods in paths.items():
        for method in methods:
            assert logged.request(method, path, json={}).status_code == 404
    assert logged.get('/static/local-ai.js').status_code == 404
    page = logged.get('/').text
    assert 'data-view="localai"' not in page and 'localai-view' not in page and '/static/local-ai.js' not in page
    assert 'AI 取图' in page
    assert not any(path.startswith('/api/local-ai') for path in logged.get('/api/openapi.json').json()['paths'])
    # Existing administrator and read-only flows continue to work.
    assert logged.get('/api/products', params={'limit': 20, 'offset': 20}).status_code == 200
    assert logged.get('/api/categories/manage').status_code == 200
    assert logged.post('/api/logout').status_code == 200


def test_backup_of_old_database_omits_retired_feature_state(logged, tmp_path, monkeypatch):
    import manage
    monkeypatch.setattr(manage, 'DATA', main.DATA)
    entry = product(logged)
    image = upload(logged, entry['id']).json()['image']
    seed_legacy_agent_state(logged)
    destination = tmp_path.parent / (tmp_path.name + '-retired-backup')
    manage.backup(destination)
    with sqlite3.connect(destination / 'library.sqlite3') as con:
        assert_retired_tables_absent(con)
        assert con.execute('SELECT count(*) FROM products').fetchone()[0] == 1
        assert con.execute('SELECT count(*) FROM images').fetchone()[0] == 1
    assert not (destination / '.local-ai-credential.json').exists()
    assert (destination / 'originals' / (image['id'] + '.png')).exists()


def test_password_reset_also_cleans_old_credentials(logged, monkeypatch):
    import manage
    monkeypatch.setattr(manage, 'DATA', main.DATA)
    monkeypatch.setattr(manage.getpass, 'getpass', lambda _: 'changed-test-password')
    _, leftover = seed_legacy_agent_state(logged)
    manage.reset_password()
    with main.db() as con:
        assert_retired_tables_absent(con)
        assert con.execute('SELECT count(*) FROM sessions').fetchone()[0] == 0
    assert not (main.DATA / '.local-ai-credential.json').exists() and not leftover.exists()
