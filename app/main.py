from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import socket
import sqlite3
import threading
import time
import unicodedata
import uuid
import warnings
import zipfile
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from storage import storage_lock
from app.migrations import remove_retired_agent_state

PROJECT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get('ASSET_DATA_DIR', PROJECT / 'data')).resolve()
ORIGINALS = DATA / 'originals'
THUMBS = DATA / 'thumbnails'
TEMP = DATA / 'temp'
MAX_BYTES = 25 * 1024 * 1024
MAX_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
COOKIE = 'asset_session'
KINDS = ['产品图', '场景图', '其他']
ANGLES = ['正面', '背面', '侧面', '俯视', '仰视', '其他']
BACKGROUNDS = ['透明', '其他']
# Values from the previous taxonomy; startup moves these rows to the current choices.
LEGACY_KINDS = {'素材图': '产品图', '主图': '产品图', '细节图': '产品图', '包装图': '产品图'}
LEGACY_BACKGROUNDS = {'白底': '其他'}
setup_lock = threading.Lock()
upload_lock = threading.Lock()
login_attempts: dict[str, list[float]] = {}
login_lock = threading.Lock()


@contextmanager
def db():
    connection = sqlite3.connect(DATA / 'library.sqlite3', timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys=ON')
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize():
    for directory in (DATA, ORIGINALS, THUMBS, TEMP):
        directory.mkdir(parents=True, exist_ok=True)
    with db() as con:
        con.execute('PRAGMA journal_mode=WAL')
        con.executescript('''
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY, code TEXT NOT NULL COLLATE NOCASE UNIQUE,
                name TEXT NOT NULL, brand TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT '',
                aliases TEXT NOT NULL DEFAULT '[]', created_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS categories (name TEXT PRIMARY KEY COLLATE NOCASE);
            INSERT OR IGNORE INTO categories(name) SELECT DISTINCT category FROM products WHERE category<>'';
            CREATE TABLE IF NOT EXISTS images (
                id TEXT PRIMARY KEY, product_id TEXT REFERENCES products(id),
                original_name TEXT NOT NULL, extension TEXT NOT NULL, mime_type TEXT NOT NULL,
                width INTEGER NOT NULL, height INTEGER NOT NULL, size INTEGER NOT NULL,
                sha256 TEXT NOT NULL, kind TEXT NOT NULL, angle TEXT NOT NULL,
                background TEXT NOT NULL, has_alpha INTEGER NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]', created_at INTEGER NOT NULL, deleted_at INTEGER);
            CREATE INDEX IF NOT EXISTS image_product ON images(product_id);
            CREATE INDEX IF NOT EXISTS image_hash ON images(sha256);
            CREATE INDEX IF NOT EXISTS image_created ON images(created_at DESC);
            CREATE TABLE IF NOT EXISTS sessions (hash TEXT PRIMARY KEY, expires INTEGER NOT NULL,
                role TEXT NOT NULL DEFAULT 'admin');
            CREATE TABLE IF NOT EXISTS tokens (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, hash TEXT NOT NULL UNIQUE,
                prefix TEXT NOT NULL, created_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL,
                actor TEXT NOT NULL, detail TEXT NOT NULL, created_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS pending_deletes (
                id TEXT PRIMARY KEY, extension TEXT NOT NULL, created_at INTEGER NOT NULL);
            -- staff: internal colleagues, may create their own read-only tokens.
            -- external: customers and partners, password login only, never tokens.
            CREATE TABLE IF NOT EXISTS accounts (
                id TEXT PRIMARY KEY, username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                salt TEXT NOT NULL, password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('staff','external')),
                created_at INTEGER NOT NULL, disabled_at INTEGER);
        ''')
    migrate_schema()
    migrate_image_choices()


def migrate_schema():
    # CREATE TABLE IF NOT EXISTS never alters an existing table, so older databases are upgraded here.
    with storage_lock(DATA), db() as con:
        columns = {row['name'] for row in con.execute('PRAGMA table_info(sessions)')}
        if 'role' not in columns:
            con.execute("ALTER TABLE sessions ADD COLUMN role TEXT NOT NULL DEFAULT 'admin'")
        # Sessions created before roles existed belong to the administrator.
        con.execute("UPDATE sessions SET role='admin' WHERE role IS NULL OR role=''")
        session_columns = {row['name'] for row in con.execute('PRAGMA table_info(sessions)')}
        if 'account_id' not in session_columns:
            # Sessions must identify the person, otherwise two staff accounts share one identity.
            con.execute('ALTER TABLE sessions ADD COLUMN account_id TEXT')
        token_columns = {row['name'] for row in con.execute('PRAGMA table_info(tokens)')}
        if 'account_id' not in token_columns:
            # Tokens created before accounts existed belong to nobody, so only the administrator can see them.
            con.execute('ALTER TABLE tokens ADD COLUMN account_id TEXT')
        if 'last_used_at' not in token_columns:
            con.execute('ALTER TABLE tokens ADD COLUMN last_used_at INTEGER')
        migrate_shared_visitor(con)
        remove_retired_agent_state(con, DATA)


def migrate_shared_visitor(con):
    """Turn the single shared visitor password into one external account row."""
    stored = {row['key']: row['value'] for row in con.execute(
        "SELECT key,value FROM settings WHERE key IN ('team_username','team_salt','team_password_hash')")}
    if not stored.get('team_password_hash'):
        return
    username = stored.get('team_username') or 'visitor'
    exists = con.execute('SELECT 1 FROM accounts WHERE username=?', (username,)).fetchone()
    if not exists:
        con.execute('INSERT INTO accounts(id,username,salt,password_hash,role,created_at) VALUES(?,?,?,?,?,?)',
                    (uuid.uuid4().hex, username, stored.get('team_salt', ''), stored['team_password_hash'], 'external',
                     int(time.time())))
    con.execute("DELETE FROM settings WHERE key IN ('team_username','team_salt','team_password_hash')")


def migrate_image_choices():
    with db() as con:
        for old, new in LEGACY_KINDS.items():
            con.execute('UPDATE images SET kind=? WHERE kind=?', (new, old))
        for old, new in LEGACY_BACKGROUNDS.items():
            con.execute('UPDATE images SET background=? WHERE background=?', (new, old))


def leave_no_trace(state: dict) -> dict:
    # Upload and ZIP files are already removed on success and failure; this only covers a crash or forced stop.
    removed = 0
    for leftover in TEMP.iterdir():
        if leftover.is_file():
            try:
                leftover.unlink()
                removed += 1
            except OSError:
                pass
    state['temp_removed'] = removed
    return state


@asynccontextmanager
async def lifespan(application):
    state: dict = {}
    await asyncio.to_thread(leave_no_trace, state)
    if state['temp_removed']:
        print(f"已清理 {state['temp_removed']} 个残留临时文件。")
    await asyncio.to_thread(clean_pending_files)
    async def retry_cleanup():
        while True:
            await asyncio.sleep(60)
            try:
                await asyncio.to_thread(clean_pending_files)
            except (OSError, sqlite3.Error):
                print('待删除文件暂未清理完成，将在下一轮重试。')
    cleanup_task = asyncio.create_task(retry_cleanup())
    try:
        yield
    finally:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass


initialize()
app = FastAPI(title='素材柜 · 内网产品图片库', version='0.1.0', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


@app.exception_handler(TimeoutError)
async def storage_busy(request: Request, error: TimeoutError):
    return JSONResponse({'detail': '素材文件正在备份或清理，请稍后重试。'}, 503)


def fail(status: int, message: str):
    raise HTTPException(status, message)


def normalized(value: str) -> str:
    return unicodedata.normalize('NFKC', value).strip()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def settings() -> dict:
    with db() as con:
        return dict(con.execute('SELECT key,value FROM settings').fetchall())


def audit(action: str, actor: str, detail: str = ''):
    with db() as con:
        con.execute('INSERT INTO audit(action,actor,detail,created_at) VALUES(?,?,?,?)',
                    (action, actor, detail[:500], int(time.time())))


def session_row(con, request: Request):
    """Session cookie -> (role, account_id). Empty account_id means the administrator."""
    cookie = request.cookies.get(COOKIE, '')
    if not cookie:
        return None
    return con.execute('SELECT role,account_id FROM sessions WHERE hash=? AND expires>?',
                       (digest(cookie), int(time.time()))).fetchone()


def session_role(con, request: Request) -> str:
    row = session_row(con, request)
    return row['role'] if row else ''


def account_identity(con, account_id: str | None):
    """A disabled or deleted account must lose access even if its session row survives."""
    if not account_id:
        return None
    return con.execute('SELECT * FROM accounts WHERE id=? AND disabled_at IS NULL', (account_id,)).fetchone()


def authenticate(request: Request) -> str:
    """Actor string: 'admin', 'staff:<account>', 'external:<account>' or 'token:<id>'.
    The suffix identifies the exact person behind the request."""
    authorization = request.headers.get('authorization', '')
    with db() as con:
        if authorization.startswith('Bearer '):
            record = con.execute('SELECT id,account_id FROM tokens WHERE hash=?', (digest(authorization[7:]),)).fetchone()
            if record:
                owner = account_identity(con, record['account_id']) if record['account_id'] else None
                if record['account_id'] and not owner:
                    fail(401, '签发此令牌的账号已停用或删除，请重新获取令牌。')
                con.execute('UPDATE tokens SET last_used_at=? WHERE id=?', (int(time.time()), record['id']))
                # A token issued by an internal colleague may upload; anonymous tokens only read.
                return 'token:' + record['id'] + (':upload' if owner and owner['role'] == 'staff' else '')
        else:
            row = session_row(con, request)
            if row:
                if row['role'] == 'admin' and not row['account_id']:
                    return 'admin'
                account = account_identity(con, row['account_id'])
                if account:
                    return account['role'] + ':' + account['id']
    fail(401, '请先登录，或提供有效的只读访问令牌。')


def actor_role(actor: str) -> str:
    if actor == 'admin':
        return 'admin'
    return actor.split(':', 1)[0]


def actor_account(actor: str) -> str | None:
    """The account that owns this actor, or None for the administrator and anonymous tokens."""
    if actor.startswith('token:'):
        return actor.split(':', 2)[1]
    parts = actor.split(':', 1)
    return parts[1] if len(parts) > 1 else None


def is_admin(actor: str) -> bool:
    return actor_role(actor) == 'admin'


def is_staff(actor: str) -> bool:
    """Administrators and internal colleagues may create tokens."""
    return actor_role(actor) in ('admin', 'staff')


def is_uploader(actor: str) -> bool:
    """Administrator/staff sessions and staff-issued tokens may write to the library."""
    return actor_role(actor) in ('admin', 'staff') or actor.endswith(':upload')


def admin(actor: str = Depends(authenticate)) -> str:
    if not is_admin(actor):
        fail(403, '此操作需要管理员登录，只读令牌或访客账号不可修改素材。')
    return actor


def staff(actor: str = Depends(authenticate)) -> str:
    if not is_staff(actor):
        fail(403, '此操作需要内部账号登录，外部账号不能执行。')
    return actor



def uploader(actor: str = Depends(authenticate)) -> str:
    if not is_uploader(actor):
        fail(403, '此操作需要内部账号或内部令牌，外部账号只能浏览和下载。')
    return actor


@app.middleware('http')
async def protection(request: Request, call_next):
    # Prevent DNS rebinding: accept only local IPs or explicitly configured host names.
    host = request.url.hostname or ''
    permitted = {'localhost', socket.gethostname().lower(), *os.environ.get('ASSET_ALLOWED_HOSTS', '').lower().split(',')}
    try:
        address = ipaddress.ip_address(host)
        permitted_host = address.is_private or address.is_loopback
    except ValueError:
        permitted_host = host.lower() in permitted
    if not permitted_host:
        return JSONResponse({'detail': '此服务只接受内网地址；自定义域名需加入 ASSET_ALLOWED_HOSTS。'}, 400)
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('origin')
        expected_origin = os.environ.get('ASSET_PUBLIC_ORIGIN', str(request.base_url)).rstrip('/')
        if origin and origin != expected_origin:
            return JSONResponse({'detail': '拒绝跨站请求。'}, 403)
        if request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail': '拒绝跨站请求。'}, 403)
    if request.url.path == '/api/images/upload' and request.method == 'POST':
        try:
            actor = authenticate(request)
            if not is_uploader(actor):
                return JSONResponse({'detail': '外部账号和只读令牌不可上传图片。'}, 403)
        except HTTPException as error:
            return JSONResponse({'detail': error.detail}, error.status_code)
        # Browser and desktop upload clients supply Content-Length. Requiring it
        # prevents an unbounded chunked request from filling temporary storage.
        length = request.headers.get('content-length', '')
        if not length.isdecimal():
            return JSONResponse({'detail': '上传请求必须提供 Content-Length。'}, 411)
        if int(length) > MAX_BYTES + 1024 * 1024:
            return JSONResponse({'detail': '上传内容超过允许大小。'}, 413)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=1, max_length=200)


def local_request(request: Request) -> bool:
    # Initialization must never be offered through a reverse proxy, even when
    # the forwarded address is missing or claims to be localhost.
    if os.environ.get('ASSET_DISABLE_SETUP') == '1' or any(
        header in request.headers for header in ('forwarded', 'x-forwarded-for', 'x-forwarded-proto')
    ):
        return False
    try:
        return ipaddress.ip_address(request.client.host).is_loopback
    except (ValueError, AttributeError):
        return False


@app.get('/api/status')
def status(request: Request):
    configured = 'password_hash' in settings()
    with db() as con:
        role = session_role(con, request)
    return {'configured': configured, 'logged_in': role in ('admin', 'staff', 'external'), 'role': role or None,
            'can_setup': local_request(request), 'can_issue_tokens': role in ('admin', 'staff'),
            'max_upload_mb': 25, 'kinds': KINDS, 'angles': ANGLES, 'backgrounds': BACKGROUNDS}


def login_response(request: Request, role: str = 'admin', account_id: str | None = None):
    secret = secrets.token_urlsafe(40)
    with db() as con:
        con.execute('DELETE FROM sessions WHERE expires<=?', (int(time.time()),))
        con.execute('INSERT INTO sessions(hash,expires,role,account_id) VALUES(?,?,?,?)',
                    (digest(secret), int(time.time()) + 28800, role, account_id))
    response = JSONResponse({'ok': True, 'role': role})
    secure_cookie = request.url.scheme == 'https' or os.environ.get('ASSET_COOKIE_SECURE') == '1' or os.environ.get('ASSET_PUBLIC_ORIGIN', '').startswith('https://')
    response.set_cookie(COOKIE, secret, httponly=True, samesite='strict', secure=secure_cookie, max_age=28800)
    return response


@app.post('/api/setup')
def setup(body: Credentials, request: Request):
    if not local_request(request):
        fail(403, '首次初始化请在服务器本机打开 localhost 地址完成。')
    if len(body.password) < 10:
        fail(400, '密码至少需要 10 个字符。')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{3,40}', body.username):
        fail(400, '账号使用 3～40 位字母、数字、下划线、点或短横线。')
    with setup_lock:
        if 'password_hash' in settings():
            fail(409, '已经完成初始化，请登录。')
        salt = secrets.token_hex(16)
        hashed = hashlib.scrypt(body.password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
        with db() as con:
            con.executemany('INSERT INTO settings(key,value) VALUES(?,?)',
                            [('username', body.username), ('salt', salt), ('password_hash', hashed)])
    audit('初始化管理员', 'admin')
    return login_response(request)


def account_matches(config: dict, prefix: str, body: Credentials) -> bool:
    salt = config.get(prefix + 'salt')
    expected = config.get(prefix + 'password_hash')
    if not salt or not expected or body.username != config.get(prefix + 'username'):
        return False
    candidate = hashlib.scrypt(body.password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return hmac.compare_digest(candidate, expected)


@app.post('/api/login')
def login(body: Credentials, request: Request):
    key = request.client.host
    with login_lock:
        attempts = [stamp for stamp in login_attempts.get(key, []) if stamp > time.time() - 900]
        if len(attempts) >= 8:
            fail(429, '尝试次数过多，请 15 分钟后再试。')
        attempts.append(time.time())
        login_attempts[key] = attempts
    config = settings()
    if not config:
        fail(400, '请先在服务器本机初始化管理员。')
    matched = account_login(body)
    if matched is None:
        fail(401, '账号或密码不正确。')
    role, account_id = matched
    with login_lock:
        login_attempts.pop(key, None)
    audit('登录', {'admin': 'admin', 'staff': '内部账号', 'external': '外部账号'}[role])
    return login_response(request, role, account_id)


def account_login(body: 'Credentials') -> tuple[str, str | None] | None:
    """Match the administrator first, then a named account; disabled accounts cannot log in."""
    config = settings()
    if account_matches(config, '', body):
        return 'admin', None
    with db() as con:
        row = con.execute('SELECT id,salt,password_hash,role,disabled_at FROM accounts WHERE username=?',
                          (body.username,)).fetchone()
    if not row or row['disabled_at']:
        return None
    hashed = hashlib.scrypt(body.password.encode(), salt=bytes.fromhex(row['salt']), n=16384, r=8, p=1).hex()
    return (row['role'], row['id']) if hmac.compare_digest(hashed, row['password_hash']) else None


class CurrentPasswordInput(BaseModel):
    current_password: str = Field(min_length=1, max_length=200, repr=False)


def credential_problem(username: str, password: str):
    if not re.fullmatch(r'[A-Za-z0-9_.-]{3,40}', username):
        fail(400, '账号使用 3～40 位字母、数字、下划线、点或短横线。')
    if len(password) < 10:
        fail(400, '密码至少需要 10 个字符。')


def check_current_password(password: str):
    config = settings()
    if 'salt' not in config:
        fail(400, '请先初始化管理员账号。')
    hashed = hashlib.scrypt(password.encode(), salt=bytes.fromhex(config['salt']), n=16384, r=8, p=1).hex()
    if not hmac.compare_digest(hashed, config['password_hash']):
        fail(403, '管理员密码不正确。')


def account_json(row):
    return {'id': row['id'], 'username': row['username'], 'role': row['role'],
            'created_at': row['created_at'], 'disabled': bool(row['disabled_at'])}


def password_digest(password: str):
    salt = secrets.token_hex(16)
    return salt, hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()


def delete_account_sessions(con, account_id: str):
    # Drop exactly this person's sessions so nobody else is signed out by the change.
    con.execute('DELETE FROM sessions WHERE account_id=?', (account_id,))


@app.get('/api/accounts')
def list_accounts(actor: str = Depends(admin)):
    with db() as con:
        rows = con.execute('SELECT * FROM accounts ORDER BY created_at DESC').fetchall()
    return {'items': [account_json(row) for row in rows]}


class AccountInput(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=10, max_length=200, repr=False)
    role: str = Field(default='external', pattern='^(staff|external)$')


class AccountUpdate(BaseModel):
    password: str = Field(min_length=10, max_length=200, repr=False)


@app.post('/api/accounts')
def create_account(body: AccountInput, actor: str = Depends(admin)):
    credential_problem(body.username, body.password)
    config = settings()
    if body.username.lower() == (config.get('username') or '').lower():
        fail(409, '账号名与管理员相同，请换一个。')
    salt, hashed = password_digest(body.password)
    identifier = uuid.uuid4().hex
    try:
        with db() as con:
            con.execute('INSERT INTO accounts(id,username,salt,password_hash,role,created_at) VALUES(?,?,?,?,?,?)',
                        (identifier, body.username, salt, hashed, body.role, int(time.time())))
            row = con.execute('SELECT * FROM accounts WHERE id=?', (identifier,)).fetchone()
    except sqlite3.IntegrityError:
        fail(409, '此账号名已存在。')
    audit('创建账号', actor, f"{body.username}（{'内部账号' if body.role == 'staff' else '外部账号'}）")
    return account_json(row)


@app.put('/api/accounts/{identifier}')
def update_account(identifier: str, body: AccountUpdate, actor: str = Depends(admin)):
    credential_problem('placeholder', body.password)
    salt, hashed = password_digest(body.password)
    with db() as con:
        row = con.execute('SELECT username FROM accounts WHERE id=?', (identifier,)).fetchone()
        if not row:
            fail(404, '账号不存在。')
        con.execute('UPDATE accounts SET salt=?,password_hash=? WHERE id=?', (salt, hashed, identifier))
        # A rotated password must invalidate every session that used the old one.
        delete_account_sessions(con, identifier)
    audit('重置账号密码', actor, row['username'])
    return {'ok': True}


@app.delete('/api/accounts/{identifier}')
def delete_account(identifier: str, actor: str = Depends(admin)):
    with db() as con:
        row = con.execute('SELECT username FROM accounts WHERE id=?', (identifier,)).fetchone()
        if not row:
            fail(404, '账号不存在。')
        # Tokens issued by this account stop working, because nobody should inherit them.
        con.execute('DELETE FROM tokens WHERE account_id=?', (identifier,))
        delete_account_sessions(con, identifier)
        con.execute('DELETE FROM accounts WHERE id=?', (identifier,))
    audit('删除账号', actor, row['username'])
    return {'ok': True}


def local_addresses() -> list[str]:
    """Private IPv4 addresses other machines can use; the default route decides the usual one."""
    found = set()
    try:
        found.update(info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(('10.255.255.255', 1))
            found.add(probe.getsockname()[0])
    except OSError:
        pass
    addresses = []
    for value in found:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if address.is_private and not address.is_loopback and not address.is_link_local:
            addresses.append((address.version, value))
    return [value for _, value in sorted(addresses)]


@app.get('/api/network')
def network_info(actor: str = Depends(admin)):
    """Prefer the configured HTTPS entry point; preserve LAN discovery for local use."""
    return {'addresses': local_addresses(),
            'public_origin': os.environ.get('ASSET_PUBLIC_ORIGIN', '').rstrip('/')}


@app.post('/api/logout')
def logout(request: Request, actor: str = Depends(authenticate)):
    if actor_role(actor) not in ('admin', 'staff', 'external') or actor.startswith('token:'):
        fail(403, '请使用浏览器登录账号退出。')
    with db() as con:
        con.execute('DELETE FROM sessions WHERE hash=?', (digest(request.cookies.get(COOKIE, '')),))
    response = JSONResponse({'ok': True})
    response.delete_cookie(COOKIE)
    return response


class ProductInput(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    category: str = Field(default='', max_length=80)
    aliases: list[str] = Field(default_factory=list, max_length=30)


def unique_strings(values: list[str], limit: int, length: int) -> list[str]:
    # NFKC folds full-width commas for tags; keep the first spelling of a repeated value.
    return list(dict.fromkeys(item[:length] for item in (normalized(value) for value in values) if item[:length]))


def product_data(body: ProductInput, con):
    product_code, product_name = normalized(body.code), normalized(body.name)
    if not product_code or not product_name:
        fail(400, '产品 SKU 和产品名称不能为空。')
    aliases = unique_strings(body.aliases, limit=30, length=100)
    category = normalized(body.category)
    if category:
        choice = con.execute('SELECT name FROM categories WHERE name=?', (category,)).fetchone()
        if not choice:
            fail(400, '请选择已有产品分类，或先创建分类选项。')
        category = choice['name']
    return product_code, product_name, category, json.dumps(aliases, ensure_ascii=False)


class CategoryInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)


@app.get('/api/categories')
def list_categories(actor: str = Depends(authenticate)):
    with db() as con:
        return {'items': [row['name'] for row in con.execute('SELECT name FROM categories ORDER BY name')]}


@app.post('/api/categories')
def create_category(body: CategoryInput, actor: str = Depends(staff)):
    name = normalized(body.name)
    if not name or len(name) > 80:
        fail(400, '分类名称需为 1 至 80 个字符。')
    with db() as con:
        added = con.execute('INSERT OR IGNORE INTO categories(name) VALUES(?)', (name,)).rowcount > 0
        name = con.execute('SELECT name FROM categories WHERE name=?', (name,)).fetchone()['name']
    if added:
        audit('新建分类', actor, name)
    return {'name': name, 'created': added}


@app.get('/api/categories/manage')
def manage_categories(actor: str = Depends(admin)):
    with db() as con:
        rows = con.execute('''SELECT c.name,
            (SELECT count(*) FROM products p WHERE p.category=c.name COLLATE NOCASE) product_count,
            (SELECT count(*) FROM images i JOIN products p ON p.id=i.product_id
             WHERE p.category=c.name COLLATE NOCASE AND i.deleted_at IS NULL) image_count,
            (SELECT count(*) FROM images i JOIN products p ON p.id=i.product_id
             WHERE p.category=c.name COLLATE NOCASE AND i.deleted_at IS NOT NULL) trashed_image_count
            FROM categories c ORDER BY c.name''').fetchall()
    return {'items': [dict(row) for row in rows]}


def category_deletion_snapshot(con, name):
    # Category names are identifiers here. Prefer the stored spelling before
    # normalizing user input, so a legacy full-width name cannot target a different category.
    category = con.execute('SELECT name FROM categories WHERE name=?', (name,)).fetchone()
    if not category:
        category = con.execute('SELECT name FROM categories WHERE name=?', (normalized(name),)).fetchone()
    if not category:
        fail(404, '分类不存在或已被删除，请刷新分类列表。')
    category = category['name']
    products = con.execute('SELECT id FROM products WHERE category=? COLLATE NOCASE ORDER BY id', (category,)).fetchall()
    images = con.execute('''SELECT i.id,i.product_id,i.deleted_at FROM images i JOIN products p ON p.id=i.product_id
        WHERE p.category=? COLLATE NOCASE ORDER BY i.id''', (category,)).fetchall()
    version = json.dumps([category, [row['id'] for row in products], [list(row) for row in images]], ensure_ascii=False)
    active = sum(row['deleted_at'] is None for row in images)
    return {'name': category, 'product_count': len(products), 'image_count': active,
            'trashed_image_count': len(images) - active, 'total_unlinked': len(images), 'preview_token': digest(version)}


@app.get('/api/categories/deletion-preview')
def preview_category_deletion(name: str = Query(min_length=1, max_length=80), actor: str = Depends(admin)):
    with db() as con:
        con.execute('BEGIN')
        return category_deletion_snapshot(con, name)


class DeleteCategoryInput(CategoryInput):
    preview_token: str = Field(pattern=r'^[a-f0-9]{64}$')


@app.delete('/api/categories')
def delete_category(body: DeleteCategoryInput, actor: str = Depends(admin)):
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        impact = category_deletion_snapshot(con, body.name)
        if not hmac.compare_digest(impact['preview_token'], body.preview_token):
            fail(409, '分类下的产品或图片已发生变化，请核对最新影响范围后再次确认删除。')
        # Unbind first, while the products still carry this category. Include trash
        # so restoring an image later cannot bring back the removed association.
        con.execute('''UPDATE images SET product_id=NULL WHERE product_id IN
            (SELECT id FROM products WHERE category=? COLLATE NOCASE)''', (impact['name'],))
        con.execute("UPDATE products SET category='' WHERE category=? COLLATE NOCASE", (impact['name'],))
        con.execute('DELETE FROM categories WHERE name=?', (impact['name'],))
        con.execute('INSERT INTO audit(action,actor,detail,created_at) VALUES(?,?,?,?)',
                    ('删除分类并解绑图片', actor,
                     f"{impact['name']}；{impact['product_count']} 个产品改为未分类；解绑 {impact['image_count']} 张有效图片、{impact['trashed_image_count']} 张回收站图片。",
                     int(time.time())))
    return {'deleted': True, **{key: value for key, value in impact.items() if key != 'preview_token'}}


def product_json(row):
    result = dict(row)
    result['aliases'] = json.loads(result['aliases'])
    return result


def like(query: str):
    return '%' + query.replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%'


@app.get('/api/products')
def list_products(q: str = Query('', max_length=200), category: str = Query('', max_length=80),
                  limit: int = Query(100, ge=1, le=200),
                  offset: int = Query(0, ge=0), actor: str = Depends(authenticate)):
    q = normalized(q)
    category = normalized(category)
    params = []
    conditions = []
    if q:
        if q.isdecimal():
            conditions.append('p.code=? COLLATE NOCASE')
            params.append(q)
        else:
            conditions.append("(p.code LIKE ? ESCAPE '!' OR p.name LIKE ? ESCAPE '!' OR EXISTS (SELECT 1 FROM json_each(p.aliases) WHERE value LIKE ? ESCAPE '!'))")
            params.extend([like(q)] * 3)
    # The special value '未分类' matches products whose category is empty.
    if category == '未分类':
        conditions.append("p.category=''")
    elif category:
        conditions.append('p.category=? COLLATE NOCASE')
        params.append(category)
    clause = 'WHERE ' + ' AND '.join(conditions) if conditions else ''
    with db() as con:
        count = con.execute(f'SELECT count(*) FROM products p {clause}', params).fetchone()[0]
        rows = con.execute(f'''SELECT p.*, (SELECT count(*) FROM images i WHERE i.product_id=p.id AND i.deleted_at IS NULL) image_count
            FROM products p {clause} ORDER BY (p.code=? COLLATE NOCASE) DESC,p.created_at DESC,p.id LIMIT ? OFFSET ?''',
            params + [q, limit, offset]).fetchall()
    return {'items': [product_json(row) for row in rows], 'total': count}


@app.post('/api/products')
def create_product(body: ProductInput, actor: str = Depends(staff)):
    identifier = uuid.uuid4().hex
    try:
        with db() as con:
            con.execute('BEGIN IMMEDIATE')
            values = product_data(body, con)
            con.execute('INSERT INTO products(id,code,name,category,aliases,created_at) VALUES(?,?,?,?,?,?)',
                        (identifier, *values, int(time.time())))
            result = product_json(con.execute('SELECT * FROM products WHERE id=?', (identifier,)).fetchone())
    except sqlite3.IntegrityError:
        fail(409, '此产品 SKU 已存在，请选择现有产品。')
    audit('新建产品', actor, values[0])
    return result


@app.put('/api/products/{identifier}')
def update_product(identifier: str, body: ProductInput, actor: str = Depends(staff)):
    try:
        with db() as con:
            con.execute('BEGIN IMMEDIATE')
            values = product_data(body, con)
            if not con.execute('SELECT 1 FROM products WHERE id=?', (identifier,)).fetchone():
                fail(404, '产品不存在。')
            con.execute('UPDATE products SET code=?,name=?,category=?,aliases=? WHERE id=?', (*values, identifier))
    except sqlite3.IntegrityError:
        fail(409, '此产品 SKU 已被使用。')
    audit('修改产品', actor, values[0])
    return {'ok': True}


IMAGE_SELECT = '''SELECT i.*,p.code product_code,p.name product_name,p.category
                  FROM images i LEFT JOIN products p ON p.id=i.product_id'''


class AssociateImagesInput(BaseModel):
    image_ids: list[str] = Field(min_length=1, max_length=100)


@app.post('/api/products/{identifier}/images/associate')
def associate_product_images(identifier: str, body: AssociateImagesInput, actor: str = Depends(staff)):
    identifiers = list(dict.fromkeys(body.image_ids))
    if any(not re.fullmatch(r'[a-f0-9]{32}', value) for value in identifiers):
        fail(400, '图片 ID 无效。')
    with db() as con:
        con.execute('BEGIN IMMEDIATE')
        product = con.execute('SELECT id,code FROM products WHERE id=?', (identifier,)).fetchone()
        if not product:
            fail(404, '产品不存在，请刷新产品目录。')
        marks = ','.join('?' for _ in identifiers)
        rows = con.execute(f'SELECT id,product_id,deleted_at FROM images WHERE id IN ({marks})', identifiers).fetchall()
        if len(rows) != len(identifiers) or any(row['deleted_at'] is not None for row in rows):
            fail(409, '部分图片已删除或移入回收站，本次未关联任何图片。请重新选择。')
        if any(row['product_id'] not in (None, identifier) for row in rows):
            fail(409, '部分图片已被关联到其他产品，本次未关联任何图片。请重新选择。')
        pending = [row['id'] for row in rows if row['product_id'] is None]
        if pending:
            con.executemany('UPDATE images SET product_id=? WHERE id=?', [(identifier, image_id) for image_id in pending])
            con.execute('INSERT INTO audit(action,actor,detail,created_at) VALUES(?,?,?,?)',
                        ('批量关联产品图片', actor,
                         json.dumps({'product_id': identifier, 'sku': product['code'], 'image_ids': pending}, ensure_ascii=False),
                         int(time.time())))
        count = con.execute('SELECT count(*) FROM images WHERE product_id=? AND deleted_at IS NULL', (identifier,)).fetchone()[0]
    return {'ok': True, 'associated': len(pending), 'already_associated': len(identifiers) - len(pending),
            'product_id': identifier, 'image_count': count}


def image_json(row):
    result = dict(row)
    result['tags'] = json.loads(result['tags'])
    result['has_alpha'] = bool(result['has_alpha'])
    result['thumbnail_url'] = f"/api/images/{result['id']}/file?variant=thumbnail"
    result['download_url'] = f"/api/images/{result['id']}/file"
    result.pop('sha256', None)
    return result


def get_image(identifier: str, include_deleted=False):
    with db() as con:
        row = con.execute(IMAGE_SELECT + ' WHERE i.id=?' + ('' if include_deleted else ' AND i.deleted_at IS NULL'), (identifier,)).fetchone()
    if not row:
        fail(404, '图片不存在或已移入回收站。')
    return row


@app.get('/api/images')
def list_images(q: str = Query('', max_length=200), product_code: str = Query('', max_length=80),
                product_id: str = '', kind: str = '', angle: str = '', background: str = '',
                category: str = Query('', max_length=80), filename: str = Query('', max_length=200),
                unassigned: bool = False, trash: bool = False,
                min_width: int = Query(0, ge=0, le=100000), limit: int = Query(48, ge=1, le=100),
                offset: int = Query(0, ge=0), actor: str = Depends(authenticate)):
    if trash and not is_admin(actor):
        fail(403, '只读令牌不可访问回收站。')
    clauses = ['i.deleted_at IS NOT NULL' if trash else 'i.deleted_at IS NULL']
    params = []
    for column, value in [('p.code', normalized(product_code)), ('i.product_id', product_id),
                          ('i.kind', kind), ('i.angle', angle), ('i.background', background),
                          ('p.category', normalized(category))]:
        if value:
            clauses.append(f'{column}=? COLLATE NOCASE')
            params.append(value)
    if unassigned:
        clauses.append('i.product_id IS NULL')
    if normalized(filename):
        clauses.append("i.original_name LIKE ? ESCAPE '!'")
        params.append(like(normalized(filename)))
    if min_width:
        clauses.append('i.width>=?')
        params.append(min_width)
    q = normalized(q)
    if q:
        if q.isdecimal():
            clauses.append('p.code=? COLLATE NOCASE')
            params.append(q)
        else:
            clauses.append("(p.code LIKE ? ESCAPE '!' OR p.name LIKE ? ESCAPE '!' OR i.original_name LIKE ? ESCAPE '!' OR EXISTS (SELECT 1 FROM json_each(p.aliases) WHERE value LIKE ? ESCAPE '!') OR EXISTS (SELECT 1 FROM json_each(i.tags) WHERE value LIKE ? ESCAPE '!'))")
            params += [like(q)] * 5
    where = ' WHERE ' + ' AND '.join(clauses)
    with db() as con:
        total = con.execute('SELECT count(*) FROM images i LEFT JOIN products p ON p.id=i.product_id' + where, params).fetchone()[0]
        rows = con.execute(IMAGE_SELECT + where + ' ORDER BY (p.code=? COLLATE NOCASE) DESC,i.created_at DESC,i.id LIMIT ? OFFSET ?', params + [q, limit, offset]).fetchall()
    return {'items': [image_json(row) for row in rows], 'total': total}


def validate_choices(kind, angle, background):
    if kind not in KINDS or angle not in ANGLES or background not in BACKGROUNDS:
        fail(400, '图片类型、角度或背景无效。')


def check_product(identifier):
    if identifier:
        with db() as con:
            if not con.execute('SELECT 1 FROM products WHERE id=?', (identifier,)).fetchone():
                fail(400, '所选产品不存在。')


@app.post('/api/images/upload')
def upload_image(file: UploadFile = File(...), product_id: str = Form(''), kind: str = Form('产品图'),
                 angle: str = Form('正面'), background: str = Form('透明'), tags: str = Form(''), actor: str = Depends(uploader)):
    validate_choices(kind, angle, background)
    check_product(product_id)
    identifier = uuid.uuid4().hex
    temporary = TEMP / (identifier + '.upload')
    original = thumbnail = None
    size = 0
    file_hash = hashlib.sha256()
    try:
        with temporary.open('wb') as output:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    fail(413, '单张图片不能超过 25 MB。')
                file_hash.update(chunk)
                output.write(chunk)
        with upload_lock, warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(temporary) as source:
                extension = {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp'}.get(source.format)
                if not extension:
                    fail(400, '仅支持 JPG、PNG、WebP 图片。')
                if getattr(source, 'n_frames', 1) > 1:
                    fail(400, '第一版仅支持静态图片，请上传单帧图片。')
                if source.width * source.height > MAX_PIXELS:
                    fail(400, '图片不能超过 4000 万像素。')
                source.verify()
            with db() as con:
                duplicate = con.execute('SELECT id,product_id FROM images WHERE sha256=? AND deleted_at IS NULL', (file_hash.hexdigest(),)).fetchall()
                for item in duplicate:
                    if (item['product_id'] or '') == product_id:
                        return {'duplicate': True, 'image': image_json(get_image(item['id']))}
            with Image.open(temporary) as source:
                corrected = ImageOps.exif_transpose(source)
                width, height = corrected.size
                has_alpha = ('A' in corrected.getbands() or 'transparency' in corrected.info) and corrected.convert('RGBA').getchannel('A').getextrema()[0] < 255
                corrected.thumbnail((720, 720))
                thumbnail = THUMBS / (identifier + '.webp')
                corrected.convert('RGBA' if has_alpha else 'RGB').save(thumbnail, 'WEBP', quality=85)
            if background == '透明' and not has_alpha:
                fail(400, '此文件没有透明像素。请改选「其他」背景，或先另存为带透明通道的 PNG / WebP 再上传。')
            if has_alpha:
                background = '透明'
            original = ORIGINALS / (identifier + '.' + extension)
            temporary.replace(original)
            mime = {'jpg': 'image/jpeg', 'png': 'image/png', 'webp': 'image/webp'}[extension]
            parsed_tags = unique_strings(re.split('[,，]', tags), limit=20, length=40)
            with db() as con:
                con.execute('''INSERT INTO images(id,product_id,original_name,extension,mime_type,width,height,size,sha256,
                    kind,angle,background,has_alpha,tags,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (identifier, product_id or None, (file.filename or '图片')[:200], extension, mime, width, height,
                     size, file_hash.hexdigest(), kind, angle, background, int(has_alpha), json.dumps(parsed_tags, ensure_ascii=False), int(time.time())))
        audit('上传图片', actor, identifier)
        return {'duplicate': False, 'image': image_json(get_image(identifier))}
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        fail(400, '图片无法解码、内容损坏或尺寸过大，请更换文件。')
    finally:
        temporary.unlink(missing_ok=True)
        with db() as con:
            saved = con.execute('SELECT 1 FROM images WHERE id=?', (identifier,)).fetchone()
        if not saved:
            if original:
                original.unlink(missing_ok=True)
            if thumbnail:
                thumbnail.unlink(missing_ok=True)


class ImageInput(BaseModel):
    product_id: str | None = None
    kind: str = '产品图'
    angle: str = '正面'
    background: str = '透明'
    tags: list[str] = Field(default_factory=list, max_length=20)


@app.get('/api/images/{identifier}')
def image_info(identifier: str, actor: str = Depends(authenticate)):
    return image_json(get_image(identifier))


@app.put('/api/images/{identifier}')
def update_image(identifier: str, body: ImageInput, actor: str = Depends(staff)):
    row = get_image(identifier)
    validate_choices(body.kind, body.angle, body.background)
    check_product(body.product_id)
    if (body.background == '透明') != bool(row['has_alpha']):
        fail(400, '背景分类必须与文件的真实透明属性一致。')
    with db() as con:
        con.execute('UPDATE images SET product_id=?,kind=?,angle=?,background=?,tags=? WHERE id=?',
                    (body.product_id or None, body.kind, body.angle, body.background,
                     json.dumps(unique_strings(body.tags, limit=20, length=40), ensure_ascii=False), identifier))
    audit('修改图片资料', actor, identifier)
    return image_json(get_image(identifier))


def download_name(row):
    base = (row['product_code'] or '未关联') + '_' + row['kind'] + '_' + row['angle']
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', base)[:100].strip('. ')
    return f"{base}_{row['id'][:8]}.{row['extension']}"


@app.get('/api/images/{identifier}/file')
def image_file(identifier: str, variant: str = Query('original', pattern='^(original|thumbnail)$'), actor: str = Depends(authenticate)):
    row = get_image(identifier, include_deleted=is_admin(actor) and variant == 'thumbnail')
    if variant == 'thumbnail':
        return FileResponse(THUMBS / (row['id'] + '.webp'), media_type='image/webp')
    audit('下载原图', actor, identifier)
    return FileResponse(ORIGINALS / (row['id'] + '.' + row['extension']), media_type=row['mime_type'], filename=download_name(row))


@app.delete('/api/images/{identifier}')
def trash_image(identifier: str, actor: str = Depends(admin)):
    get_image(identifier)
    with db() as con:
        con.execute('UPDATE images SET deleted_at=? WHERE id=?', (int(time.time()), identifier))
    audit('移入回收站', actor, identifier)
    return {'ok': True}


@app.post('/api/images/{identifier}/restore')
def restore_image(identifier: str, actor: str = Depends(admin)):
    with storage_lock(DATA):
        get_image(identifier, include_deleted=True)
        with db() as con:
            con.execute('UPDATE images SET deleted_at=NULL WHERE id=?', (identifier,))
    audit('恢复图片', actor, identifier)
    return {'ok': True}


class DeleteImagesInput(BaseModel):
    image_ids: list[str] = Field(min_length=1, max_length=100)


@app.post('/api/images/delete')
def delete_images(body: DeleteImagesInput, actor: str = Depends(admin)):
    """Commit a durable removal queue before touching files; failures can be retried."""
    identifiers = list(dict.fromkeys(body.image_ids))
    for identifier in identifiers:
        if not re.fullmatch(r'[a-f0-9]{32}', identifier):
            fail(400, '图片 ID 无效。')
    with storage_lock(DATA):
        with db() as con:
            con.execute('BEGIN IMMEDIATE')
            rows = [con.execute('SELECT id,extension,deleted_at FROM images WHERE id=?', (identifier,)).fetchone()
                    for identifier in identifiers]
            if any(row is None for row in rows):
                fail(404, '图片不存在或已经永久删除。')
            if any(row['deleted_at'] is None for row in rows):
                fail(409, '请先把图片移入回收站，再永久删除。')
            now = int(time.time())
            con.executemany('INSERT INTO pending_deletes(id,extension,created_at) VALUES(?,?,?)',
                            [(row['id'], row['extension'], now) for row in rows])
            con.executemany('DELETE FROM images WHERE id=?', [(identifier,) for identifier in identifiers])
            con.execute('INSERT INTO audit(action,actor,detail,created_at) VALUES(?,?,?,?)',
                        ('永久删除图片', actor, ','.join(identifiers)[:500], now))
        pending = clean_pending_files(locked=True)
    result = {'ok': True, 'deleted': len(identifiers)}
    if pending:
        result['cleanup_pending'] = pending
    return result


def clean_pending_files(locked=False):
    if not locked:
        with storage_lock(DATA):
            return clean_pending_files(locked=True)
    with db() as con:
        rows = con.execute('SELECT id,extension FROM pending_deletes').fetchall()
    remaining = 0
    for row in rows:
        if not re.fullmatch(r'[a-f0-9]{32}', row['id']) or row['extension'] not in ('png', 'jpg', 'webp'):
            remaining += 1
            continue
        with db() as con:
            if con.execute('SELECT 1 FROM images WHERE id=?', (row['id'],)).fetchone():
                remaining += 1
                continue
        failed = False
        for path in (ORIGINALS / (row['id'] + '.' + row['extension']), THUMBS / (row['id'] + '.webp')):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                failed = True
        if failed:
            remaining += 1
        else:
            with db() as con:
                con.execute('DELETE FROM pending_deletes WHERE id=?', (row['id'],))
    return remaining


class ExportInput(BaseModel):
    image_ids: list[str] = Field(min_length=1, max_length=100)


@app.post('/api/export')
def export_images(body: ExportInput, actor: str = Depends(authenticate)):
    rows = [get_image(identifier) for identifier in dict.fromkeys(body.image_ids)]
    if sum(row['size'] for row in rows) > 500 * 1024 * 1024:
        fail(400, '单次打包上限为 500 MB，请分批下载。')
    target = TEMP / (uuid.uuid4().hex + '.zip')
    try:
        with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_STORED) as archive:
            for row in rows:
                archive.write(ORIGINALS / (row['id'] + '.' + row['extension']), download_name(row))
        audit('批量下载', actor, ','.join(row['id'] for row in rows))
        return FileResponse(target, media_type='application/zip', filename='product-images.zip', background=BackgroundTask(target.unlink, missing_ok=True))
    except Exception:
        target.unlink(missing_ok=True)
        raise


@app.get('/api/overview')
def overview(actor: str = Depends(authenticate)):
    if actor_role(actor) not in ('admin', 'staff', 'external') or actor.startswith('token:'):
        fail(403, '概览需要浏览器账号登录。')
    with db() as con:
        counts = dict(con.execute('''SELECT count(*) images,coalesce(sum(size),0) total_bytes,
            coalesce(sum(CASE WHEN product_id IS NULL THEN 1 ELSE 0 END),0) unassigned,
            coalesce(sum(has_alpha),0) transparent FROM images WHERE deleted_at IS NULL''').fetchone())
        counts['products'] = con.execute('SELECT count(*) FROM products').fetchone()[0]
        counts['trash'] = con.execute('SELECT count(*) FROM images WHERE deleted_at IS NOT NULL').fetchone()[0] if is_admin(actor) else 0
        counts['categories'] = [r[0] for r in con.execute('SELECT name FROM categories ORDER BY name')]
    return counts


class TokenInput(BaseModel):
    name: str = Field(min_length=1, max_length=60)


@app.get('/api/tokens')
def list_tokens(actor: str = Depends(staff)):
    query = 'SELECT t.id,t.name,t.prefix,t.created_at,t.last_used_at,a.username owner ' \
            'FROM tokens t LEFT JOIN accounts a ON a.id=t.account_id'
    with db() as con:
        if is_admin(actor):
            rows = con.execute(query + ' ORDER BY t.created_at DESC').fetchall()
        else:
            # An internal account only ever sees the tokens it issued itself.
            rows = con.execute(query + ' WHERE t.account_id=? ORDER BY t.created_at DESC',
                               (actor_account(actor),)).fetchall()
    return {'items': [dict(row) for row in rows]}


@app.post('/api/tokens')
def create_token(body: TokenInput, actor: str = Depends(staff)):
    identifier = uuid.uuid4().hex
    # A token issued by an internal colleague may upload; the administrator's token only reads.
    owner = actor_account(actor)
    secret = 'img_' + secrets.token_urlsafe(32)
    with db() as con:
        con.execute('INSERT INTO tokens(id,name,hash,prefix,created_at,account_id) VALUES(?,?,?,?,?,?)',
                    (identifier, body.name.strip(), digest(secret), secret[:10], int(time.time()), owner))
    audit('创建令牌', actor, body.name)
    return {'id': identifier, 'token': secret, 'name': body.name}


@app.delete('/api/tokens/{identifier}')
def revoke_token(identifier: str, actor: str = Depends(staff)):
    with db() as con:
        row = con.execute('SELECT account_id,name FROM tokens WHERE id=?', (identifier,)).fetchone()
        if not row:
            fail(404, '令牌不存在。')
        if not is_admin(actor) and row['account_id'] != actor_account(actor):
            fail(403, '只能撤销自己创建的令牌。')
        con.execute('DELETE FROM tokens WHERE id=?', (identifier,))
    audit('撤销令牌', actor, row['name'])
    return {'ok': True}


@app.get('/api/audit')
def list_audit(actor: str = Depends(admin)):
    with db() as con:
        return {'items': [dict(row) for row in con.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 100')]}


@app.get('/api/openapi.json', include_in_schema=False)
def openapi(actor: str = Depends(authenticate)):
    return app.openapi()


class RevalidatingStatics(StaticFiles):
    """Force the browser to revalidate HTML/CSS/JS so code changes take effect on reload."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers['Cache-Control'] = 'no-cache'
        return response


app.mount('/static', RevalidatingStatics(directory=PROJECT / 'static'), name='static')


@app.get('/', include_in_schema=False)
def home():
    return FileResponse(PROJECT / 'static' / 'index.html', headers={'Cache-Control': 'no-store'})
