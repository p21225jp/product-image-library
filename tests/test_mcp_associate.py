import json
import httpx
import pytest
import mcp_bridge as bridge


def configure(monkeypatch, handler, token='img_associate'):
    original = httpx.Client
    monkeypatch.setattr(bridge, 'SERVER_URL', 'https://library.example')
    monkeypatch.setattr(bridge, 'API_TOKEN', 'img_read')
    monkeypatch.setattr(bridge, 'WRITE_API_TOKEN', 'img_create')
    monkeypatch.setattr(bridge, 'ASSOCIATE_API_TOKEN', token)
    monkeypatch.setattr(bridge, 'SITES_TOKEN', 'site-access')
    monkeypatch.setattr(bridge.httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))


def test_association_uses_exact_sku_and_separate_grant(monkeypatch):
    requests = []
    def respond(request):
        requests.append(request)
        assert request.headers['Authorization'] == 'Bearer img_associate'
        assert request.headers['OAI-Sites-Authorization'] == 'Bearer site-access'
        if request.method == 'GET':
            assert request.url.params['q'] == '000123'
            return httpx.Response(200, json={'items': [
                {'id': 'b'*32, 'code': '123', 'name': 'wrong'},
                {'id': 'a'*32, 'code': '000123', 'name': 'right'}]})
        assert request.url.path == '/api/products/'+'a'*32+'/images/associate'
        assert json.loads(request.content) == {'image_ids': ['c'*32]}
        return httpx.Response(200, json={'associated': 1, 'already_associated': 0})
    configure(monkeypatch, respond)
    result = bridge.associate_images('000123', ['c'*32, 'c'*32])
    assert result['product_sku'] == '000123'
    assert len(requests) == 2


def test_missing_association_grant_never_uses_other_tokens(monkeypatch):
    configure(monkeypatch, lambda r: pytest.fail('No network allowed'), token='')
    monkeypatch.setattr(bridge, 'WRITE_API_TOKEN', '')
    with pytest.raises(ValueError, match='ASSET_ASSOCIATE_API_TOKEN'):
        bridge.associate_images('001', ['c'*32])


def test_one_combined_write_token_serves_both_tools(monkeypatch):
    calls = []
    def respond(request):
        calls.append(request)
        assert request.headers['Authorization'] == 'Bearer img_combined'
        if request.method == 'GET':
            return httpx.Response(200, json={'items': [{'id': 'a'*32, 'code': '0001', 'name': 'board'}]})
        if request.url.path == '/api/products':
            return httpx.Response(200, json={'id': 'a'*32, 'code': '0001', 'name': 'board'})
        return httpx.Response(200, json={'associated': 1})
    configure(monkeypatch, respond, token='')
    monkeypatch.setattr(bridge, 'WRITE_API_TOKEN', 'img_combined')
    bridge.create_product('0001', 'board')
    bridge.associate_images('0001', ['c'*32])
    assert len(calls) == 3


@pytest.mark.parametrize('sku,ids', [(123, ['c'*32]), (' ', ['c'*32]), ('001', []), ('001', ['c'*32]*101), ('001', ['bad']), ('001', [123])])
def test_invalid_input_cannot_write(monkeypatch, sku, ids):
    configure(monkeypatch, lambda r: pytest.fail('Invalid input reached network'))
    with pytest.raises(ValueError):
        bridge.associate_images(sku, ids)


def test_name_match_is_never_substituted_for_sku(monkeypatch):
    def respond(request):
        assert request.method == 'GET'
        return httpx.Response(200, json={'items': [{'id': 'a'*32, 'code': 'other', 'name': '001'}]})
    configure(monkeypatch, respond)
    with pytest.raises(ValueError, match='唯一'):
        bridge.associate_images('001', ['c'*32])


@pytest.mark.parametrize('status', [403, 409])
def test_denial_or_conflict_does_not_retry(monkeypatch, status):
    calls = []
    def respond(request):
        calls.append(request)
        if request.method == 'GET':
            return httpx.Response(200, json={'items': [{'id': 'a'*32, 'code': '001', 'name': 'board'}]})
        return httpx.Response(status, json={'detail': 'rejected'})
    configure(monkeypatch, respond)
    with pytest.raises(ValueError, match=str(status)):
        bridge.associate_images('001', ['c'*32])
    assert len(calls) == 2
