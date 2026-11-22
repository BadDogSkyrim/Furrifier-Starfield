"""Writes that are whole or absent: the bytes go to a scratch file beside the target, which then
replaces it in one rename. Stopping the run (Ctrl-C) mid-write leaves the old file, or none, and
no scratch file -- never a truncated plugin or texture where the game will load it."""
import os
from contextlib import contextmanager
from pathlib import Path

SCRATCH_SUFFIX = '.partial'


@contextmanager
def replacing(path):
    """Yield a scratch path to write; on success it replaces `path`, on any failure it's removed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    scratch = path.with_name(path.name + SCRATCH_SUFFIX)
    try:
        yield scratch
        os.replace(scratch, path)
    finally:
        if scratch.exists():
            scratch.unlink()


def write_bytes(path, data: bytes):
    with replacing(path) as scratch:
        with open(scratch, 'wb') as f:
            f.write(data)
