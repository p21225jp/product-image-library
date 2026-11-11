"""End-to-end MCP check against an isolated QA server, never production data."""
import asyncio
import hashlib
import os
import sys
import tempfile
from pathlib import Path

import httpx
from mcp import ClientSession, StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parent.parent
URL = 'http://127.0.0.1:8751'


async def run_check():
    with httpx.Client(base_url=URL, trust_env=False) as client:
        response = client.post('/api/login', json={'username':'qa-admin', 'password':'temporary-browser-password'})
        response.raise_for_status()
        result = client.get('/api/images', params={'product_code':'001234'}).json()
        assert result['total'] > 0, 'Upload the synthetic UI image first.'
        image = result['items'][0]
        expected = client.get(image['download_url']).content
        token = client.post('/api/tokens', json={'name':'isolated MCP test'}).json()
        try:
            with tempfile.TemporaryDirectory(prefix='asset-mcp-export-') as destination:
                environment = dict(os.environ)
                environment.update(ASSET_SERVER_URL=URL, ASSET_API_TOKEN=token['token'], ASSET_EXPORT_DIR=destination)
                params = StdioServerParameters(command=sys.executable, args=[str(ROOT / 'mcp_bridge.py')], env=environment)
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.discover()
                        listed = await session.list_tools()
                        assert {item.name for item in listed.tools} == {'search_products','search_images','get_image_info','export_images','export_images_zip','create_product'}
                        found = await session.call_tool('search_images', {'product_code':'001234','background':'透明','min_width':2000})
                        assert not found.is_error, found
                        missing = await session.call_tool('search_images', {'product_code':'1234'})
                        assert not missing.is_error
                        assert missing.structured_content['total'] == 0
                        output = await session.call_tool('export_images', {'image_ids':[image['id']]})
                        assert not output.is_error, output
                        assert len(output.structured_content['saved']) == 1
                        assert not output.structured_content['failed']
                        assert all(block.type == 'text' for block in output.content)
                        files = list(Path(destination).glob('*.png'))
                        assert len(files) == 1
                        assert hashlib.sha256(files[0].read_bytes()).digest() == hashlib.sha256(expected).digest()
                        print('PASS: MCP discovery, six tools, exact product filtering, transparent/min-width search, local original-byte export, text-only result.')
        finally:
            client.delete('/api/tokens/' + token['id']).raise_for_status()


asyncio.run(run_check())
