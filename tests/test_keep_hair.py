"""--keep-hair: a furrified NPC keeps its own hair part; --assets finds vanilla files out of BA2s."""
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fsftools.facegen import find_asset  # noqa: E402
from fsftools.furrify_npc import npc_hair_parts  # noqa: E402


class Sub:
    def __init__(self, sig, data):
        self.signature, self.data = sig, data

    def get_form_id(self, offset=0):
        return struct.unpack_from('<I', self.data, offset)[0]


class Rec:
    def __init__(self, edid, subs):
        self.editor_id, self.subrecords, self.plugin = edid, subs, None

    def get_subrecord(self, sig):
        return next((s for s in self.subrecords if s.signature == sig), None)

    def get_subrecords(self, sig):
        return [s for s in self.subrecords if s.signature == sig]


def hdpt(edid, kind):
    return Rec(edid, [Sub('PNAM', struct.pack('<I', kind))])


class Plugins:
    def __init__(self, by_id):
        self.by_id = by_id

    def resolve_form_id(self, form_id, plugin):
        return self.by_id.get(form_id)


def test_only_the_hair_part_is_kept():
    parts = {1: hdpt('HumanFemaleHead', 1), 2: hdpt('Hair_Bob', 3), 3: hdpt('Brows_Thin', 6),
             4: hdpt('Beard_Full', 4), 5: hdpt('Hair_Bun', 3)}
    npc = Rec('SomeNPC', [Sub('PNAM', struct.pack('<I', i)) for i in (1, 2, 3, 4, 99)])
    assert [p.editor_id for p in npc_hair_parts(npc, Plugins(parts))] == ['Hair_Bob']
    assert npc_hair_parts(Rec('Bald', []), Plugins(parts)) == [], "no head parts: nothing to keep"


def test_assets_folder_is_searched_after_data(tmp_path):
    data, assets = tmp_path / 'Data', tmp_path / 'Assets'
    for root in (data, assets):
        (root / 'Meshes' / 'Hair').mkdir(parents=True)
    (data / 'Meshes' / 'Hair' / 'loose.nif').write_bytes(b'data')
    (assets / 'Meshes' / 'Hair' / 'loose.nif').write_bytes(b'assets')
    (assets / 'Meshes' / 'Hair' / 'vanilla.nif').write_bytes(b'assets')
    assert find_asset(Path('Meshes/Hair/loose.nif'), data, assets) == data / 'Meshes' / 'Hair' / 'loose.nif'
    assert find_asset(Path('Meshes/Hair/vanilla.nif'), data, assets) == assets / 'Meshes' / 'Hair' / 'vanilla.nif'
    assert find_asset(Path('Meshes/Hair/vanilla.nif'), data, None) == data / 'Meshes' / 'Hair' / 'vanilla.nif', \
        "no assets folder: the data path, as before"
    with pytest.raises(FileNotFoundError):
        find_asset(Path('Meshes/Hair/nowhere.nif'), data, assets).read_bytes()
