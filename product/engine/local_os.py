"""Small OS boundary for private files, bootstrap locking and detached startup."""
import errno
import os
import stat
import sys
import time
from contextlib import contextmanager
from pathlib import Path


def reject_link(path):
    path = Path(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError("Private runtime paths cannot be symlinks or reparse points")


def private_opener(name, flags):
    reject_link(name)
    return os.open(name, flags | getattr(os, "O_NOFOLLOW", 0), 0o600)


@contextmanager
def bootstrap_lock(path):
    reject_link(path)
    with open(path, "a+b", opener=private_opener) as lock:
        if sys.platform == "win32":
            import msvcrt
            # Windows locks byte ranges; always lock the same existing byte.
            lock.seek(0, os.SEEK_END)
            if not lock.tell():
                lock.write(b"\0")
                lock.flush()
            deadline = time.monotonic() + 35
            while True:
                try:
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as error:
                    if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK} or time.monotonic() >= deadline:
                        raise
                    time.sleep(.1)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            yield


def helper_process_options(platform=sys.platform):
    if platform == "win32":
        # No console flash; the helper outlives the short-lived browser native host.
        return {"creationflags": 0x00000200 | 0x08000000}  # NEW_PROCESS_GROUP | NO_WINDOW
    return {"start_new_session": True}


def binary_native_stdio():
    if sys.platform == "win32":
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
