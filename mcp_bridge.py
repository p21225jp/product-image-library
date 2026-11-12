# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 jacksonYWJ

"""Local stdio adapter. Image bytes are saved locally, never returned as MCP content."""
from __future__ import annotations

import os
import logging
import re
import uuid
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations


class LibraryToolError(ToolError, ValueError):
    """Expected, sanitized failures that MCP clients can report to the user."""

SERVER_URL = os.environ.get('ASSET_SERVER_URL', 'http://127.0.0.1:8750').rstrip('/')
API_TOKEN = os.environ.get('ASSET_API_TOKEN', '')
WRITE_API_TOKEN = os.environ.get('ASSET_WRITE_API_TOKEN', '')
ASSOCIATE_API_TOKEN = os.environ.get('ASSET_ASSOCIATE_API_TOKEN', '')
SITES_TOKEN = os.environ.get('ASSET_SITES_TOKEN', '')
EXPORT_DIR = Path(os.environ.get('ASSET_EXPORT_DIR', Path(__file__).parent / 'exports')).resolve()
MAX_ZIP_CONTENT_BYTES = 500 * 1024 * 1024
MAX_ZIP_DOWNLOAD_BYTES = MAX_ZIP_CONTENT_BYTES + 2 * 1024 * 1024
parsed_url = urlsplit(SERVER_URL)
if parsed_url.scheme not in ('http', 'https') or not parsed_url.netloc or parsed_url.username or parsed_url.password or parsed_url.query or parsed_url.fragment:
    raise LibraryToolError('ASSET_SERVER_URL must be a plain HTTP(S) server URL without credentials.')

logging.getLogger('httpx').setLevel(logging.WARNING)
server = MCPServer('product-image-library', log_level='WARNING')


def client(write: bool = False, associate: bool = False):
    token = (ASSOCIATE_API_TOKEN or WRITE_API_TOKEN) if associate else WRITE_API_TOKEN if write else API_TOKEN
    if associate and not token:
        raise LibraryToolError('请配置管理员联合写入令牌 ASSET_WRITE_API_TOKEN；旧版独立关联令牌可继续使用 ASSET_ASSOCIATE_API_TOKEN。')
    if write and not token:
        raise LibraryToolError('新建产品需要管理员写入授权，请配置 ASSET_WRITE_API_TOKEN。')
    if not token:
        raise LibraryToolError('请先在素材库「AI 取图」中创建只读令牌，并配置 ASSET_API_TOKEN。')
    headers = {'Authorization': 'Bearer ' + token}
    if SITES_TOKEN:
        headers['OAI-Sites-Authorization'] = 'Bearer ' + SITES_TOKEN
    return httpx.Client(base_url=SERVER_URL, headers=headers,
                        timeout=60, follow_redirects=False, trust_env=False)


def response_json(response):
    if not response.is_success:
        # Do not expose request headers, the token or raw transport exceptions to the model.
        try:
            message = response.json().get('detail', '请求未成功')
        except ValueError:
            message = '服务未返回有效数据'
        raise LibraryToolError(f'图片库返回 {response.status_code}：{message}')
    return response.json()


def identifier(value: str):
    if not re.fullmatch(r'[a-f0-9]{32}', value):
        raise LibraryToolError('请使用 search_images 返回的有效图片 ID。')
    return value


@server.tool(structured_output=True, annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False))
def search_products(query: str, limit: int = 30, offset: int = 0) -> dict[str, Any]:
    """按产品 SKU、名称或别名搜索。SKU 按字符串传入，保留前导零；纯数字只精确匹配 SKU。返回文字元数据，不返回图片像素。"""
    with client() as session:
        return response_json(session.get('/api/products', params={'q': query, 'limit': max(1, min(limit, 100)), 'offset': max(0, offset)}))


@server.tool(structured_output=True, annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False))
def create_product(sku: str, name: str, category: str = '', aliases: list[str] | None = None) -> dict[str, Any]:
    """管理员授权后新建产品。SKU 必须为字符串并保留前导零；name 为产品名称，category 为已有的单个分类（空值表示未分类），aliases 为可选别名列表。重复 SKU 报错，不覆盖现有产品；不创建分类、不修改或删除其他资料。"""
    for label, value, maximum, required in [('SKU', sku, 80, True), ('产品名称', name, 160, True), ('产品分类', category, 80, False)]:
        if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
            raise LibraryToolError(f'{label}必须是有效字符串，长度最多 {maximum} 个字符。')
    if aliases is None:
        aliases = []
    if not isinstance(aliases, list) or len(aliases) > 30 or any(not isinstance(value, str) or len(value) > 100 for value in aliases):
        raise LibraryToolError('别名最多 30 个，每个别名必须为不超过 100 个字符的字符串。')
    try:
        with client(write=True) as session:
            return response_json(session.post('/api/products', json={'code': sku, 'name': name, 'category': category, 'aliases': aliases}))
    except httpx.HTTPError:
        raise LibraryToolError('网络请求未正常完成。请先按 SKU 查询产品是否已创建，再决定是否重试。') from None


@server.tool(structured_output=True, annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False))
def associate_images(product_sku: str, image_ids: list[str]) -> dict[str, Any]:
    """管理员授权后，将 1～100 张已上传图片关联到指定产品 SKU。SKU 保留前导零。重复关联同一产品会跳过；任一图片已属于其他产品、在回收站或不存在时整批拒绝。不新建产品、不改绑、不修改图片类型、角度、标签或原文件。"""
    if not isinstance(product_sku, str) or not product_sku.strip() or len(product_sku) > 80:
        raise LibraryToolError('产品 SKU 必须为不超过 80 个字符的非空字符串。')
    if not isinstance(image_ids, list) or not 1 <= len(image_ids) <= 100 or any(not isinstance(x, str) for x in image_ids):
        raise LibraryToolError('每次请选择 1～100 张有效图片。')
    ids = [identifier(x) for x in dict.fromkeys(image_ids)]
    import unicodedata
    sku = unicodedata.normalize('NFKC', product_sku).strip()
    try:
        with client(associate=True) as session:
            result = response_json(session.get('/api/products', params={'q': sku, 'limit': 100, 'offset': 0}))
            products = [p for p in result.get('items', []) if p['code'].casefold() == sku.casefold()]
            if len(products) != 1:
                raise LibraryToolError('未找到唯一的对应产品 SKU，请先核对产品目录。')
            product = products[0]
            product_id = identifier(product['id'])
            result = response_json(session.post('/api/products/' + product_id + '/images/associate', json={'image_ids': ids}))
            return {**result, 'product_sku': product['code'], 'product_name': product['name'], 'image_ids': ids}
    except httpx.HTTPError:
        raise LibraryToolError('网络请求未正常完成。请先查询图片当前归属；同一产品的关联可安全重试。') from None


@server.tool(structured_output=True, annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False))
def search_images(query: str = '', product_code: str = '', kind: str = '', angle: str = '',
                  background: str = '', min_width: int = 0, limit: int = 30, offset: int = 0) -> dict[str, Any]:
    """查找产品图片。明确产品 SKU 时使用 product_code，保留前导零。kind 为产品图/场景图/其他；angle 为正面/背面/侧面/俯视/仰视/其他；background 为透明/其他。返回图片 ID 与文字属性，匹配为空时请明确报告缺图，不自动替换产品。"""
    with client() as session:
        return response_json(session.get('/api/images', params={'q': query, 'product_code': product_code,
            'kind': kind, 'angle': angle, 'background': background, 'min_width': max(0, min_width),
            'limit': max(1, min(limit, 100)), 'offset': max(0, offset)}))


@server.tool(structured_output=True, annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False))
def get_image_info(image_id: str) -> dict[str, Any]:
    """获取一张图片的产品归属、格式、尺寸等文字资料，不读取或返回图片像素。"""
    with client() as session:
        return response_json(session.get('/api/images/' + identifier(image_id)))


@server.tool(structured_output=True, annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False))
def export_images(image_ids: list[str]) -> dict[str, Any]:
    """逐张下载原图到本机，每次最多 30 张。需要打包下载或仅保存压缩包时，请使用 export_images_zip。不接受任意目标路径、不覆盖旧文件，只返回文件名和保存状态，不把图片像素发送给模型。"""
    if not image_ids or len(image_ids) > 30:
        raise LibraryToolError('每次请选择 1～30 张图片。')
    ids = [identifier(value) for value in dict.fromkeys(image_ids)]
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    saved, failed = [], []
    with client() as session:
        for item_id in ids:
            temporary = None
            target = None
            created_target = False
            completed = False
            try:
                item = response_json(session.get('/api/images/' + item_id))
                extension = item['extension']
                if extension not in ('jpg', 'png', 'webp'):
                    raise LibraryToolError('不支持的图片格式。')
                base = str(item.get('product_code') or 'unassigned')
                base = re.sub(r'[^\w.-]', '_', base)[:60].strip('. ') or 'asset'
                # Prefix guarantees no reserved Windows device name is used.
                filename = f"asset_{base}_{item_id[:8]}_{uuid.uuid4().hex[:8]}.{extension}"
                target = EXPORT_DIR / filename
                temporary = EXPORT_DIR / (uuid.uuid4().hex + '.part')
                received = 0
                with session.stream('GET', '/api/images/' + item_id + '/file') as response:
                    if response.status_code != 200:
                        raise LibraryToolError(f'下载失败，HTTP {response.status_code}')
                    with temporary.open('xb') as output:
                        for chunk in response.iter_bytes():
                            received += len(chunk)
                            if received > 25 * 1024 * 1024:
                                raise LibraryToolError('文件超过允许大小。')
                            output.write(chunk)
                if received != item['size']:
                    raise LibraryToolError('下载大小与原文件不一致，请重试。')
                # Exclusive create avoids replacing existing files even on POSIX.
                with target.open('xb') as output, temporary.open('rb') as source:
                    created_target = True
                    while chunk := source.read(1024 * 1024):
                        output.write(chunk)
                completed = True
                saved.append({'image_id': item_id, 'filename': filename, 'bytes': received, 'status': 'saved'})
            except (httpx.HTTPError, OSError, ValueError) as error:
                message = str(error) if isinstance(error, ValueError) else '网络或本地文件操作失败，请检查服务与输出目录。'
                failed.append({'image_id': item_id, 'error': message})
            finally:
                if temporary:
                    temporary.unlink(missing_ok=True)
                if target and created_target and not completed:
                    target.unlink(missing_ok=True)
    return {'saved': saved, 'failed': failed, 'location': 'ASSET_EXPORT_DIR 配置的本机目录', 'image_content_sent_to_model': False}


@server.tool(structured_output=True, annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False))
def export_images_zip(image_ids: list[str]) -> dict[str, Any]:
    """让服务器打包选中图片，只下载一个 ZIP 到 ASSET_EXPORT_DIR，不在本机保存或解压单张原图。每次 1～100 张、原图合计最多 500 MiB；保留原图格式和尺寸。返回 ZIP 文件名、大小和图片数量，不返回图片像素。批量打包优先使用本工具。"""
    if not image_ids or len(image_ids) > 100:
        raise LibraryToolError('每次打包请选择 1～100 张图片。')
    ids = [identifier(value) for value in dict.fromkeys(image_ids)]
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f'product_images_{len(ids)}_{uuid.uuid4().hex[:12]}.zip'
    target = EXPORT_DIR / filename
    temporary = EXPORT_DIR / (uuid.uuid4().hex + '.zip.part')
    created_target = completed = False
    received = 0
    try:
        with client() as session:
            with session.stream('POST', '/api/export', json={'image_ids': ids},
                                timeout=httpx.Timeout(180, connect=30)) as response:
                if response.status_code != 200:
                    raise LibraryToolError(f'打包下载失败，HTTP {response.status_code}。请检查令牌、图片是否存在及单批 500 MiB 限制。')
                with temporary.open('xb') as output:
                    for chunk in response.iter_bytes():
                        received += len(chunk)
                        if received > MAX_ZIP_DOWNLOAD_BYTES:
                            raise LibraryToolError('压缩包超过允许的下载大小。')
                        output.write(chunk)
                length = response.headers.get('content-length', '')
                if length.isdecimal() and received != int(length):
                    raise LibraryToolError('压缩包下载不完整，请重试。')
        with zipfile.ZipFile(temporary) as archive:
            entries = archive.infolist()
            if len(entries) != len(ids) or sum(item.file_size for item in entries) > MAX_ZIP_CONTENT_BYTES:
                raise LibraryToolError('压缩包图片数量或内容大小不符合预期。')
            for item in entries:
                if (item.is_dir() or '/' in item.filename or '\\' in item.filename or
                        Path(item.filename).suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp')):
                    raise LibraryToolError('压缩包含有非预期的文件或路径。')
            if archive.testzip() is not None:
                raise LibraryToolError('压缩包完整性校验失败。')
        # Exclusive creation also protects existing files on POSIX. No image is extracted.
        with target.open('xb') as output, temporary.open('rb') as source:
            created_target = True
            while chunk := source.read(1024 * 1024):
                output.write(chunk)
        completed = True
        return {'filename': filename, 'bytes': received, 'image_count': len(ids), 'status': 'saved',
                'format': 'zip', 'location': 'ASSET_EXPORT_DIR 配置的本机目录',
                'image_content_sent_to_model': False}
    except (httpx.HTTPError, OSError, zipfile.BadZipFile, RuntimeError, ValueError) as error:
        message = str(error) if isinstance(error, ValueError) else '压缩包下载或校验失败，请检查网络、磁盘空间后重试。'
        raise LibraryToolError(message) from None
    finally:
        temporary.unlink(missing_ok=True)
        if created_target and not completed:
            target.unlink(missing_ok=True)


if __name__ == '__main__':
    server.run(transport='stdio')
