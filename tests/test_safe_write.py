"""Ctrl-C mid-write leaves the old file or none, and no scratch file beside it."""
import pytest

from fsftools import facegen
from fsftools import safe_write


def test_write_replaces_whole(tmp_path):
    path = tmp_path / 'sub' / 'FSFNPC.esm'
    safe_write.write_bytes(path, b'one')
    safe_write.write_bytes(path, b'two')
    assert path.read_bytes() == b'two'
    assert [p.name for p in path.parent.iterdir()] == ['FSFNPC.esm']


def test_a_stop_mid_write_keeps_the_old_file(tmp_path):
    path = tmp_path / 'FSFNPC.esm'
    path.write_bytes(b'last run')
    with pytest.raises(KeyboardInterrupt):
        with safe_write.replacing(path) as scratch:
            scratch.write_bytes(b'half of the ne')
            raise KeyboardInterrupt
    assert path.read_bytes() == b'last run', 'the previous plugin is untouched'
    assert [p.name for p in tmp_path.iterdir()] == ['FSFNPC.esm'], 'no scratch file left'


def test_a_stop_before_the_first_write_leaves_nothing(tmp_path):
    path = tmp_path / 'x.dds'
    with pytest.raises(KeyboardInterrupt):
        with safe_write.replacing(path) as scratch:
            scratch.write_bytes(b'partial')
            raise KeyboardInterrupt
    assert list(tmp_path.iterdir()) == []


def test_shared_maps_leave_no_scratch_when_stopped(tmp_path):
    def interrupted(path):
        path.write_bytes(b'partial')
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        facegen._link_or_write({}, tmp_path / 'a_ao.dds', interrupted)
    assert list(tmp_path.iterdir()) == []
