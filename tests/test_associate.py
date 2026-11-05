import concurrent.futures
import sqlite3
import uuid

import pytest
from fastapi.testclient import TestClient

from app import main
from test_library import isolated_login_limits, service, logged, product, upload, png, token


def associate(session, target, image_ids, **options):
    return session.post('/api/products/' + target['id'] + '/images/associate', json={'image_ids': image_ids}, **options)


def test_associate_multiple_images_preserves_files_and_attributes(logged):
    target = product(logged)
    images = [upload(logged, data=png(color=(i * 40, 80, 160, 100)), tags='官方,原图', angle='背面').json()['image'] for i in range(3)]
    before = [logged.get(image['download_url']).content for image in images]
    result = associate(logged, target, [image['id'] for image in images]).json()
    assert result['associated'] == 3 and result['image_count'] == 3 and result['already_associated'] == 0
    assert logged.get('/api/images?unassigned=true').json()['total'] == 0
    assert logged.get('/api/products').json()['items'][0]['image_count'] == 3
    for index, image in enumerate(images):
        item = logged.get('/api/images/' + image['id']).json()
        assert item['product_id'] == target['id']
        assert (item['tags'], item['kind'], item['angle'], item['background']) == (['官方', '原图'], '产品图', '背面', '透明')
        assert logged.get(image['download_url']).content == before[index]
    audit = logged.get('/api/audit').json()['items']
    record = next(row for row in audit if row['action'] == '批量关联产品图片')
    assert all(image['id'] in record['detail'] for image in images)


def test_associate_is_idempotent_and_deduplicates_ids(logged):
    target = product(logged)
    image = upload(logged).json()['image']
    first = associate(logged, target, [image['id'], image['id']]).json()
    second = associate(logged, target, [image['id']]).json()
    assert first['associated'] == 1 and first['image_count'] == 1
    assert second['associated'] == 0 and second['already_associated'] == 1 and second['image_count'] == 1
    with main.db() as con:
        assert con.execute("SELECT count(*) FROM audit WHERE action='批量关联产品图片'").fetchone()[0] == 1


def test_conflict_trash_and_missing_image_leave_whole_batch_unchanged(logged):
    target = product(logged)
    other = product(logged, code='other')
    free = upload(logged).json()['image']
    owned = upload(logged, other['id']).json()['image']
    assert associate(logged, target, [free['id'], owned['id']]).status_code == 409
    assert logged.get('/api/images/' + free['id']).json()['product_id'] is None
    assert logged.get('/api/images/' + owned['id']).json()['product_id'] == other['id']
    assert associate(logged, target, [free['id'], uuid.uuid4().hex]).status_code == 409
    trashed = upload(logged, data=png(color=(5, 5, 5, 100))).json()['image']
    logged.delete('/api/images/' + trashed['id']).raise_for_status()
    assert associate(logged, target, [free['id'], trashed['id']]).status_code == 409
    assert logged.get('/api/images/' + free['id']).json()['product_id'] is None


def test_two_products_cannot_claim_the_same_unassigned_images(logged):
    targets = [product(logged, code='a'), product(logged, code='b')]
    free = upload(logged).json()['image']
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda p: associate(logged, p, [free['id']]), targets))
    assert sorted(result.status_code for result in results) == [200, 409]
    winner = results.index(next(result for result in results if result.status_code == 200))
    assert logged.get('/api/images/' + free['id']).json()['product_id'] == targets[winner]['id']


def test_association_transaction_rolls_back_on_database_failure(logged):
    target = product(logged)
    images = [upload(logged, data=png(color=(i * 50, 10, 10, 100))).json()['image']['id'] for i in range(2)]
    with main.db() as con:
        con.execute("CREATE TRIGGER fail_association BEFORE UPDATE OF product_id ON images WHEN NEW.id='" + max(images) + "' BEGIN SELECT RAISE(ABORT,'test failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        associate(logged, target, images)
    assert logged.get('/api/images?unassigned=true').json()['total'] == 2
    with main.db() as con:
        assert con.execute("SELECT count(*) FROM audit WHERE action='批量关联产品图片'").fetchone()[0] == 0


def test_associate_permissions_limits_and_csrf(logged):
    target = product(logged)
    image = upload(logged).json()['image']
    readonly = token(logged)
    assert associate(logged, target, [image['id']], headers={'Authorization': 'Bearer ' + readonly['token']}).status_code == 403
    assert associate(logged, target, [], headers={'Origin': 'https://evil.example'}).status_code == 403
    assert associate(logged, target, []).status_code == 422
    assert associate(logged, target, [uuid.uuid4().hex for _ in range(101)]).status_code == 422
    assert associate(logged, target, ['invalid']).status_code == 400
    assert associate(logged, {'id': uuid.uuid4().hex}, [image['id']]).status_code == 404
    logged.post('/api/accounts', json={'username': 'viewer', 'password': 'associate-viewer-password', 'role': 'external'}).raise_for_status()
    with TestClient(main.app, base_url='http://localhost', client=('127.0.0.1', 54321)) as visitor:
        assert associate(visitor, target, [image['id']]).status_code == 401
        visitor.post('/api/login', json={'username': 'viewer', 'password': 'associate-viewer-password'}).raise_for_status()
        assert associate(visitor, target, [image['id']]).status_code == 403


def test_filename_search_finds_numeric_sku_without_changing_normal_search(logged):
    for name, shade in [('001234_正面.png', 10), ('001234_背面.png', 20), ('100%_侧面.png', 30)]:
        response = logged.post('/api/images/upload', files={'file': (name, png(color=(shade, 5, 5, 100)), 'image/png')})
        assert response.status_code == 200
    result = logged.get('/api/images', params={'filename': '001234', 'unassigned': True, 'limit': 1}).json()
    assert result['total'] == 2 and len(result['items']) == 1
    other = logged.get('/api/images', params={'filename': '001234', 'unassigned': True, 'limit': 1, 'offset': 1}).json()
    assert other['items'][0]['id'] != result['items'][0]['id']
    assert logged.get('/api/images', params={'filename': '%'}).json()['total'] == 1
    assert logged.get('/api/images', params={'q': '001234'}).json()['total'] == 0
