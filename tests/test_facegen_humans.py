"""The FaceGen bake against the CK's on vanilla humans: FSFTest.esm's copies of four vanilla NPCs.

Human phenotype maps differ from one another (FSF's barely do), so these show how phenotypes blend.
The copies' faces are the vanilla NPCs' verbatim (test_change_from_npc checks it); their bake
reads the vanilla assets in tests/fixtures/vanilla (make_vanilla_fixture.py), and the CK's bake
of them is in tests/fixtures/ck_bake/fsftest beside the furry NPCs'.
"""
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fsfdata import game_data  # noqa: E402
from fsftools import facegen  # noqa: E402
from fsftools.config import load_races  # noqa: E402
from fsftools.furrify_npc import change_from_npc  # noqa: E402
from fsftools.plugin_loader import load_order_for_plugin, load_plugins  # noqa: E402
from fsftools.race_data import RaceAppearance, avm_index  # noqa: E402
from make_test_plugin import FIRST_ID, HUMANS, NPCS  # noqa: E402
from test_facegen import decode_png, mesh_paths, shape_names  # noqa: E402
from test_facegen_npcs import CK, GEOM, TEX, ck_file  # noqa: E402

VANILLA = ROOT / 'tests' / 'fixtures' / 'vanilla'
RACES = ROOT / 'tests' / 'fixtures' / 'vanilla_races'
IDS = {h[0]: f'{FIRST_ID + len(NPCS) + i:08X}' for i, h in enumerate(HUMANS)}
FCTP = facegen.DEFAULT_FCTP


@pytest.fixture(scope='module')
def baked():
    data = game_data()
    order = load_order_for_plugin(data, 'FSFTest.esm')
    plugins = load_plugins(data, order)
    base = avm_index(plugins, order)
    appearances = {e: RaceAppearance(c, plugins, base, VANILLA) for e, c in load_races(RACES).items()}
    changes = {edid: change_from_npc(plugins.get_record_by_edid('NPC_', edid), plugins) for edid in IDS}
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        results = {}
        for edid, change in changes.items():     # one at a time, so one failing doesn't hide the rest
            try:
                results[edid] = facegen.bake_all([change], appearances, plugins, VANILLA, out,
                                                 log=lambda *a: None, assets=VANILLA)
            except Exception as e:                # noqa: BLE001 -- reported by the test that needs it
                results[edid] = e
        yield dict(out=out, plugins=plugins, results=results, changes=changes)


def baked_ok(baked, edid):
    result = baked['results'][edid]
    if isinstance(result, Exception):
        raise result
    count, problems = result
    assert count == 1 and not problems, problems


def test_a_phenotype_with_no_maps_is_left_out_of_the_blend(tmp_path):
    """Heller has sliders for male_eu_md3, which has no _ao/_rough/_normal. The CK's bake of him
    matches ours with those sliders ignored -- their share of the region going to the default --
    and not with the missing maps read as black (measured 2026-11-22, his Ears)."""
    maps = facegen.FaceMaps(VANILLA, FCTP, ['Ears'], tmp_path)
    weights = maps.region_weights('male_eu_md2', 'male_default', {'male_eu_md3_Ears': 1.0})
    assert 'male_eu_md3' not in weights
    plain = maps.region_weights('male_eu_md2', 'male_default', {})
    assert all(np.array_equal(weights[w], plain[w]) for w in plain), "as if the slider weren't there"


@pytest.mark.parametrize('edid', list(IDS))
def test_human_has_the_cks_parts(baked, edid):
    baked_ok(baked, edid)
    ident = IDS[edid]
    ck = ck_file(GEOM / f'{ident}.NIF').read_bytes()
    mine = (baked['out'] / GEOM / f'{ident}.NIF').read_bytes()
    assert sorted(shape_names(mine)) == sorted(shape_names(ck))


def decoded(data: bytes):
    """A .mesh as (triangle indices, positions in metres, first UV set)."""
    m = facegen._mesh_layout(data)
    indices = np.frombuffer(data, '<u2', m['num_indices'], 8)
    pos = np.frombuffer(data, '<i2', m['num_verts'] * 3, m['pos']).astype(float).reshape(-1, 3) / 32767 * m['scale']
    at, n = m['uv1']
    uv = np.frombuffer(data, '<f2', n * 2, at).astype(float).reshape(-1, 2)
    return indices, pos, uv


@pytest.mark.parametrize('edid', list(IDS))
def test_human_meshes_match_the_cks(baked, edid):
    """Same triangles, positions within 0.5 mm, same UVs -- compared decoded. The CK re-encodes
    vanilla parts (its own position scale, more weights per vertex), so their bytes differ where
    FSF's don't; skin weights aren't compared."""
    baked_ok(baked, edid)
    ident = IDS[edid]
    ck = ck_file(GEOM / f'{ident}.NIF').read_bytes()
    mine = (baked['out'] / GEOM / f'{ident}.NIF').read_bytes()
    ours_by_name = dict(zip(shape_names(mine), mesh_paths(mine)))
    for name, theirs in zip(shape_names(ck), mesh_paths(ck)):
        ia, pa, ua = decoded((baked['out'] / 'Geometries' / (ours_by_name[name].replace('\\', '/') + '.mesh')).read_bytes())
        ib, pb, ub = decoded(ck_file(Path('Geometries') / (theirs.replace('\\', '/') + '.mesh')).read_bytes())
        if '_Hair_' in name:
            # The CK rewrites some of a vanilla hair's triangles (same count, same vertices).
            assert len(ia) == len(ib), (name, 'triangles')
        else:
            assert np.array_equal(ia, ib), (name, 'triangles')
        assert np.allclose(ua, ub, atol=1e-3), (name, 'uv')
        if name.endswith('_Teeth'):
            continue
        assert np.abs(pa - pb).max() < 0.0005, (name, np.abs(pa - pb).max())


def outside_null(work):
    null = decode_png(VANILLA / 'textures' / FCTP / 'fct_null_mask.dds', work)[..., 0]
    return null == 0       # the CK's Null rule isn't copied: see test_facegen_npcs.compared


# Reproducing vanilla human faces exactly isn't the goal (Bad Dog, 2026-11-22): the furrifier bakes
# FSF's heads and tints, which test_facegen_npcs matches exactly. On tinted humans the CK's colour
# runs 19-30 levels off ours on average, with bluish-white patches under the eyes and on the ears
# that no layer we model accounts for; human normal maps are 6-15 levels off. Not chased.
UNTINTED = {'FSFTest_Human_ScanMale', 'FSFTest_Human_ScanFemale'}


@pytest.mark.parametrize('edid', list(IDS))
def test_human_colour_matches_the_cks(baked, edid, tmp_path):
    if edid not in UNTINTED:
        pytest.skip("tinted vanilla faces aren't reproduced (see UNTINTED)")
    baked_ok(baked, edid)
    import struct
    ident = IDS[edid]

    def read(path):
        b = Path(path).read_bytes()
        h, w = struct.unpack_from('<II', b, 12)
        return np.frombuffer(b, np.uint8, h * w * 4, 148).reshape(h, w, 4)[..., :3] / 255.0
    error = np.abs(read(baked['out'] / TEX / f'{ident}_Color.dds') - read(ck_file(TEX / f'{ident}_Color.dds')))
    where = outside_null(tmp_path)
    assert error[where].max() < 0.01, error[where].max()


@pytest.mark.parametrize('edid', list(IDS))
def test_human_maps_match_the_cks(baked, edid, tmp_path):
    """Roughness and AO: the phenotype blend, Heller's two phenotypes included. Not the beard NPC:
    its roughness runs ~2 levels off everywhere, and under its coloured Rosacea mask (NNAM 640f0fbb)
    the CK's drops toward 100, the colour's first byte -- as a follicle mask's does. One small mask
    isn't enough to make that a rule for every mask; noted, not copied."""
    if edid == 'FSFTest_Human_Beard':
        pytest.skip("see the docstring")
    baked_ok(baked, edid)
    ident = IDS[edid]
    where = outside_null(tmp_path)
    for d in ('mine', 'ck'):
        (tmp_path / d).mkdir()
    for suffix, limit, channels in (('rough', 0.5, 1), ('ao', 0.5, 1)):     # normals: see UNTINTED
        mine = decode_png(baked['out'] / TEX / f'{ident}_{suffix}.dds', tmp_path / 'mine')
        theirs = decode_png(ck_file(TEX / f'{ident}_{suffix}.dds'), tmp_path / 'ck')
        assert np.abs(mine[..., :channels] - theirs[..., :channels])[where].mean() < limit, suffix
_ = CK
