"""Local maintenance: consistent backups and administrator password recovery."""
import argparse
import getpass
import hashlib
import json
import os
import secrets
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from storage import storage_lock
from app.migrations import remove_retired_agent_state

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('ASSET_DATA_DIR', ROOT / 'data')).resolve()


def backup(destination: Path):
    destination = destination.resolve()
    if destination == DATA or DATA in destination.parents:
        raise ValueError('备份目标必须位于 data 目录之外。建议使用独立硬盘。')
    with storage_lock(DATA):
        destination.mkdir(parents=True, exist_ok=False)
        with sqlite3.connect(DATA / 'library.sqlite3') as source, sqlite3.connect(destination / 'library.sqlite3') as target:
            source.backup(target)
            target.execute('DELETE FROM sessions')
            remove_retired_agent_state(target)
            if target.execute("SELECT 1 FROM sqlite_master WHERE name='pending_deletes'").fetchone():
                target.execute('DELETE FROM pending_deletes')
            records = target.execute('SELECT id,extension,sha256 FROM images').fetchall()
        for folder in ['originals', 'thumbnails']:
            (destination / folder).mkdir()
        for identifier, extension, expected_hash in records:
            original = destination / 'originals' / f'{identifier}.{extension}'
            shutil.copy2(DATA / 'originals' / f'{identifier}.{extension}', original)
            shutil.copy2(DATA / 'thumbnails' / f'{identifier}.webp', destination / 'thumbnails' / f'{identifier}.webp')
            copied_hash = hashlib.sha256()
            with original.open('rb') as saved:
                while chunk := saved.read(1024 * 1024):
                    copied_hash.update(chunk)
            if copied_hash.hexdigest() != expected_hash:
                raise ValueError('原图校验失败，本次备份未完成。')
        # This completion marker is written only after every referenced file has been copied and verified.
        (destination / 'backup.json').write_text(json.dumps({'created_at': datetime.now().astimezone().isoformat(), 'images': len(records), 'format': 1}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'备份完成：{len(records)} 张图片。目标：{destination}')


def reset_password():
    first = getpass.getpass('新管理员密码（至少 10 位）：')
    second = getpass.getpass('再次输入：')
    if first != second or len(first) < 10:
        raise ValueError('密码不一致或不足 10 位。')
    salt = secrets.token_hex(16)
    hashed = hashlib.scrypt(first.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    with storage_lock(DATA), sqlite3.connect(DATA / 'library.sqlite3') as con:
        if not con.execute("SELECT 1 FROM settings WHERE key='username'").fetchone():
            raise ValueError('请先通过网页初始化管理员。')
        con.execute("UPDATE settings SET value=? WHERE key='salt'", (salt,))
        con.execute("UPDATE settings SET value=? WHERE key='password_hash'", (hashed,))
        con.execute('DELETE FROM sessions')
        con.execute('DELETE FROM tokens')
        remove_retired_agent_state(con, DATA)
    print('密码已更新，所有会话和只读令牌已撤销。')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='素材库本机维护工具')
    subcommands = parser.add_subparsers(dest='command', required=True)
    backup_parser = subcommands.add_parser('backup', help='备份数据库和全部原图（含回收站）')
    backup_parser.add_argument('destination', type=Path, help='一个尚不存在的新备份目录')
    subcommands.add_parser('reset-password', help='本机交互式重置密码并撤销令牌')
    args = parser.parse_args()
    if not (DATA / 'library.sqlite3').exists():
        parser.error('尚未找到数据库，请先启动应用。')
    if args.command == 'backup':
        backup(args.destination)
    else:
        reset_password()
