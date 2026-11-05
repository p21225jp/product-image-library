"""Coordinate file removal and backups across the web server and maintenance CLI."""
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

_locks: dict[str, threading.Lock] = {}
_guard = threading.Lock()


@contextmanager
def storage_lock(data: Path, timeout: float = 60):
    data = data.resolve()
    data.mkdir(parents=True, exist_ok=True)
    with _guard:
        local_lock = _locks.setdefault(os.path.normcase(str(data)), threading.Lock())
    deadline = time.monotonic() + timeout
    if not local_lock.acquire(timeout=timeout):
        raise TimeoutError('素材文件正在备份或清理，请稍后重试。')
    try:
        with (data / '.storage.lock').open('a+b') as handle:
            if handle.tell() == 0:
                handle.write(b'0')
                handle.flush()
            while True:
                try:
                    handle.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError('素材文件正在备份或清理，请稍后重试。')
                    time.sleep(0.05)
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        local_lock.release()
