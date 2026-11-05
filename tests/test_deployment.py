import pytest
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

import serve
from app import main
from test_library import service, logged


def test_launcher_defaults_and_explicit_proxy_trust(monkeypatch):
    options = {}
    monkeypatch.setattr(serve.uvicorn, 'run', lambda app, **kwargs: options.update(kwargs))
    monkeypatch.delenv('ASSET_TRUSTED_PROXIES', raising=False)
    # Uvicorn's ambient setting must not silently enable trust in LAN mode.
    monkeypatch.setenv('FORWARDED_ALLOW_IPS', '*')
    serve.main([])
    assert options['proxy_headers'] is False
    assert options['forwarded_allow_ips'] == ''
    monkeypatch.setenv('ASSET_TRUSTED_PROXIES', '127.0.0.1, ::1')
    serve.main([])
    assert options['proxy_headers'] is True
    assert options['forwarded_allow_ips'] == '127.0.0.1,::1'


@pytest.mark.parametrize('value', ['*', '0.0.0.0/0', '127.0.0.1,*', 'localhost', '127.0.0.1,'])
def test_launcher_rejects_invalid_or_unbounded_proxy_trust(monkeypatch, value):
    monkeypatch.setenv('ASSET_TRUSTED_PROXIES', value)
    with pytest.raises(SystemExit) as error:
        serve.main([])
    assert error.value.code == 2


def test_setup_is_local_and_can_be_disabled(service, monkeypatch):
    credentials = {'username': 'qa-admin', 'password': 'temporary-test-password'}
    assert service.get('/api/status').json()['can_setup'] is True
    for headers in ({'X-Forwarded-For': '127.0.0.1'}, {'X-Forwarded-Proto': 'https'}, {'Forwarded': 'for=127.0.0.1'}):
        assert service.get('/api/status', headers=headers).json()['can_setup'] is False
        assert service.post('/api/setup', json=credentials, headers=headers).status_code == 403
    monkeypatch.setenv('ASSET_DISABLE_SETUP', '1')
    assert service.get('/api/status').json()['can_setup'] is False
    assert service.post('/api/setup', json=credentials).status_code == 403


def test_public_origin_is_shared_without_changing_lan_discovery(logged, monkeypatch):
    monkeypatch.setattr(main, 'local_addresses', lambda: ['10.1.2.3'])
    monkeypatch.delenv('ASSET_PUBLIC_ORIGIN', raising=False)
    assert logged.get('/api/network').json() == {'addresses': ['10.1.2.3'], 'public_origin': ''}
    monkeypatch.setenv('ASSET_PUBLIC_ORIGIN', 'https://assets.company.example/')
    assert logged.get('/api/network').json()['public_origin'] == 'https://assets.company.example'


def test_proxy_login_limits_use_client_address_and_secure_cookie(logged, monkeypatch):
    monkeypatch.setenv('ASSET_ALLOWED_HOSTS', 'assets.company.example')
    monkeypatch.setenv('ASSET_PUBLIC_ORIGIN', 'https://assets.company.example')
    monkeypatch.setenv('ASSET_DISABLE_SETUP', '1')
    app = ProxyHeadersMiddleware(main.app, trusted_hosts='127.0.0.1')
    bad_credentials = {'username': 'qa-admin', 'password': 'wrong-password'}
    first = {'X-Forwarded-For': '10.1.2.10', 'X-Forwarded-Proto': 'https', 'Origin': 'https://assets.company.example'}
    with TestClient(app, base_url='https://assets.company.example', client=('127.0.0.1', 10000)) as proxy:
        for _ in range(8):
            assert proxy.post('/api/login', json=bad_credentials, headers=first).status_code == 401
        assert proxy.post('/api/login', json=bad_credentials, headers=first).status_code == 429
        second = dict(first, **{'X-Forwarded-For': '10.1.2.11'})
        response = proxy.post('/api/login', json={'username': 'qa-admin', 'password': 'temporary-test-password'}, headers=second)
        assert response.status_code == 200
        assert 'secure' in response.headers['set-cookie'].lower()
        assert proxy.get('/api/network', headers=second).json()['public_origin'] == 'https://assets.company.example'
        assert not proxy.get('/api/status', headers=second).json()['can_setup']


def test_untrusted_peer_cannot_bypass_login_limit_by_forging_headers(logged):
    app = ProxyHeadersMiddleware(main.app, trusted_hosts='127.0.0.1')
    with TestClient(app, base_url='http://localhost', client=('10.1.2.12', 10000)) as remote:
        for index in range(9):
            result = remote.post('/api/login', json={'username': 'qa-admin', 'password': 'wrong-password'},
                                 headers={'X-Forwarded-For': f'10.2.0.{index + 1}'})
            assert result.status_code == (401 if index < 8 else 429)
