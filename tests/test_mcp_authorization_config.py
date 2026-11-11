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


def test_cannot_change_server_or_unrelated_settings(tmp_path):
    path = fixture_config(tmp_path)
    original = path.read_bytes()
    with pytest.raises(ValueError):
        authorization.update_mcp_env(path, {'ASSET_SERVER_URL': 'https://other.example'}, 'https://library.example')
    assert path.read_bytes() == original
