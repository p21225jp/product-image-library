import importlib.util
from pathlib import Path

import pytest
import tomli

spec = importlib.util.spec_from_file_location('authorize_mcp_admin', Path(__file__).resolve().parents[1] / 'scripts' / 'authorize_mcp_admin.py')
authorization = importlib.util.module_from_spec(spec)
spec.loader.exec_module(authorization)


def fixture_config(tmp_path):
    path = tmp_path / 'config.toml'
    path.write_text('model = "existing-model"\n[mcp_servers.mkt_asset_library]\ncommand = "python"\n[mcp_servers.mkt_asset_library.env]\nASSET_SERVER_URL = "https://library.example"\nASSET_API_TOKEN = "existing-read-token"\n[mcp_servers.other]\ncommand = "other-command"\n', encoding='utf-8')
    return path


def test_credential_update_preserves_other_configuration(tmp_path):
    path = fixture_config(tmp_path)
    authorization.update_mcp_env(path, {'ASSET_WRITE_API_TOKEN': 'test"quoted\\credential', 'ASSET_SITES_TOKEN': 'site-only-credential'}, 'https://library.example/')
    data = tomli.loads(path.read_text(encoding='utf-8'))
    assert data['model'] == 'existing-model'
    assert data['mcp_servers']['other']['command'] == 'other-command'
    assert data['mcp_servers']['mkt_asset_library']['env']['ASSET_API_TOKEN'] == 'existing-read-token'
    assert data['mcp_servers']['mkt_asset_library']['env']['ASSET_WRITE_API_TOKEN'] == 'test"quoted\\credential'
    assert list(tmp_path.iterdir()) == [path]


def test_origin_mismatch_never_saves_credentials(tmp_path):
    path = fixture_config(tmp_path)
    original = path.read_bytes()
    with pytest.raises(ValueError, match='origin'):
        authorization.update_mcp_env(path, {'ASSET_SITES_TOKEN': 'not-for-other-origin'}, 'https://other.example')
    assert path.read_bytes() == original


def test_association_grant_is_saved_separately(tmp_path):
    path = fixture_config(tmp_path)
    authorization.update_mcp_env(path, {'ASSET_ASSOCIATE_API_TOKEN': 'test-associate-only'}, 'https://library.example')
    env = tomli.loads(path.read_text(encoding='utf-8'))['mcp_servers']['mkt_asset_library']['env']
    assert env['ASSET_ASSOCIATE_API_TOKEN'] == 'test-associate-only'
    assert env['ASSET_API_TOKEN'] == 'existing-read-token'
    assert 'ASSET_WRITE_API_TOKEN' not in env


def test_cannot_change_server_or_unrelated_settings(tmp_path):
    path = fixture_config(tmp_path)
    original = path.read_bytes()
    with pytest.raises(ValueError):
        authorization.update_mcp_env(path, {'ASSET_SERVER_URL': 'https://other.example'}, 'https://library.example')
    assert path.read_bytes() == original


def test_combined_grant_removes_only_legacy_association_key(tmp_path):
    path = fixture_config(tmp_path)
    authorization.update_mcp_env(path, {'ASSET_WRITE_API_TOKEN': 'old-create', 'ASSET_ASSOCIATE_API_TOKEN': 'old-assoc'}, 'https://library.example')
    authorization.update_mcp_env(path, {'ASSET_WRITE_API_TOKEN': 'new-combined'}, 'https://library.example', remove_keys=('ASSET_ASSOCIATE_API_TOKEN',))
    data = tomli.loads(path.read_text(encoding='utf-8'))
    env = data['mcp_servers']['mkt_asset_library']['env']
    assert env['ASSET_WRITE_API_TOKEN'] == 'new-combined'
    assert 'ASSET_ASSOCIATE_API_TOKEN' not in env
    assert env['ASSET_API_TOKEN'] == 'existing-read-token'
    assert data['mcp_servers']['other']['command'] == 'other-command'


def test_credential_removal_rejects_unrelated_keys(tmp_path):
    path = fixture_config(tmp_path)
    original = path.read_bytes()
    with pytest.raises(ValueError):
        authorization.update_mcp_env(path, {'ASSET_WRITE_API_TOKEN': 'new'}, 'https://library.example', remove_keys=('ASSET_SERVER_URL',))
    assert path.read_bytes() == original


def test_default_authorization_issues_one_grant_for_both_tools(tmp_path, monkeypatch):
    import httpx
    path = fixture_config(tmp_path)
    authorization.update_mcp_env(path, {'ASSET_WRITE_API_TOKEN': 'old-create', 'ASSET_ASSOCIATE_API_TOKEN': 'old-assoc'}, 'https://library.example')
    grants = []
    def respond(request):
        if request.url.path == '/api/status':
            combined = request.headers.get('Authorization') == 'Bearer new-combined'
            return httpx.Response(200, json={'can_create_products': True, 'can_associate_images': combined})
        if request.url.path == '/api/login':
            return httpx.Response(200, json={'role': 'admin'})
        if request.url.path == '/api/tokens':
            import json
            grants.append(json.loads(request.content))
            return httpx.Response(200, json={'id': 'a'*32, 'scope': authorization.COMBINED_SCOPE, 'token': 'new-combined'})
        assert request.url.path == '/api/logout'
        return httpx.Response(200, json={})
    original = httpx.Client
    monkeypatch.setattr(authorization.httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(respond), **kw))
    monkeypatch.setattr('builtins.input', lambda _: 'test-admin')
    monkeypatch.setattr(authorization.getpass, 'getpass', lambda _: 'synthetic-test-password')
    result = authorization.authorize(path)
    assert result['scope'] == authorization.COMBINED_SCOPE
    assert len(grants) == 1 and grants[0]['scope'] == authorization.COMBINED_SCOPE
    env = tomli.loads(path.read_text(encoding='utf-8'))['mcp_servers']['mkt_asset_library']['env']
    assert env['ASSET_WRITE_API_TOKEN'] == 'new-combined'
    assert 'ASSET_ASSOCIATE_API_TOKEN' not in env
    assert env['ASSET_API_TOKEN'] == 'existing-read-token'
