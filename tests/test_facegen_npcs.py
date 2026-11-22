"""The FaceGen bake against the Creation Kit's, on the tests' own NPCs (FSFTest.esm).

Each NPC in tests/fixtures/fsftest/FSFTest.esm (written by make_test_plugin.py, which says what each
one covers) is read back with change_from_npc and baked by the furrifier's pipeline, then compared
with the CK's bake of the same NPC from the same FSF snapshot. The CK's files are in
tests/fixtures/ck_bake/fsftest, laid out as the CK writes them; see tests/fixtures/ck_bake/README.txt.
"""
import struct
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from esplib import Plugin  # noqa: E402
from fsfdata import RACES, game_data  # noqa: E402
from fsftools import facegen  # noqa: E402
from fsftools.config import load_races  # noqa: E402
from fsftools.furrify_npc import change_from_npc  # noqa: E402
from fsftools.plugin_loader import load_order_for_plugin, load_plugins  # noqa: E402
from fsftools.race_data import RaceAppearance, avm_index, race_avm, tint_plugin_path  # noqa: E402
from make_test_plugin import FIRST_ID, NPCS  # noqa: E402
from test_facegen import decode_png, mesh_paths, shape_names, without_shape_flag  # noqa: E402

IDS = {npc[0]: f'{FIRST_ID + i:08X}' for i, npc in enumerate(NPCS)}
CK = ROOT / 'tests' / 'fixtures' / 'ck_bake' / 'fsftest'
GEOM = Path('Meshes') / 'Actors' / 'Character' / 'FaceGenData' / 'FaceGeom' / 'FSFTest.esm'
TEX = Path('Textures') / 'Actors' / 'Character' / 'FaceCustomization' / 'FSFTest.esm'
EXPORT_INFO = 0x40      # the header's export-info short string, after the author and process script


def ck_file(rel):
    path = CK / rel
    if not path.is_file():
        pytest.fail(f"the CK's bake isn't in the fixtures: {path}. Bake FSFTest.esm's NPCs in the CK "
                    f"and copy them in (tests/fixtures/ck_bake/README.txt)")
    return path


@pytest.fixture(scope='module')
def baked():
    data = game_data()
    order = load_order_for_plugin(data, 'FSFTest.esm')
    plugins = load_plugins(data, order)
    base = avm_index(plugins, order)
    appearances = {}
    for edid, cfg in load_races(RACES).items():
        tint = Plugin.load(str(tint_plugin_path(cfg.tint_plugin, data)), only_signatures={'AVMD'})
        appearances[edid] = RaceAppearance(cfg, plugins, race_avm(base, tint), data)
    changes = [change_from_npc(plugins.get_record_by_edid('NPC_', edid), plugins) for edid in IDS]
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        count, problems = facegen.bake_all(changes, appearances, plugins, data, out, log=lambda *a: None)
        assert count == len(IDS) and not problems, problems
        yield dict(out=out, plugins=plugins, data=data, changes={c.npc_editorid: c for c in changes})


def without_export_info(nif: bytes) -> bytes:
    """The nif minus its header's export-info string, where the CK leaves what looks like stale memory
    (different bytes and lengths from one bake to the next)."""
    assert nif[0x38:EXPORT_INFO] == bytes.fromhex('010003000000' '0100'), nif[0x38:EXPORT_INFO].hex()
    return nif[:EXPORT_INFO] + nif[EXPORT_INFO + 1 + nif[EXPORT_INFO]:]


@pytest.mark.parametrize('edid', list(IDS))
def test_nif_has_the_cks_parts(baked, edid):
    """The same shapes, extra parts included; built in the CK's order with its mesh names and counts
    put in, the same bytes. (The CK's order follows neither the record, FormID nor part type --
    hash order, it seems -- and nothing reads it, so it isn't matched.)"""
    ident = IDS[edid]
    ck = ck_file(GEOM / f'{ident}.NIF').read_bytes()
    mine = (baked['out'] / GEOM / f'{ident}.NIF').read_bytes()
    assert sorted(shape_names(mine)) == sorted(shape_names(ck))
    geometries = [b for t, b in facegen.read_nif(ck).blocks if t == 'BSGeometry']
    shapes = []
    for name, mesh, geometry in zip(shape_names(ck), mesh_paths(ck), geometries):
        hdpt = baked['plugins'].get_record_by_edid('HDPT', name)
        source = facegen.load_part_source(baked['data'], hdpt, baked['plugins'])
        tri_size, num_verts = struct.unpack_from('<II', geometry, facegen._geometry_fields(geometry)['mesh'])
        shapes.append((name, source, facegen.BakedMesh(mesh, tri_size, num_verts, b'')))
    assert without_export_info(without_shape_flag(facegen.build_nif(shapes))) == \
        without_export_info(without_shape_flag(ck))


@pytest.mark.parametrize('edid', list(IDS))
def test_meshes_match_the_cks(baked, edid):
    """Each part's baked mesh: same layout, UVs and weights; positions within about 0.6 mm, but for
    the teeth, which the CK doesn't morph."""
    ident = IDS[edid]
    ck = ck_file(GEOM / f'{ident}.NIF').read_bytes()
    mine = (baked['out'] / GEOM / f'{ident}.NIF').read_bytes()
    ours_by_name = dict(zip(shape_names(mine), mesh_paths(mine)))
    for name, theirs in zip(shape_names(ck), mesh_paths(ck)):
        ours = ours_by_name[name]
        a = facegen.split_mesh((baked['out'] / 'Geometries' / (ours.replace('\\', '/') + '.mesh')).read_bytes())
        b = facegen.split_mesh(ck_file(Path('Geometries') / (theirs.replace('\\', '/') + '.mesh')).read_bytes())
        for section in ('head', 'uv', 'weights', 'tail'):
            assert a[section] == b[section], (name, section)
        if name.endswith('_Teeth'):
            # The CK leaves the teeth unmorphed (its teeth are the source mesh, to the rounding);
            # ours follow the chargen morphs, which Bad Dog checked is right (2026-11-21).
            continue
        pos, ck_pos = (np.frombuffer(x['pos'], '<i2').astype(int) for x in (a, b))
        assert np.abs(pos - ck_pos).max() <= 10, name


def compared(baked, edid):
    """Where to compare an NPC's colour and maps with the CK's: everywhere but the Null region.

    The CK fills Null from the first region (alphabetically) that has a slider, at that slider's
    value (the later phenotype's, if two share the region), and leaves the rest black; with no
    sliders at all, from the default maps. Measured 2026-11-21/22 on six bakes: Chin 0.8 -> Null
    x0.80; Eyes 0.5 -> x0.50; Cheeks 0.183 + 0.707 -> x0.706; every slider at 1.0 -> as ours; none
    -> *_default. Bad Dog's call: a CK bug, not copied. Ours fills Null with the phenotype."""
    change = baked['changes'][edid]
    race = baked['plugins'].get_record_by_edid('RACE', change.new_race_edid)
    fctp = next(bytes(s.data).rstrip(b'\0').decode() for s in race.subrecords if s.signature == 'FCTP')
    null = decode_png(baked['data'] / 'Textures' / fctp / 'FCT_Null_mask.dds', baked['out'])[..., 0]
    return null == 0


@pytest.mark.parametrize('edid', list(IDS))
def test_colour_matches_the_cks(baked, edid):
    ident = IDS[edid]
    where = compared(baked, edid)

    def read(path):
        b = Path(path).read_bytes()
        h, w = struct.unpack_from('<II', b, 12)
        return np.frombuffer(b, np.uint8, h * w * 4, 148).reshape(h, w, 4)[..., :3] / 255.0
    error = np.abs(read(baked['out'] / TEX / f'{ident}_Color.dds') - read(ck_file(TEX / f'{ident}_Color.dds')))
    assert error[where].max() < 0.01, error[where].max()


@pytest.mark.parametrize('edid', list(IDS))
def test_maps_match_the_cks(baked, edid, tmp_path):
    """Normal, roughness and AO, blended per region as the CK does."""
    ident = IDS[edid]
    where = compared(baked, edid)
    for d in ('mine', 'ck'):
        (tmp_path / d).mkdir()
    for suffix, limit, channels in (('rough', 0.5, 1), ('ao', 0.5, 1), ('Normal', 5.5, 2)):
        mine = decode_png(baked['out'] / TEX / f'{ident}_{suffix}.dds', tmp_path / 'mine')
        theirs = decode_png(ck_file(TEX / f'{ident}_{suffix}.dds'), tmp_path / 'ck')
        assert np.abs(mine[..., :channels] - theirs[..., :channels])[where].mean() < limit, suffix
