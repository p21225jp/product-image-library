"""Authorize Codex to create products without putting an admin password in chat or config."""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import re
import tempfile

import httpx
import tomli


MCP_NAME = 'mkt_asset_library'
ENV_HEADER = '[mcp_servers.mkt_asset_library.env]'
WRITABLE_KEYS = {'ASSET_WRITE_API_TOKEN', 'ASSET_SITES_TOKEN'}


def update_mcp_env(path: Path, changes: dict[str, str], expected_origin: str) -> None:
    """Update only this MCP's credentials, preserving all other Codex configuration."""
    if not changes or set(changes) - WRITABLE_KEYS:
        raise ValueError('Unsupported credential configuration key')
    source = path.read_text(encoding='utf-8-sig')
    config = tomli.loads(source)
    entry = config.get('mcp_servers', {}).get(MCP_NAME, {})
    if entry.get('env', {}).get('ASSET_SERVER_URL', '').rstrip('/') != expected_origin.rstrip('/'):
        raise ValueError('Configured server differs from the authorized Site origin')
    lines = source.splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == ENV_HEADER]
    if len(starts) != 1:
        raise ValueError('Expected exactly one existing MCP environment section')
    begin = starts[0] + 1
    end = next((i for i in range(begin, len(lines)) if lines[i].lstrip().startswith('[')), len(lines))
    block = lines[begin:end]
    for key, value in changes.items():
        if not isinstance(value, str) or not value:
            raise ValueError('Empty credential was not saved')
        replacement = key + ' = ' + json.dumps(value, ensure_ascii=False)
        matches = [i for i, line in enumerate(block) if re.match(r'^\s*' + re.escape(key) + r'\s*=', line)]
        if len(matches) > 1:
            raise ValueError('Duplicate credential configuration key')
        if matches:
            block[matches[0]] = replacement
        else:
            block.append(replacement)
    updated = '\n'.join(lines[:begin] + block + lines[end:]) + '\n'
    parsed = tomli.loads(updated)
    expected = tomli.loads(source)
    expected['mcp_servers'][MCP_NAME]['env'].update(changes)
    if parsed != expected:
        raise ValueError('Configuration validation failed; original file was retained')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, prefix='.mcp-config-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(updated)
        if path.read_text(encoding='utf-8-sig') != source:
            raise ValueError('Configuration changed during authorization; original file was retained')
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def authorize(config_path: Path) -> dict:
    entry = tomli.loads(config_path.read_text(encoding='utf-8-sig'))['mcp_servers'][MCP_NAME]
    environment = entry.get('env', {})
    origin = environment['ASSET_SERVER_URL'].rstrip('/')
    headers = {}
    if environment.get('ASSET_SITES_TOKEN'):
        headers['OAI-Sites-Authorization'] = 'Bearer ' + environment['ASSET_SITES_TOKEN']
    with httpx.Client(base_url=origin, headers=headers, timeout=30, follow_redirects=False, trust_env=False) as client:
        probe = client.get('/api/status')
        if probe.status_code != 200 or 'application/json' not in probe.headers.get('content-type', ''):
            raise ValueError('站点平台认证尚未配置或已失效，请先配置 ASSET_SITES_TOKEN。')
        existing = environment.get('ASSET_WRITE_API_TOKEN')
        if existing:
            check = client.get('/api/status', headers={'Authorization': 'Bearer ' + existing})
            if check.status_code == 200 and check.json().get('can_create_products'):
                print('现有新建产品授权有效，无需重复签发。')
                return {'ok': True, 'reused_existing_grant': True}
        print('素材库地址：' + origin)
        print('请在本窗口输入素材库管理员账号。密码不会显示，也不会保存。')
        username = input('管理员账号：').strip()
        password = getpass.getpass('管理员密码：')
        if not username or not password:
            raise ValueError('账号或密码为空，未创建授权。')
        login = client.post('/api/login', json={'username': username, 'password': password})
        del password
        if login.status_code != 200:
            raise ValueError('管理员登录失败，请检查账号密码；未创建授权。')
        try:
            if login.json().get('role') != 'admin':
                raise ValueError('当前账号不是管理员，无权签发新建产品授权。')
            grant_response = client.post('/api/tokens', json={'name': 'Codex 新建产品', 'scope': 'products:create'})
            if grant_response.status_code != 200:
                raise ValueError('授权签发失败，请检查服务器是否已更新。')
            grant = grant_response.json()
            if not re.fullmatch(r'[a-f0-9]{32}', grant.get('id', '')) or grant.get('scope') != 'products:create':
                raise ValueError('服务器未返回有效的新建产品授权。')
            saved = False
            try:
                check = client.get('/api/status', headers={'Authorization': 'Bearer ' + grant['token']})
                if check.status_code != 200 or not check.json().get('can_create_products'):
                    raise ValueError('新令牌没有新建产品权限，未保存到配置。')
                update_mcp_env(config_path, {'ASSET_WRITE_API_TOKEN': grant['token']}, origin)
                saved = True
            finally:
                if not saved:
                    client.delete('/api/tokens/' + grant['id'])
            print('管理员授权完成，已保存专用的新建产品令牌。管理员密码未保存。')
            print('请重载 MCP 客户端，以使用 create_product 工具。')
            return {'ok': True, 'scope': 'products:create', 'grant_id': grant['id'], 'config_path': str(config_path)}
        finally:
            client.post('/api/logout', json={})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path.home() / '.codex' / 'config.toml')
    parser.add_argument('--report', type=Path)
    parser.add_argument('--no-pause', action='store_true')
    args = parser.parse_args()
    try:
        result = authorize(args.config)
    except ValueError as error:
        result = {'ok': False, 'error': str(error)}
        print(str(error))
    except Exception as error:
        result = {'ok': False, 'error': '授权未完成（' + type(error).__name__ + '）。未输出任何凭据。'}
        print(result['error'])
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    if not args.no_pause:
        input('按 Enter 关闭窗口。')
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
