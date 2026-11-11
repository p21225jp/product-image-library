import json

import httpx
import pytest

import mcp_bridge as bridge


def configure(monkeypatch, handler, write_token='img_admin_create'):
    original_client = httpx.Client
    monkeypatch.setattr(bridge, 'SERVER_URL', 'https://library.example')
    monkeypatch.setattr(bridge, 'API_TOKEN', 'img_read_only')
    monkeypatch.setattr(bridge, 'WRITE_API_TOKEN', write_token)
    monkeypatch.setattr(bridge, 'SITES_TOKEN', 'official-site-credential')
    monkeypatch.setattr(bridge.httpx, 'Client', lambda **kwargs: original_client(
        transport=httpx.MockTransport(handler), **kwargs))


def test_create_uses_separate_write_credential_and_preserves_sku(monkeypatch):
    requests = []

    def respond(request):
        requests.append(request)
        assert request.url.host == 'library.example'
        assert request.headers['OAI-Sites-Authorization'] == 'Bearer official-site-credential'
        if request.method == 'POST':
            assert request.headers['Authorization'] == 'Bearer img_admin_create'
            assert request.url.path == '/api/products'
            payload = json.loads(request.content)
            assert payload == {'code': '0000123', 'name': '测试产品', 'category': '显示器', 'aliases': ['测试别名']}
            return httpx.Response(200, json={'id': 'a' * 32, **payload})
        assert request.headers['Authorization'] == 'Bearer img_read_only'
        return httpx.Response(200, json={'items': [], 'total': 0})

    configure(monkeypatch, respond)
    assert bridge.create_product('0000123', '测试产品', '显示器', ['测试别名'])['code'] == '0000123'
    bridge.search_products('0000123')
    assert len(requests) == 2


def test_no_write_credential_never_falls_back_to_read_token(monkeypatch):
    def unexpected(request):
        pytest.fail('No network request is allowed without a write credential')

    configure(monkeypatch, unexpected, write_token='')
    with pytest.raises(ValueError, match='ASSET_WRITE_API_TOKEN'):
        bridge.create_product('0000123', '测试产品')


@pytest.mark.parametrize('args', [
    (123, '产品'), (' ', '产品'), ('0001', ''),
    ('0001', '产品', ['显示器']), ('0001', '产品', '', '别名'),
    ('0001', '产品', '', ['x' * 101]),
])
def test_invalid_input_cannot_write(monkeypatch, args):
    monkeypatch.setattr(bridge, 'client', lambda **kwargs: pytest.fail('Invalid input must not reach the server'))
    with pytest.raises(ValueError):
        bridge.create_product(*args)


@pytest.mark.parametrize('status', [403, 409])
def test_denied_or_duplicate_request_is_not_retried_or_overwritten(monkeypatch, status):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, json={'detail': '需要授权' if status == 403 else 'SKU 已存在'})

    configure(monkeypatch, respond)
    with pytest.raises(ValueError, match=str(status)):
        bridge.create_product('0000123', '测试产品')
    assert len(requests) == 1


def test_uncertain_network_failure_does_not_retry_write(monkeypatch):
    requests = []

    def interrupted(request):
        requests.append(request)
        raise httpx.ReadTimeout('synthetic timeout')

    configure(monkeypatch, interrupted)
    with pytest.raises(bridge.LibraryToolError, match='先按 SKU 查询'):
        bridge.create_product('0000123', '测试产品')
    assert len(requests) == 1
