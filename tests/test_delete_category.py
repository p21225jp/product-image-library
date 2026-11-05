import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import main
from test_library import isolated_login_limits, service, logged, product, upload, png, token


def preview(session, name, **options):
    response = session.get('/api/categories/deletion-preview', params={'name': name}, **options)
    assert response.status_code == 200, response.text
    return response.json()


def remove(session, impact, **options):
    return session.request('DELETE', '/api/categories', json={
        'name': impact['name'], 'preview_token': impact['preview_token']}, **options)


def test_delete_category_unlinks_all_its_images_keeps_products_and_files(logged):
    first = product(logged, code='001234', category='显示器')
    second = product(logged, code='001235', category='显示器')
    other = product(logged, code='009999', category='主板')
    active = upload(logged, first['id'], tags='官方,原图').json()['image']
    trashed = upload(logged, second['id'], data=png(color=(5, 5, 5, 100))).json()['image']
    untouched = upload(logged, other['id']).json()['image']
    unassigned = upload(logged).json()['image']
    original = logged.get(active['download_url']).content
    thumbnail = logged.get(active['thumbnail_url']).content
    logged.delete('/api/images/' + trashed['id']).raise_for_status()
    info = preview(logged, '显示器')
    assert (info['product_count'], info['image_count'], info['trashed_image_count'], info['total_unlinked']) == (2, 1, 1, 2)
    managed = logged.get('/api/categories/manage').json()['items']
    assert next(c for c in managed if c['name'] == '显示器')['image_count'] == 1
    result = remove(logged, info)
    assert result.status_code == 200, result.text
    assert result.json()['total_unlinked'] == 2
    assert 'preview_token' not in result.json()
    assert logged.get('/api/categories').json()['items'] == ['主板']
    for entry in [first, second]:
        row = logged.get('/api/products', params={'q': entry['code']}).json()['items'][0]
        assert row['id'] == entry['id'] and row['category'] == '' and row['image_count'] == 0
        assert row['name'] == entry['name'] and row['aliases'] == entry['aliases']
    item = logged.get('/api/images/' + active['id']).json()
    assert item['product_id'] is None and item['tags'] == ['官方', '原图']
    assert logged.get(active['download_url']).content == original
    assert logged.get(active['thumbnail_url']).content == thumbnail
    assert logged.get('/api/images/' + untouched['id']).json()['product_id'] == other['id']
    assert logged.get('/api/images/' + unassigned['id']).json()['product_id'] is None
    with main.db() as con:
        trashed_row = con.execute('SELECT * FROM images WHERE id=?', (trashed['id'],)).fetchone()
        assert trashed_row['product_id'] is None and trashed_row['deleted_at'] is not None
    logged.post('/api/images/' + trashed['id'] + '/restore').raise_for_status()
    assert logged.get('/api/images/' + trashed['id']).json()['product_id'] is None
    main.initialize()
    assert '显示器' not in logged.get('/api/categories').json()['items']
    assert logged.get('/api/products').json()['total'] == 3
    audit = logged.get('/api/audit').json()['items']
    assert any(a['action'] == '删除分类并解绑图片' and '显示器' in a['detail'] for a in audit)


def test_empty_category_and_names_with_slashes_are_supported(logged):
    logged.post('/api/categories', json={'name': '配件 / 零件 & 其他'}).raise_for_status()
    info = preview(logged, '配件 / 零件 & 其他')
    assert info['product_count'] == info['total_unlinked'] == 0
    assert remove(logged, info).status_code == 200
    assert remove(logged, info).status_code == 404


def test_category_delete_matches_legacy_case_and_normalization(logged):
    entry = product(logged, category='SSD')
    image = upload(logged, entry['id']).json()['image']
    with main.db() as con:
        con.execute("UPDATE products SET category='ssd' WHERE id=?", (entry['id'],))
    info = preview(logged, 'ＳＳＤ')
    assert info['name'] == 'SSD' and info['product_count'] == 1 and info['image_count'] == 1
    assert remove(logged, info).status_code == 200
    assert logged.get('/api/images/' + image['id']).json()['product_id'] is None
    assert logged.get('/api/products').json()['items'][0]['category'] == ''


@pytest.mark.parametrize('legacy_name', ['ＳＳＤ', ' SSD '])
def test_legacy_category_identity_is_preserved_before_normalizing(logged, legacy_name):
    ordinary = product(logged, code='ascii', category='SSD')
    legacy = product(logged, code='legacy')
    with main.db() as con:
        con.execute('INSERT INTO categories(name) VALUES(?)', (legacy_name,))
        con.execute('UPDATE products SET category=? WHERE id=?', (legacy_name, legacy['id']))
    info = preview(logged, legacy_name)
    assert info['name'] == legacy_name and info['product_count'] == 1
    assert remove(logged, info).status_code == 200
    assert logged.get('/api/products', params={'q': ordinary['code']}).json()['items'][0]['category'] == 'SSD'
    assert logged.get('/api/products', params={'q': legacy['code']}).json()['items'][0]['category'] == ''


@pytest.mark.parametrize('change', ['new_product', 'new_image', 'moved_image', 'trashed_image'])
def test_delete_refuses_changed_impact_without_partial_updates(logged, change):
    target = product(logged, category='显示器')
    image = upload(logged, target['id']).json()['image']
    info = preview(logged, '显示器')
    if change == 'new_product':
        product(logged, code='new', category='显示器')
    elif change == 'new_image':
        upload(logged, target['id'], data=png(color=(5, 5, 5, 100))).raise_for_status()
    elif change == 'moved_image':
        with main.db() as con:
            con.execute('UPDATE images SET product_id=NULL WHERE id=?', (image['id'],))
    else:
        logged.delete('/api/images/' + image['id']).raise_for_status()
    assert remove(logged, info).status_code == 409
    assert '显示器' in logged.get('/api/categories').json()['items']
    assert logged.get('/api/products', params={'q': target['code']}).json()['items'][0]['category'] == '显示器'
    assert remove(logged, preview(logged, '显示器')).status_code == 200


def test_delete_rolls_back_everything_when_database_write_fails(logged):
    target = product(logged, category='显示器')
    image = upload(logged, target['id']).json()['image']
    info = preview(logged, '显示器')
    with main.db() as con:
        con.execute("CREATE TRIGGER block_category_delete BEFORE DELETE ON categories BEGIN SELECT RAISE(ABORT,'test error'); END")
    with pytest.raises(sqlite3.IntegrityError):
        remove(logged, info)
    assert logged.get('/api/images/' + image['id']).json()['product_id'] == target['id']
    assert logged.get('/api/products').json()['items'][0]['category'] == '显示器'
    assert logged.get('/api/categories').json()['items'] == ['显示器']
    assert not any(a['action'] == '删除分类并解绑图片' for a in logged.get('/api/audit').json()['items'])


def test_permissions_validation_and_csrf(logged):
    product(logged, category='显示器')
    info = preview(logged, '显示器')
    readonly = token(logged)
    headers = {'Authorization': 'Bearer ' + readonly['token']}
    assert remove(logged, info, headers=headers).status_code == 403
    assert logged.get('/api/categories/manage', headers=headers).status_code == 403
    assert logged.get('/api/categories/deletion-preview', params={'name': '显示器'}, headers=headers).status_code == 403
    assert remove(logged, info, headers={'Origin': 'https://untrusted.example'}).status_code == 403
    assert logged.request('DELETE', '/api/categories', json={'name': '显示器'}).status_code == 422
    logged.post('/api/accounts', json={'username': 'viewer', 'password': 'category-viewer-password', 'role': 'external'}).raise_for_status()
    with TestClient(main.app, base_url='http://localhost', client=('127.0.0.1', 10001)) as visitor:
        assert remove(visitor, info).status_code == 401
        visitor.post('/api/login', json={'username': 'viewer', 'password': 'category-viewer-password'}).raise_for_status()
        assert remove(visitor, info).status_code == 403
        assert visitor.get('/api/categories/manage').status_code == 403
    assert logged.get('/api/categories').json()['items'] == ['显示器']


def test_deleted_category_cannot_be_used_by_product_writer(logged):
    target = product(logged, category='显示器')
    remove(logged, preview(logged, '显示器')).raise_for_status()
    body = {'code': 'other', 'name': '产品', 'category': '显示器'}
    assert logged.post('/api/products', json=body).status_code == 400
    assert logged.put('/api/products/' + target['id'], json=body).status_code == 400
    assert logged.get('/api/products').json()['total'] == 1
