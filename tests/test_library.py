import io
import zipfile
import sqlite3

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import main


@pytest.fixture(autouse=True)
def isolated_login_limits():
    # Every check authenticates from 127.0.0.1; start each test well below the shared attempt limit.
    main.login_attempts.clear()
    yield
    main.login_attempts.clear()


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setattr(main, 'DATA', tmp_path)
    monkeypatch.setattr(main, 'ORIGINALS', tmp_path / 'originals')
    monkeypatch.setattr(main, 'THUMBS', tmp_path / 'thumbnails')
    monkeypatch.setattr(main, 'TEMP', tmp_path / 'temp')
    main.login_attempts.clear()
    main.initialize()
    with TestClient(main.app, base_url='http://localhost', client=('127.0.0.1', 10000)) as session:
        yield session


@pytest.fixture
def logged(service):
    response = service.post('/api/setup', json={'username': 'qa-admin', 'password': 'temporary-test-password'})
    assert response.status_code == 200, response.text
    return service


def png(alpha=True, color=None):
    output = io.BytesIO()
    image = Image.new('RGBA' if alpha else 'RGB', (300, 200), color or ((30, 100, 200, 120) if alpha else (20, 50, 100)))
    image.save(output, 'PNG')
    return output.getvalue()


def product(session, code='001234', name='显示器 QA', **extra):
    if extra.get('category'):
        assert session.post('/api/categories', json={'name': extra['category']}).status_code == 200
    response = session.post('/api/products', json={'code': code, 'name': name, 'aliases': ['设计屏'], **extra})
    assert response.status_code == 200, response.text
    return response.json()


def upload(session, product_id='', alpha=True, data=None, **fields):
    return session.post('/api/images/upload', data={'product_id': product_id, **fields},
                        files={'file': ('正面图.png', data or png(alpha), 'image/png')})


def token(session):
    result = session.post('/api/tokens', json={'name': 'QA read-only'})
    assert result.status_code == 200
    return result.json()


def test_setup_local_only_and_unique(service):
    with TestClient(main.app, base_url='http://localhost', client=('192.168.1.25', 1234)) as remote:
        assert not remote.get('/api/status').json()['can_setup']
        assert remote.post('/api/setup', json={'username': 'test', 'password': 'temporary-test-password'}).status_code == 403
    assert service.post('/api/setup', json={'username': 'test', 'password': 'short'}).status_code == 400
    assert service.post('/api/setup', json={'username': 'test', 'password': 'temporary-test-password'}).status_code == 200
    assert service.post('/api/setup', json={'username': 'test', 'password': 'temporary-test-password'}).status_code == 409


def test_unauthorized_protected_routes(service):
    for route in ['/api/products', '/api/images', '/api/overview', '/api/tokens', '/api/audit', '/api/openapi.json']:
        assert service.get(route).status_code == 401
    assert upload(service).status_code == 401
    assert service.get('/').status_code == 200


def test_csrf_and_host_validation(logged):
    assert logged.post('/api/products', json={'code': 'x', 'name': 'x'}, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert logged.get('/api/products', headers={'Host': 'evil.example'}).status_code == 400
    assert logged.post('/api/products', json={'code': 'x', 'name': 'x'}, headers={'Origin': 'http://localhost'}).status_code == 200


def test_product_exact_codes_aliases_and_literal_search(logged):
    entry = product(logged, category='显示器')
    product(logged, code='1234', name='另一型号')
    assert logged.get('/api/products', params={'q': '001234'}).json()['items'][0]['code'] == '001234'
    assert logged.get('/api/products', params={'q': '123'}).json()['total'] == 0
    assert logged.get('/api/products', params={'q': '设计屏'}).json()['total'] == 2
    assert logged.get('/api/products', params={'q': '%'}).json()['total'] == 0
    assert logged.post('/api/products', json={'code': '001234', 'name': '重复'}).status_code == 409
    assert logged.put('/api/products/' + entry['id'], json={'code': '001234', 'name': '新名称'}).status_code == 200
    assert logged.get('/api/products', params={'q': '新名称'}).json()['total'] == 1


def test_product_list_filters_by_category(logged):
    for name in ('显示器', '主板', '显卡'):
        assert logged.post('/api/categories', json={'name': name}).status_code == 200
    product(logged, code='100148165479', name='PG27UCDM', category='显示器')
    product(logged, code='200000000001', name='ROG MAXIMUS', category='主板')
    product(logged, code='300000000001', name='未分类产品')
    total = logged.get('/api/products').json()
    assert total['total'] == 3

    monitors = logged.get('/api/products', params={'category': '显示器'}).json()
    assert monitors['total'] == 1
    assert monitors['items'][0]['code'] == '100148165479'

    assert logged.get('/api/products', params={'category': 'SSD'}).json()['total'] == 0
    main_boards = logged.get('/api/products', params={'category': '主板'}).json()
    assert [item['name'] for item in main_boards['items']] == ['ROG MAXIMUS']

    # Products without a category are reachable through the dedicated bucket.
    unsorted_products = logged.get('/api/products', params={'category': '未分类'}).json()
    assert [item['code'] for item in unsorted_products['items']] == ['300000000001']

    # Category and keyword filters combine instead of replacing each other.
    assert logged.get('/api/products', params={'category': '显示器', 'q': 'PG27'}).json()['total'] == 1
    assert logged.get('/api/products', params={'category': '主板', 'q': 'PG27'}).json()['total'] == 0


def test_category_choices_persist_and_products_select_one(logged):
    assert logged.get('/api/categories').json()['items'] == []
    assert logged.post('/api/categories', json={'name': '   '}).status_code == 400
    assert logged.post('/api/categories', json={'name': '  显示器  '}).json() == {'name': '显示器', 'created': True}
    assert logged.post('/api/categories', json={'name': '显示器'}).json()['created'] is False
    assert logged.post('/api/categories', json={'name': 'ＳＳＤ'}).json()['name'] == 'SSD'
    assert logged.post('/api/categories', json={'name': 'ssd'}).json() == {'name': 'SSD', 'created': False}
    entry = product(logged, category='显示器')
    assert entry['category'] == '显示器'
    assert logged.post('/api/products', json={'code': 'bad', 'name': 'bad', 'category': '未创建'}).status_code == 400
    assert logged.post('/api/products', json={'code': 'bad', 'name': 'bad', 'category': ['显示器', 'SSD']}).status_code == 422
    upload(logged, entry['id'])
    assert logged.get('/api/images', params={'category': '显示器'}).json()['total'] == 1
    assert logged.get('/api/images', params={'category': 'SSD'}).json()['total'] == 0
    assert logged.put('/api/products/' + entry['id'], json={'code': '001234', 'name': '新名称', 'category': 'ssd'}).status_code == 200
    assert logged.get('/api/products').json()['items'][0]['category'] == 'SSD'
    main.initialize()
    assert set(logged.get('/api/categories').json()['items']) == {'显示器', 'SSD'}
    token = logged.post('/api/tokens', json={'name': '分类只读测试'}).json()['token']
    headers = {'Authorization': 'Bearer ' + token}
    assert logged.get('/api/categories', headers=headers).status_code == 200
    assert logged.post('/api/categories', json={'name': '只读禁止新增'}, headers=headers).status_code == 403


def test_image_choices_accept_new_taxonomy(logged):
    status = logged.get('/api/status').json()
    assert status['kinds'] == ['产品图', '场景图', '其他']
    assert status['angles'] == ['正面', '背面', '侧面', '俯视', '仰视', '其他']
    assert status['backgrounds'] == ['透明', '其他']
    image = upload(logged, kind='场景图', angle='仰视', alpha=False, background='其他').json()['image']
    assert (image['kind'], image['angle'], image['background']) == ('场景图', '仰视', '其他')
    assert logged.get('/api/images', params={'kind': '场景图', 'angle': '仰视'}).json()['total'] == 1


def test_legacy_image_choices_are_migrated(logged):
    image = upload(logged).json()['image']
    with main.db() as con:
        con.execute("UPDATE images SET kind='包装图', background='白底', angle='侧面' WHERE id=?", (image['id'],))
    main.initialize()
    main.initialize()
    row = logged.get('/api/images/' + image['id']).json()
    assert (row['kind'], row['angle'], row['background']) == ('产品图', '侧面', '其他')
    assert logged.get('/api/images', params={'kind': '产品图', 'background': '其他'}).json()['total'] == 1


def test_existing_categories_are_migrated(logged):
    entry = product(logged)
    with main.db() as con:
        con.execute('UPDATE products SET category=? WHERE id=?', ('旧分类', entry['id']))
    main.initialize()
    main.initialize()
    assert logged.get('/api/categories').json()['items'] == ['旧分类']
    assert logged.put('/api/products/' + entry['id'], json={'code': entry['code'], 'name': '更新名称', 'category': '旧分类'}).status_code == 200
    result = logged.get('/api/products').json()['items'][0]
    assert result['category'] == '旧分类'


def test_brand_is_no_longer_read_or_searched(logged):
    entry = product(logged)
    main.initialize()
    with main.db() as con:
        con.execute("UPDATE products SET brand='历史品牌' WHERE id=?", (entry['id'],))
    assert logged.put('/api/products/' + entry['id'], json={'code': entry['code'], 'name': '改名', 'brand': '新品牌'}).status_code == 200
    with main.db() as con:
        assert con.execute('SELECT brand FROM products WHERE id=?', (entry['id'],)).fetchone()[0] == '历史品牌'
    assert logged.get('/api/products', params={'q': '历史品牌'}).json()['total'] == 0
    assert logged.get('/api/images', params={'q': '历史品牌'}).json()['total'] == 0
    assert logged.get('/api/images', params={'brand': '历史品牌'}).json()['total'] == 0
    assert 'brands' not in logged.get('/api/overview').json()


def test_product_aliases_and_tags_are_normalized_and_unique(logged):
    entry = product(logged, aliases=['  设计屏 ', '设计屏', 'ＳＳＤ'])
    assert entry['aliases'] == ['设计屏', 'SSD']
    image = upload(logged, entry['id'], tags='官方，官方, 无文案').json()['image']
    assert image['tags'] == ['官方', '无文案']
    updated = logged.put('/api/images/' + image['id'], json={'product_id': entry['id'], 'kind': '产品图', 'angle': '正面', 'background': '透明', 'tags': ['无文案', ' 无文案 ', '']})
    assert updated.json()['tags'] == ['无文案']


def test_upload_preserves_original_and_deduplicates_per_product(logged):
    entry = product(logged)
    original = png()
    result = upload(logged, entry['id'], data=original, tags='官方，正面')
    assert result.status_code == 200, result.text
    image = result.json()['image']
    assert image['background'] == '透明' and image['has_alpha'] is True
    assert image['width'] == 300 and image['height'] == 200
    assert image['product_code'] == '001234'
    assert logged.get(image['download_url']).content == original
    thumbnail = logged.get(image['thumbnail_url'])
    assert thumbnail.status_code == 200 and thumbnail.headers['content-type'] == 'image/webp'
    assert upload(logged, entry['id']).json()['duplicate'] is True
    assert logged.get('/api/overview').json()['images'] == 1
    assert upload(logged).json()['duplicate'] is False
    assert logged.get('/api/overview').json()['unassigned'] == 1


def test_image_filters_do_not_substitute_products(logged):
    entry = product(logged)
    upload(logged, entry['id'], kind='产品图')
    assert logged.get('/api/images', params={'product_code': '001234', 'background': '透明', 'min_width': 250}).json()['total'] == 1
    assert logged.get('/api/images', params={'product_code': '1234'}).json()['total'] == 0
    assert logged.get('/api/images', params={'q': '123'}).json()['total'] == 0
    assert logged.get('/api/images', params={'q': '设计屏', 'kind': '产品图'}).json()['total'] == 1
    assert logged.get('/api/images', params={'min_width': 1000}).json()['total'] == 0
    assert logged.get('/api/images', params={'background': '白底'}).json()['total'] == 0


def test_invalid_files_and_background_cleanup(logged):
    assert upload(logged, data=b'<svg onload="alert(1)"></svg>').status_code == 400
    assert upload(logged, alpha=False, background='透明').status_code == 400
    assert upload(logged, kind='invalid').status_code == 400
    assert upload(logged, background='白底').status_code == 400
    assert upload(logged, angle='斜视').status_code == 400
    assert not list(main.ORIGINALS.iterdir())
    assert not list(main.THUMBS.iterdir())
    assert not list(main.TEMP.iterdir())
    assert logged.post('/api/images/upload', headers={'Content-Length': str(30*1024*1024)}, content=b'').status_code == 413


def test_external_account_browses_and_downloads_but_never_writes(logged):
    entry = product(logged)
    image = upload(logged, entry['id']).json()['image']
    main.login_attempts.clear()
    created = logged.post('/api/accounts', json={'username': 'customer', 'password': 'customer-password-1', 'role': 'external'})
    assert created.status_code == 200, created.text
    assert created.json()['role'] == 'external'
    assert logged.post('/api/accounts', json={'username': 'customer', 'password': 'customer-password-1'}).status_code == 409
    assert logged.post('/api/accounts', json={'username': 'qa-admin', 'password': 'customer-password-1'}).status_code == 409
    assert logged.post('/api/accounts', json={'username': 'x', 'password': 'customer-password-1'}).status_code == 422
    with TestClient(main.app, base_url='http://localhost', client=('192.168.1.40', 1000)) as viewer:
        assert viewer.get('/').status_code == 200
        assert viewer.get('/api/images').status_code == 401
        assert viewer.post('/api/login', json={'username': 'customer', 'password': 'wrong-password'}).status_code == 401
        assert viewer.post('/api/login', json={'username': 'customer', 'password': 'customer-password-1'}).status_code == 200
        status = viewer.get('/api/status').json()
        assert status['logged_in'] is True and status['role'] == 'external'
        assert status['can_issue_tokens'] is False
        assert viewer.get('/api/images').json()['total'] == 1
        assert viewer.get(image['download_url']).content == png()
        assert viewer.get(image['thumbnail_url']).status_code == 200
        assert viewer.get('/api/overview').json()['trash'] == 0
        assert viewer.get('/api/images?trash=true').status_code == 403
        # An external account can never mint a token, not even a read-only one.
        assert viewer.get('/api/tokens').status_code == 403
        assert viewer.post('/api/tokens', json={'name': 'sneaky'}).status_code == 403
        assert viewer.post('/api/products', json={'code': 'x', 'name': 'x'}).status_code == 403
        assert viewer.post('/api/images/upload', files={'file': ('x.png', png(), 'image/png')}).status_code == 403
        assert viewer.delete('/api/images/' + image['id']).status_code == 403
        assert viewer.get('/api/accounts').status_code == 403
        assert viewer.post('/api/accounts', json={'username': 'evil', 'password': 'evil-password-1'}).status_code == 403
        # Resetting the password ends that account's sessions.
        account_id = created.json()['id']
        assert logged.put('/api/accounts/' + account_id, json={'password': 'customer-password-2'}).status_code == 200
        assert viewer.get('/api/images').status_code == 401
        assert viewer.post('/api/login', json={'username': 'customer', 'password': 'customer-password-2'}).status_code == 200
        # Deleting the account blocks the login outright.
        assert logged.delete('/api/accounts/' + account_id).status_code == 200
        assert viewer.get('/api/images').status_code == 401
        assert viewer.post('/api/login', json={'username': 'customer', 'password': 'customer-password-2'}).status_code == 401


def test_staff_account_issues_tokens_and_can_upload(logged):
    entry = product(logged)
    main.login_attempts.clear()
    created = logged.post('/api/accounts', json={'username': 'designer', 'password': 'designer-password-1', 'role': 'staff'})
    assert created.status_code == 200, created.text
    with TestClient(main.app, base_url='http://localhost', client=('192.168.1.60', 2000)) as member:
        assert member.post('/api/login', json={'username': 'designer', 'password': 'designer-password-1'}).status_code == 200
        status = member.get('/api/status').json()
        assert status['role'] == 'staff' and status['can_issue_tokens'] is True
        # Internal colleagues may read, download, upload and organise products.
        assert member.post('/api/images/upload', files={'file': ('s.png', png(), 'image/png')},
                           data={'product_id': entry['id']}).status_code == 200
        created_product = member.post('/api/products', json={'code': 'PROD-ST-1', 'name': '内部新建产品'})
        assert created_product.status_code == 200
        assert member.put('/api/products/' + entry['id'],
                          json={'code': entry['code'], 'name': '内部改名', 'aliases': []}).status_code == 200
        # Deleting is reserved for the administrator: images, categories and accounts alike.
        image_id = upload(logged, entry['id']).json()['image']['id']
        assert member.get('/api/images/' + image_id).status_code == 200
        assert member.put('/api/images/' + image_id,
                          json={'kind': '产品图', 'angle': '侧面', 'background': '透明', 'tags': []}).status_code == 200
        assert member.request('DELETE', '/api/images/' + image_id).status_code == 403
        assert member.post('/api/images/' + image_id + '/restore').status_code == 403
        assert member.post('/api/images/delete', json={'image_ids': [image_id]}).status_code == 403
        assert member.request('DELETE', '/api/categories', json={'name': '显示器'}).status_code == 403
        assert member.get('/api/accounts').status_code == 403
        assert member.get('/api/audit').status_code == 403
        issued = member.post('/api/tokens', json={'name': '我的 AI 工具'})
        assert issued.status_code == 200
        secret = issued.json()['token']
        listed = member.get('/api/tokens').json()['items']
        assert [item['name'] for item in listed] == ['我的 AI 工具']
        assert listed[0]['owner'] == 'designer'
    # The staff-issued token may read and upload, but still cannot manage the library.
    headers = {'Authorization': 'Bearer ' + secret}
    assert logged.get('/api/images', headers=headers).json()['total'] == 1
    assert logged.post('/api/images/upload', headers=headers, data={'product_id': entry['id']},
                       files={'file': ('t.png', png(), 'image/png')}).status_code == 200
    assert logged.delete('/api/images/' + entry['id'], headers=headers).status_code == 403
    assert logged.get('/api/accounts', headers=headers).status_code == 403
    # One staff account cannot see or revoke another account's tokens.
    other = logged.post('/api/accounts', json={'username': 'other-staff', 'password': 'other-password-1', 'role': 'staff'})
    assert other.status_code == 200
    with TestClient(main.app, base_url='http://localhost', client=('192.168.1.61', 2001)) as peer:
        peer.post('/api/login', json={'username': 'other-staff', 'password': 'other-password-1'})
        assert peer.get('/api/tokens').json()['items'] == []
        assert peer.delete('/api/tokens/' + issued.json()['id']).status_code == 403
    # Removing the account also removes the tokens it issued.
    assert logged.delete('/api/accounts/' + created.json()['id']).status_code == 200
    assert logged.get('/api/images', headers=headers).status_code == 401


def test_old_sessions_table_is_upgraded(service, monkeypatch):
    # Databases created before visitor roles lack the role column; startup must add it, not crash on login.
    with main.db() as con:
        con.execute('DROP TABLE sessions')
        con.execute('CREATE TABLE sessions (hash TEXT PRIMARY KEY, expires INTEGER NOT NULL)')
    main.initialize()
    with main.db() as con:
        assert 'role' in {row['name'] for row in con.execute('PRAGMA table_info(sessions)')}
    assert service.post('/api/setup', json={'username': 'qa-admin', 'password': 'temporary-test-password'}).status_code == 200
    assert service.post('/api/login', json={'username': 'qa-admin', 'password': 'temporary-test-password'}).status_code == 200


def test_upload_defaults_match_transparent_workflow(logged):
    # Transparent is the default background, so a PNG with alpha needs no extra form fields.
    image = upload(logged).json()['image']
    assert (image['kind'], image['angle'], image['background']) == ('产品图', '正面', '透明')
    # A file without alpha is rejected because the default now assumes transparency.
    assert upload(logged, alpha=False).status_code == 400


def test_role_capability_matrix(logged):
    """Administrator keeps every power; internal accounts read, download, upload and edit but never delete."""
    entry = product(logged)
    image_id = upload(logged, entry['id']).json()['image']['id']
    main.login_attempts.clear()
    logged.post('/api/accounts', json={'username': 'inner', 'password': 'inner-password-1', 'role': 'staff'})
    logged.post('/api/accounts', json={'username': 'outsider', 'password': 'outsider-password-1', 'role': 'external'})

    def session(username, password, port):
        client = TestClient(main.app, base_url='http://localhost', client=('10.20.0.' + str(port % 200), port))
        client.post('/api/login', json={'username': username, 'password': password})
        return client

    with session('inner', 'inner-password-1', 7100) as inner, \
         session('outsider', 'outsider-password-1', 7200) as outer:
        cases = [
            # (description, callable, admin, staff, external)
            ('read images', lambda c: c.get('/api/images'), 200, 200, 200),
            ('download', lambda c: c.get('/api/images/' + image_id + '/file'), 200, 200, 200),
            ('read products', lambda c: c.get('/api/products'), 200, 200, 200),
            ('upload', lambda c: c.post('/api/images/upload', data={'product_id': entry['id']},
                                        files={'file': ('m.png', png(), 'image/png')}), 200, 200, 403),
            ('create product', lambda c: c.post('/api/products', json={'code': 'M-1', 'name': '矩阵产品'}), 200, 200, 403),
            ('edit image', lambda c: c.put('/api/images/' + image_id,
                                           json={'kind': '产品图', 'angle': '仰视', 'background': '透明', 'tags': []}), 200, 200, 403),
            ('create token', lambda c: c.post('/api/tokens', json={'name': '矩阵令牌'}), 200, 200, 403),
            ('delete image', lambda c: c.request('DELETE', '/api/images/' + image_id), 200, 403, 403),
            ('trash view', lambda c: c.get('/api/images?trash=true'), 200, 403, 403),
            ('manage accounts', lambda c: c.get('/api/accounts'), 200, 403, 403),
            ('audit log', lambda c: c.get('/api/audit'), 200, 403, 403),
        ]
        for label, call, expected_admin, expected_staff, expected_external in cases:
            actual = (logged.get('/api/status').status_code, call(inner).status_code, call(outer).status_code)
            expected = (expected_admin, expected_staff, expected_external)
            assert actual == expected, f'{label}: {actual} != {expected}'
        # The category deletion endpoint is also administrator-only.
        assert inner.request('DELETE', '/api/categories', json={'name': 'x'}).status_code == 403


def test_network_addresses_are_admin_only(logged):
    result = logged.get('/api/network')
    assert result.status_code == 200
    addresses = result.json()['addresses']
    assert isinstance(addresses, list)
    assert all(not address.startswith('127.') and not address.startswith('169.254.') for address in addresses)
    headers = {'Authorization': 'Bearer ' + token(logged)['token']}
    assert logged.get('/api/network', headers=headers).status_code == 403
    assert logged.get('/api/network', headers={'Authorization': 'Bearer bad'}).status_code == 401


def test_readonly_token_and_revocation(logged):
    entry = product(logged)
    image = upload(logged, entry['id']).json()['image']
    secret = token(logged)
    headers = {'Authorization': 'Bearer ' + secret['token']}
    assert logged.get('/api/images', headers=headers).status_code == 200
    assert logged.get(image['download_url'], headers=headers).status_code == 200
    assert logged.get('/api/tokens', headers=headers).status_code == 403
    assert logged.post('/api/products', json={'code':'x','name':'x'}, headers=headers).status_code == 403
    assert logged.delete('/api/images/' + image['id'], headers=headers).status_code == 403
    assert logged.post('/api/images/upload', files={'file': ('x.png', png(), 'image/png')}, headers=headers).status_code == 403
    assert secret['token'] not in logged.get('/api/tokens').text
    assert secret['token'] not in logged.get('/api/audit').text
    assert logged.delete('/api/tokens/' + secret['id']).status_code == 200
    assert logged.get('/api/images', headers=headers).status_code == 401


def test_trash_restore_and_hidden_from_tools(logged):
    image = upload(logged).json()['image']
    headers = {'Authorization': 'Bearer ' + token(logged)['token']}
    assert logged.delete('/api/images/' + image['id']).status_code == 200
    assert logged.get('/api/images').json()['total'] == 0
    assert logged.get('/api/images?trash=true').json()['total'] == 1
    assert logged.get(image['download_url']).status_code == 404
    assert logged.get(image['thumbnail_url']).status_code == 200
    assert logged.get(image['thumbnail_url'], headers=headers).status_code == 404
    assert logged.get('/api/images?trash=true', headers=headers).status_code == 403
    assert len(list(main.ORIGINALS.iterdir())) == 1
    assert logged.post('/api/images/' + image['id'] + '/restore').status_code == 200
    assert logged.get(image['download_url']).content == png()


def test_batch_export_and_reassociation(logged):
    image = upload(logged).json()['image']
    entry = product(logged)
    edited = logged.put('/api/images/' + image['id'], json={'product_id': entry['id'], 'kind':'场景图', 'angle':'侧面', 'background':'透明', 'tags':['无文案']})
    assert edited.status_code == 200, edited.text
    assert logged.get('/api/overview').json()['unassigned'] == 0
    result = logged.post('/api/export', json={'image_ids':[image['id'],image['id']]})
    assert result.status_code == 200
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        assert len(archive.namelist()) == 1
        assert archive.namelist()[0].startswith('001234_场景图_侧面_')
        assert archive.read(archive.namelist()[0]) == png()
    assert not list(main.TEMP.iterdir())
    assert logged.get('/api/images/../../requirements.txt/file').status_code == 404


def test_logout_invalidates_session_and_login_works(logged):
    assert logged.post('/api/logout').status_code == 200
    assert logged.get('/api/images').status_code == 401
    assert logged.post('/api/login', json={'username':'qa-admin','password':'wrong'}).status_code == 401
    assert logged.post('/api/login', json={'username':'qa-admin','password':'temporary-test-password'}).status_code == 200
    assert logged.get('/api/status').json()['logged_in']


def test_permanent_delete_requires_trash_and_removes_files(logged):
    image = upload(logged).json()['image']
    live = logged.post('/api/images/delete', json={'image_ids': [image['id']]})
    assert live.status_code == 409
    assert logged.get(image['download_url']).status_code == 200
    assert logged.delete('/api/images/' + image['id']).status_code == 200
    result = logged.post('/api/images/delete', json={'image_ids': [image['id']]})
    assert result.status_code == 200, result.text
    assert result.json() == {'ok': True, 'deleted': 1}
    assert logged.get('/api/images?trash=true').json()['total'] == 0
    assert logged.get('/api/images/' + image['id']).status_code == 404
    assert not list(main.ORIGINALS.iterdir())
    assert not list(main.THUMBS.iterdir())
    assert logged.get('/api/audit').json()['items'][0]['action'] == '永久删除图片'
    assert logged.post('/api/images/delete', json={'image_ids': ['../etc/passwd']}).status_code == 400
    assert logged.post('/api/images/delete', json={'image_ids': ['0' * 32]}).status_code == 404
    headers = {'Authorization': 'Bearer ' + token(logged)['token']}
    assert logged.post('/api/images/delete', json={'image_ids': [image['id']]}, headers=headers).status_code == 403


def test_startup_clears_leftover_temporary_files(service):
    leftover = main.TEMP / 'crashed.upload'
    kept = main.ORIGINALS / 'keep.png'
    leftover.write_bytes(b'partial')
    kept.write_bytes(b'original')
    with TestClient(main.app, base_url='http://localhost', client=('127.0.0.1', 10000)):
        pass
    assert not leftover.exists()
    assert kept.read_bytes() == b'original'


def test_backup_contains_recoverable_originals_and_database(logged, tmp_path, monkeypatch):
    import manage
    entry = product(logged)
    image = upload(logged, entry['id']).json()['image']
    logged.delete('/api/images/' + image['id'])
    monkeypatch.setattr(manage, 'DATA', main.DATA)
    destination = tmp_path.parent / (tmp_path.name + '-backup')
    manage.backup(destination)
    with sqlite3.connect(destination / 'library.sqlite3') as connection:
        assert connection.execute('SELECT code FROM products').fetchone()[0] == '001234'
        assert connection.execute('SELECT count(*) FROM sessions').fetchone()[0] == 0
        assert connection.execute('SELECT deleted_at FROM images').fetchone()[0] is not None
    assert (destination / 'originals' / (image['id'] + '.png')).read_bytes() == png()
    assert (destination / 'thumbnails' / (image['id'] + '.webp')).exists()
    with pytest.raises(ValueError):
        manage.backup(main.DATA / 'invalid-backup')


def test_https_proxy_origin_and_cookie_flag(service, monkeypatch):
    monkeypatch.setenv('ASSET_PUBLIC_ORIGIN', 'https://assets.company.internal')
    monkeypatch.setenv('ASSET_ALLOWED_HOSTS', 'assets.company.internal')
    result = service.post('/api/setup', json={'username':'admin','password':'temporary-test-password'},
                          headers={'Host':'assets.company.internal','Origin':'https://assets.company.internal'})
    assert result.status_code == 200
    assert 'Secure' in result.headers['set-cookie']


def test_account_passwords_stay_out_of_urls_and_external_can_logout(logged):
    created = logged.post('/api/accounts', json={'username': 'client', 'password': 'client-password-1', 'role': 'external'})
    assert created.status_code == 200 and '?' not in str(created.request.url)
    account_id = created.json()['id']
    # A password in the query string must never be accepted.
    assert logged.put('/api/accounts/' + account_id, params={'password': 'client-password-9'},
                      json={'password': 'client-password-2'}).status_code == 200
    schema = logged.get('/api/openapi.json').json()['paths']['/api/accounts/{identifier}']
    # Passwords belong in the body; the URL may only carry the account identifier.
    for method in ('put', 'delete'):
        assert [p['name'] for p in schema[method].get('parameters', [])] == ['identifier']
        assert all(p['in'] == 'path' for p in schema[method].get('parameters', []))
    with TestClient(main.app, base_url='http://localhost', client=('192.168.1.40', 1000)) as viewer:
        assert viewer.post('/api/login', json={'username': 'client', 'password': 'client-password-2'}).status_code == 200
        assert viewer.get('/api/status').json()['logged_in'] is True
        assert viewer.get('/api/overview').status_code == 200
        assert viewer.post('/api/logout').status_code == 200
        assert viewer.get('/api/images').status_code == 401
        assert viewer.get('/api/status').json()['role'] is None
    response = logged.request('DELETE', '/api/accounts/' + account_id)
    assert response.status_code == 200 and '?' not in str(response.request.url)


def test_locked_file_is_queued_without_a_broken_restore(logged, monkeypatch):
    from pathlib import Path
    item = upload(logged).json()['image']
    logged.delete('/api/images/' + item['id'])
    thumb = main.THUMBS / (item['id'] + '.webp')
    real_unlink = Path.unlink
    def fail_thumbnail(path, *args, **kwargs):
        if path == thumb:
            raise PermissionError('simulated file lock')
        return real_unlink(path, *args, **kwargs)
    with monkeypatch.context() as scoped:
        scoped.setattr(Path, 'unlink', fail_thumbnail)
        response = logged.post('/api/images/delete', json={'image_ids': [item['id']]})
    assert response.status_code == 200
    assert response.json()['cleanup_pending'] == 1
    assert logged.get('/api/images?trash=true').json()['total'] == 0
    assert logged.post('/api/images/' + item['id'] + '/restore').status_code == 404
    assert thumb.exists()
    assert main.clean_pending_files() == 0
    assert not thumb.exists()
    with main.db() as con:
        assert con.execute('SELECT count(*) FROM pending_deletes').fetchone()[0] == 0


def test_failed_database_delete_keeps_files_and_record(logged):
    item = upload(logged).json()['image']
    logged.delete('/api/images/' + item['id'])
    with main.db() as con:
        con.execute("CREATE TRIGGER fail_delete BEFORE DELETE ON images BEGIN SELECT RAISE(ABORT, 'simulated database failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        logged.post('/api/images/delete', json={'image_ids': [item['id']]})
    assert logged.get('/api/images?trash=true').json()['total'] == 1
    assert (main.ORIGINALS / (item['id'] + '.png')).exists()
    assert (main.THUMBS / (item['id'] + '.webp')).exists()
    with main.db() as con:
        assert con.execute('SELECT count(*) FROM pending_deletes').fetchone()[0] == 0


def test_startup_finishes_delete_committed_before_a_crash(logged, monkeypatch):
    item = upload(logged).json()['image']
    logged.delete('/api/images/' + item['id'])
    def interrupted(**kwargs):
        raise RuntimeError('simulated shutdown after database commit')
    with monkeypatch.context() as scoped:
        scoped.setattr(main, 'clean_pending_files', interrupted)
        with pytest.raises(RuntimeError):
            logged.post('/api/images/delete', json={'image_ids': [item['id']]})
    assert logged.get('/api/images?trash=true').json()['total'] == 0
    assert (main.ORIGINALS / (item['id'] + '.png')).exists()
    with TestClient(main.app, base_url='http://localhost', client=('127.0.0.1', 1000)):
        pass
    assert not (main.ORIGINALS / (item['id'] + '.png')).exists()
    with main.db() as con:
        assert con.execute('SELECT count(*) FROM pending_deletes').fetchone()[0] == 0


def test_backup_and_permanent_delete_do_not_overlap(logged, tmp_path, monkeypatch):
    import manage
    import threading
    from concurrent.futures import ThreadPoolExecutor
    item = upload(logged).json()['image']
    logged.delete('/api/images/' + item['id'])
    monkeypatch.setattr(manage, 'DATA', main.DATA)
    destination = tmp_path.parent / (tmp_path.name + '-concurrent-backup')
    copying, release, deleting = threading.Event(), threading.Event(), threading.Event()
    real_copy = manage.shutil.copy2
    def paused_copy(source, target, *args, **kwargs):
        copying.set()
        assert release.wait(5)
        return real_copy(source, target, *args, **kwargs)
    monkeypatch.setattr(manage.shutil, 'copy2', paused_copy)
    def remove():
        deleting.set()
        return logged.post('/api/images/delete', json={'image_ids': [item['id']]})
    with ThreadPoolExecutor(max_workers=2) as pool:
        backup_job = pool.submit(manage.backup, destination)
        try:
            assert copying.wait(5)
            delete_job = pool.submit(remove)
            assert deleting.wait(5)
            assert not delete_job.done()
        finally:
            release.set()
        backup_job.result(timeout=10)
        assert delete_job.result(timeout=10).status_code == 200
    assert (destination / 'backup.json').exists()
    assert (destination / 'originals' / (item['id'] + '.png')).read_bytes() == png()
    assert not (main.ORIGINALS / (item['id'] + '.png')).exists()


def test_storage_lock_also_coordinates_other_processes(tmp_path):
    import subprocess
    import sys
    from storage import storage_lock
    script = "from pathlib import Path; from storage import storage_lock; import sys;\ntry:\n with storage_lock(Path(sys.argv[1]),timeout=.2): print('acquired')\nexcept TimeoutError: print('busy')"
    with storage_lock(tmp_path):
        result = subprocess.run([sys.executable, '-c', script, str(tmp_path)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0 and result.stdout.strip() == 'busy', result.stderr
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0 and result.stdout.strip() == 'acquired', result.stderr
