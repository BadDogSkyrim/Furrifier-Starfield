"""--overlay: a folder that reads as Data with another folder's files laid over it."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fsftools.overlay import clear_view, merged_view, overlay_roots  # noqa: E402


def put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode())


def tree(tmp_path):
    data, over = tmp_path / 'Data', tmp_path / 'Over'
    put(data / 'Starfield.esm', 'vanilla')
    put(data / 'FSF.esm', 'live fsf')
    put(data / 'Meshes' / 'Actors' / 'Human' / 'head.nif', 'human head')
    put(data / 'Meshes' / 'Actors' / 'FSF' / 'fox.nif', 'live fox')
    put(data / 'Meshes' / 'Actors' / 'FSF' / 'gone.nif', 'deleted from the mod, still deployed')
    put(over / 'FSF.esm', 'snapshot fsf')
    put(over / 'meshes' / 'actors' / 'FSF' / 'fox.nif', 'snapshot fox')
    put(over / 'Meshes' / 'Actors' / 'FSF' / 'new.nif', 'only in the snapshot')
    return data, over


def test_overlay_files_win_and_the_rest_reads_through(tmp_path):
    data, over = tree(tmp_path)
    view = merged_view(data, over, where=tmp_path / 'view')
    assert (view / 'FSF.esm').read_text() == 'snapshot fsf'
    assert (view / 'Starfield.esm').read_text() == 'vanilla'
    assert (view / 'Meshes' / 'Actors' / 'FSF' / 'fox.nif').read_text() == 'snapshot fox'   # any case
    assert (view / 'Meshes' / 'Actors' / 'FSF' / 'new.nif').read_text() == 'only in the snapshot'
    assert (view / 'Meshes' / 'Actors' / 'Human' / 'head.nif').read_text() == 'human head'
    assert (view / 'Meshes' / 'Actors' / 'FSF' / 'gone.nif').exists()     # nothing replaced: still there


def test_a_replaced_mod_s_files_are_hidden(tmp_path):
    """The overlay stands in for a mod: what that mod deploys is hidden, so nothing reads live."""
    data, over = tree(tmp_path)
    mod = tmp_path / 'Mods' / 'FSF'
    put(mod / 'FSF.esm', 'live fsf')
    put(mod / 'Meshes' / 'Actors' / 'FSF' / 'fox.nif', 'live fox')
    put(mod / 'Meshes' / 'Actors' / 'FSF' / 'gone.nif', 'x')
    view = merged_view(data, over, replaces=[mod], where=tmp_path / 'view')
    assert not (view / 'Meshes' / 'Actors' / 'FSF' / 'gone.nif').exists()
    assert (view / 'Meshes' / 'Actors' / 'FSF' / 'fox.nif').read_text() == 'snapshot fox'
    assert (view / 'Meshes' / 'Actors' / 'Human' / 'head.nif').read_text() == 'human head'


def test_named_files_are_hidden_whoever_deploys_them(tmp_path):
    """A furrifier output plugin some profile deploys (FSFNPC.esm) is hidden by name, cheaply: its
    mod's 40,000 FaceGen files don't have to be walked."""
    data, over = tree(tmp_path)
    put(data / 'FSFNPC.esm', 'furrified')
    put(data / 'Meshes' / 'Actors' / 'Human' / 'other.nif', 'stays')
    view = merged_view(data, over, replaces=[], hide=['FSFNPC.esm', 'meshes/actors/human/head.nif'],
                       where=tmp_path / 'view')
    assert not (view / 'FSFNPC.esm').exists()
    assert not (view / 'Meshes' / 'Actors' / 'Human' / 'head.nif').exists()
    assert (view / 'Meshes' / 'Actors' / 'Human' / 'other.nif').read_text() == 'stays'
    assert (view / 'Starfield.esm').exists()


def test_clearing_the_view_leaves_data_and_overlay_alone(tmp_path):
    data, over = tree(tmp_path)
    before = sorted((p.relative_to(tmp_path).as_posix(), p.read_bytes()) for p in tmp_path.rglob('*') if p.is_file())
    view = merged_view(data, over, where=tmp_path / 'view')
    assert (view / 'Meshes').exists()
    clear_view(view)
    assert not view.exists()
    after = sorted((p.relative_to(tmp_path).as_posix(), p.read_bytes()) for p in tmp_path.rglob('*') if p.is_file())
    assert after == before


def test_a_tool_s_data_roots_take_the_view(tmp_path):
    """The first data folder that exists becomes the view; paths under it follow; others don't."""
    data, over = tree(tmp_path)
    assets = tmp_path / 'Assets'
    assets.mkdir()
    roots, rebase = overlay_roots([tmp_path / 'missing', data, assets], over, log=lambda s: None)
    view = Path(roots[1])
    try:
        assert roots[0] == str(tmp_path / 'missing') and roots[2] == str(assets)
        assert (view / 'FSF.esm').read_text() == 'snapshot fsf'
        assert Path(rebase(data / 'Meshes' / 'Actors')) == view / 'Meshes' / 'Actors'
        assert rebase(str(assets / 'x.nif')) == str(assets / 'x.nif')
    finally:
        clear_view(view)


def test_building_again_replaces_the_old_view(tmp_path):
    data, over = tree(tmp_path)
    merged_view(data, over, where=tmp_path / 'view')
    os.remove(over / 'Meshes' / 'Actors' / 'FSF' / 'new.nif')
    view = merged_view(data, over, where=tmp_path / 'view')
    assert not (view / 'Meshes' / 'Actors' / 'FSF' / 'new.nif').exists()
    assert (data / 'Starfield.esm').read_text() == 'vanilla'
