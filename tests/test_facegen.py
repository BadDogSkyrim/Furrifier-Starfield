"""The FaceGen bake, checked against output the Creation Kit wrote for the same inputs.

tests/fixtures/ck_bake holds a copy of the CK's files from 2026-11-05, so re-baking in the CK can't
move the target. The source assets come from the FSF snapshot. Whole-NPC comparisons against the CK
are in test_facegen_presets.py.
"""
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
from fsfdata import BUILTIN, RACES, SCHEME, game_data  # noqa: E402
sys.path.insert(0, str(ROOT))
from fsftools import facegen  # noqa: E402
from fsftools.plugin_loader import load_order_for_plugin, load_plugins  # noqa: E402

CK = ROOT / 'tests' / 'fixtures' / 'ck_bake'
DERM05 = r'Textures\Actors\FSFFox\faces\chargen\postblenddetails\dermaesthetic\male_fox_derm05_color.dds'
COMPLEX04 = r'Textures\Actors\FSFFox\faces\chargen\postblenddetails\complexion\Complexion04_color.dds'
DETAILS04 = r'Textures\Actors\FSFFox\faces\chargen\postblenddetails\complexion\Details04_mask.dds'
SK3 = r'Textures\Actors\FSFFox\faces\chargen\male_fox_sk3_color.dds'
SK5 = r'Textures\Actors\FSFFox\faces\chargen\male_fox_sk5_color.dds'
MOLES_LIGHT = bytes([150, 4, 24, 71])
NO_COLOR = b'\0\0\0\0'


@pytest.fixture(scope='module')
def world():
    data = game_data()
    order = load_order_for_plugin(data, 'FSF.esm')
    return dict(data=data, plugins=load_plugins(data, order))


def read_color(path):
    b = Path(path).read_bytes()
    assert b[84:88] == b'DX10' and struct.unpack_from('<I', b, 128)[0] == 29, 'R8G8B8A8_UNORM_SRGB'
    h, w = struct.unpack_from('<II', b, 12)
    return np.frombuffer(b, np.uint8, h * w * 4, 148).reshape(h, w, 4)[..., :3] / 255.0


def color_error(world, name, base, layers):
    got = facegen.composite_face(world['data'], base, layers, {})
    return np.abs(got / 255.0 - read_color(CK / f'{name}_Color.dds'))


def test_colour_layers_match_the_ck(world):
    e = color_error(world, '00005999', SK3, [(DERM05, NO_COLOR, 64), (COMPLEX04, NO_COLOR, 64)])
    assert e.max() < 0.01, e.max()


def test_mask_colour_matches_the_ck(world):
    e = color_error(world, '00003A09', SK5,
                    [(DERM05, NO_COLOR, 64), (COMPLEX04, NO_COLOR, 64), (DETAILS04, MOLES_LIGHT, 64)])
    assert e.max() < 0.01, e.max()


def test_a_mask_with_no_colour_paints_black(world):
    """A mask (an R8 `_mask`, no alpha) with NNAM 00000000 isn't invisible: it paints black through
    the mask, as the CK baked the hyena male preset's Complexion_Ears (2026-11-21)."""
    bare = facegen.composite_face(world['data'], SK3, [], {}).astype(int)
    got = facegen.composite_face(world['data'], SK3, [(DETAILS04, NO_COLOR, 64)], {}).astype(int)
    mask = facegen._load(world['data'], DETAILS04, {})[..., 0]
    assert mask.max() > 0.25, "the mask paints somewhere"
    assert np.abs(got - bare)[mask == 0].max() <= 1, "untouched outside the mask"
    full = mask >= mask.max() - 1e-6
    # Black laid on in linear light at the mask's strength (0.3 here): about 0.85 of the sRGB value.
    assert got[full].mean() < bare[full].mean() * 0.9, "darkened where the mask is strongest"


def test_a_facial_hairs_follicle_mask_is_painted_in_its_colour(world):
    """A facial hair's NAM3 names a mask in the BeardFollicleMask group; the NPC's FHCL names its
    colour in the Modulation group of the same name. The hyena male preset's ruff, in vanilla White.
    (Measured on the CK's bake of the preset, 2026-11-21: painted at the mask's strength, and the
    colour's first byte is the roughness laid on with it.) Stand-in records with vanilla's White:
    which parts carry a NAM3 is FSF's to change."""
    from fsftools.race_data import KIND_MODULATION, KIND_SIMPLE
    group = _Rec('SimpleGroup_BeardFollicleMask', LNAM=b'Ruff_mask\0', VNAM=b'ruff_mask.dds\0', NNAM=b'')
    colours = _Rec('Modulation_BeardFollicleMask', LNAM=b'White\0', NNAM=bytes.fromhex('c9868c8d'))
    avm = {(KIND_SIMPLE, 'BeardFollicleMask'): group, (KIND_MODULATION, 'BeardFollicleMask'): colours}
    head = _Rec('Head', PNAM=struct.pack('<I', 1))
    ruff = _Rec('Ruff', PNAM=struct.pack('<I', 4), NAM3=b'Ruff_mask\0')
    bare = _Rec('Ruff_NoMask', PNAM=struct.pack('<I', 4))
    npc = _Rec('Npc', FHCL=b'White\0')
    assert facegen.follicle_layers([head, ruff, bare], npc, avm) == [('ruff_mask.dds', bytes.fromhex('c9868c8d'))]
    assert facegen.follicle_layers([_Rec('Ruff_Unknown', PNAM=struct.pack('<I', 4), NAM3=b'Other\0')], npc, avm) == [], \
        "a key with no entry paints nothing"


class _Sub:
    def __init__(self, signature, data):
        self.signature, self.data = signature, data


class _Rec:
    """Just enough of a record for follicle_layers."""
    def __init__(self, editor_id, **subs):
        self.editor_id = editor_id
        self.subs = {k: _Sub(k, v) for k, v in subs.items()}
        self.subrecords = list(self.subs.values())

    def get_subrecord(self, sig):
        return self.subs.get(sig)


def test_a_follicle_mask_with_no_hair_colour_paints_black():
    """An NPC with no HCOL still gets its hair's scalp mask, in black: Bethesda's bake of
    male_as_md1_scan (000FA522) is 0,0,0 under its CroppedBang cap mask (measured 2026-11-22)."""
    from fsftools.race_data import KIND_MODULATION, KIND_SIMPLE
    group = _Rec('SimpleGroup_HairFollicleMask', LNAM=b'Cap\0', VNAM=b'cap_mask.dds\0', NNAM=b'')
    colours = _Rec('Modulation_HairFollicleMask', LNAM=b'Jet\0', NNAM=bytes.fromhex('c9020203'))
    avm = {(KIND_SIMPLE, 'HairFollicleMask'): group, (KIND_MODULATION, 'HairFollicleMask'): colours}
    hair = _Rec('Hair', PNAM=struct.pack('<I', 3), NAM3=b'Cap\0')
    assert facegen.follicle_layers([hair], _Rec('NoColour'), avm) == [('cap_mask.dds', b'\0\0\0\0')]
    assert facegen.follicle_layers([hair], _Rec('Jet', HCOL=b'Jet\0'), avm) == [
        ('cap_mask.dds', bytes.fromhex('c9020203'))]


def test_a_follicle_colour_with_no_roughness_byte_leaves_roughness():
    """Under the black of a missing hair colour the CK's roughness is the bare face's."""
    rough = np.full((2, 2), 128.0)
    mask = np.ones((2, 2, 3), np.float32)
    assert (facegen.follicle_rough(rough, [(mask, b'\0\0\0\0')]) == 128).all()


def test_a_follicle_mask_lays_its_roughness_on():
    rough = np.full((4, 4), 255.0)
    mask = np.zeros((4, 4, 3), np.float32)
    mask[0, 0], mask[1, 1] = 1.0, 0.5
    got = facegen.follicle_rough(rough, [(mask, bytes.fromhex('c9868c8d'))])
    assert got[0, 0] == pytest.approx(0xc9) and got[1, 1] == pytest.approx((255 + 0xc9) / 2)
    assert got[2, 2] == 255


def test_colour_file_has_the_cks_layout(tmp_path):
    img = np.zeros((1024, 1024, 3), np.uint8)
    path = tmp_path / 'x_Color.dds'
    facegen.write_color_dds(path, img)
    ck = (CK / '00005999_Color.dds').read_bytes()
    mine = path.read_bytes()
    assert len(mine) == len(ck)
    assert mine[:148] == ck[:148]


def decode_png(path, work):
    """A DDS's pixels through texconv, which reads every format the bake writes."""
    from PIL import Image
    import sf_texconv
    subprocess.run([sf_texconv.find_texconv(None), '-nologo', '-y', '-ft', 'png', '-f', 'R8G8B8A8_UNORM',
                    '-o', str(work), str(path)], capture_output=True, text=True)
    return np.asarray(Image.open(Path(work) / (Path(path).stem + '.png')).convert('RGB'), np.float64)


def test_morph_groups_pick_the_regions_maps(world, tmp_path):
    """At bake time this NPC had keys only in Chin and Ears. Those regions and the null area get the
    phenotype's maps; the rest get male_default's. Searching all 1024 region choices finds exactly this."""
    race = world['plugins'].get_record_by_edid('RACE', 'FSFFoxRace')
    fctp = next(s.data.rstrip(b'\0').decode() for s in race.subrecords if s.signature == 'FCTP')
    regions = ['Cheeks', 'Chin', 'Ears', 'Eyes', 'Forehead', 'Jaw', 'Mouth', 'Neck', 'Nose']
    maps = facegen.FaceMaps(world['data'], fctp, regions, tmp_path)
    keys = {'male_fox_md1_Chin': 1.0, 'male_fox_md1_Ears': 1.0, 'Strong': 0.3}
    weights = maps.region_weights('male_fox_md1', 'male_default', keys)
    assert set(weights) == {'male_fox_md1', 'male_default'}, 'body keys are not regions'
    rough = maps.blend('rough', weights)
    ck_rough = decode_png(CK / '00005999_rough.dds', tmp_path)
    assert np.abs(rough[..., 0] - ck_rough[..., 0]).mean() < 0.5
    normal = maps.blend('normal', weights)
    ck_normal = decode_png(CK / '00005999_Normal.dds', tmp_path)
    assert np.abs(normal[..., :2] - ck_normal[..., :2]).mean() < 5.5
    wrong = maps.blend('normal', maps.region_weights('male_fox_md1', 'male_default', {}))
    assert np.abs(normal[..., :2] - ck_normal[..., :2]).mean() < np.abs(wrong[..., :2] - ck_normal[..., :2]).mean() - 2


def test_identical_maps_blend_to_identical_bytes(world, tmp_path):
    """The fox's AO is the same for phenotype and default, so every NPC's AO should be one file."""
    race = world['plugins'].get_record_by_edid('RACE', 'FSFFoxRace')
    fctp = next(s.data.rstrip(b'\0').decode() for s in race.subrecords if s.signature == 'FCTP')
    regions = ['Cheeks', 'Chin', 'Ears', 'Eyes', 'Forehead', 'Jaw', 'Mouth', 'Neck', 'Nose']
    maps = facegen.FaceMaps(world['data'], fctp, regions, tmp_path)
    a = maps.blend('ao', maps.region_weights('male_fox_md1', 'male_default', {'male_fox_md1_Ears': 0.91}))
    b = maps.blend('ao', maps.region_weights('male_fox_md1', 'male_default', {'male_fox_md1_Nose': 0.17}))
    assert np.array_equal(a, b)


def test_a_fractional_key_shares_its_region_with_default(world, tmp_path):
    race = world['plugins'].get_record_by_edid('RACE', 'FSFFoxRace')
    fctp = next(s.data.rstrip(b'\0').decode() for s in race.subrecords if s.signature == 'FCTP')
    regions = ['Cheeks', 'Chin', 'Ears', 'Eyes', 'Forehead', 'Jaw', 'Mouth', 'Neck', 'Nose']
    maps = facegen.FaceMaps(world['data'], fctp, regions, tmp_path)
    half = maps.region_weights('male_fox_md1', 'male_default', {'male_fox_md1_Ears': 0.5})
    full = maps.region_weights('male_fox_md1', 'male_default', {'male_fox_md1_Ears': 1.0})
    none = maps.region_weights('male_fox_md1', 'male_default', {})
    ears = maps.masks['Ears'] > 0.9
    assert ears.any()
    a, b, c = (x['male_fox_md1'][ears].mean() for x in (none, half, full))
    assert a < b < c
    assert abs(b - (a + c) / 2) < 0.02
    total = sum(half.values())
    covered = sum(maps.masks.values()) > 0
    assert np.abs(total[covered] - 1).max() < 1e-4


def mesh_paths(nif_bytes):
    return [m.group(0).decode() for m in re.finditer(rb'[0-9a-f]{20}\\[0-9a-f]{20}', nif_bytes)]


def part_named(world, edid):
    hdpt = world['plugins'].get_record_by_edid('HDPT', edid)
    assert hdpt is not None, edid
    return hdpt


def shape_names(nif_bytes):
    """Shape names in the order the CK wrote them, from the block list."""
    return facegen.read_nif(nif_bytes).shape_names()


def without_shape_flag(data):
    """The nif with the one bit the CK sets on some shapes and not others cleared."""
    out = bytearray(data)
    nif = facegen.read_nif(data)
    o = data.index(nif.blocks[0][1])
    for kind, block in nif.blocks:
        if kind == 'BSGeometry':
            at = o + facegen._geometry_fields(block)['flags']
            out[at:at + 4] = struct.pack('<I', struct.unpack_from('<I', data, at)[0] & ~0x00080000)
        o += len(block)
    return bytes(out)


def mesh_sections(data):
    return facegen.split_mesh(data)


def test_unmorphed_part_stays_close_to_the_ck(world):
    """An eye has no morphs, but the CK still nudges its vertices a little."""
    source = facegen.load_part_source(world['data'], part_named(world, 'FSFCanine_Male_RightEye'), world['plugins'])
    baked = facegen.bake_mesh(source, {'male_fox_md1_Ears': 1.0})
    ck = (CK / 'eye_M01.mesh').read_bytes()
    mine, theirs = mesh_sections(baked.data), mesh_sections(ck)
    assert len(baked.data) == len(ck)
    for section in ('head', 'uv', 'weights', 'tail'):
        assert mine[section] == theirs[section], section
    assert np.abs(np.frombuffer(mine['pos'], '<i2').astype(int) - np.frombuffer(theirs['pos'], '<i2').astype(int)).max() <= 10
    for section in ('normals', 'tangents'):
        assert not (np.frombuffer(mine[section], '<u4') >> 30).any(), 'w cleared, as the CK does'
    assert baked.name.replace('\\', '') == __import__('hashlib').sha1(baked.data).hexdigest()


def run_cli(out_dir, *only):
    plugin = out_dir / 'test.esm'
    cmd = [sys.executable, str(ROOT / 'sf_furrify.py'), '--data', str(game_data()), '--plugin', 'FSF.esm', '--out', str(plugin),
           '--scheme', str(SCHEME), '--builtin', str(BUILTIN),
           '--races', str(RACES), '--facegen', str(out_dir / 'mod')]
    for n in only:
        cmd += ['--only', n]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)


@pytest.fixture(scope='module')
def baked_run():
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        run = run_cli(out, 'Companion_SamCoe', 'FC_Neon_GenericCustomerM01', 'FC_Neon_GenericCustomerM02',
                      'Companion_SarahMorgan')
        assert run.returncode == 0, run.stdout + run.stderr
        yield out / 'mod', run.stdout


def geom_dir(mod):
    return mod / 'Meshes' / 'Actors' / 'Character' / 'FaceGenData' / 'FaceGeom' / 'Starfield.esm'


def tex_dir(mod):
    return mod / 'Textures' / 'Actors' / 'Character' / 'FaceCustomization' / 'Starfield.esm'


def test_cli_writes_the_cks_file_set(baked_run):
    mod, _ = baked_run
    for name in ('00005999', '00003A09', '00003A0A'):
        assert (geom_dir(mod) / f'{name}.NIF').exists(), name
        for suffix, ck_name in (('Color', '_Color'), ('Normal', '_Normal'), ('ao', '_ao'), ('rough', '_rough')):
            path = tex_dir(mod) / f'{name}_{suffix}.dds'
            assert path.stat().st_size == (CK / f'00005999{ck_name}.dds').stat().st_size, path.name
            assert path.read_bytes()[:128] == (CK / f'00005999{ck_name}.dds').read_bytes()[:128], path.name


def test_cli_meshes_exist_and_differ_only_where_morphed(baked_run):
    mod, _ = baked_run
    paths = {}
    for name in ('00005999', '00003A09'):
        nif = (geom_dir(mod) / f'{name}.NIF').read_bytes()
        paths[name] = dict(zip(shape_names(nif), mesh_paths(nif)))
        for mesh in paths[name].values():
            assert (mod / 'Geometries' / (mesh + '.mesh')).exists(), mesh
    a, b = paths['00005999'], paths['00003A09']
    assert a['FSFCanine_Male_Head'] != b['FSFCanine_Male_Head'], 'different morph values'
    assert a['FSFCanine_Male_RightEye'] == b['FSFCanine_Male_RightEye'], 'eyes have no morphs'


def test_cli_says_when_it_cannot_bake_an_npc(baked_run):
    """Sarah is female; until the race's face tones list her phenotype, a bake would be black."""
    mod, log = baked_run
    baked = (geom_dir(mod) / '00005983.NIF').exists()
    assert baked or ('Companion_SarahMorgan' in log and 'FSFFoxFaceSkinTones' in log), log

def test_shared_maps_leave_links_for_the_mod_manager(tmp_path, monkeypatch):
    """NTFS allows 1024 names per file, and a hardlink deploy adds one per staged name, so a group sharing one
    file must stay at half that or less."""
    monkeypatch.setattr(facegen, 'LINKS_PER_FILE', 3)
    cache = {}
    for i in range(10):
        facegen._link_or_write(cache, tmp_path / f'{i:08X}_ao.dds', lambda p: Path(p).write_bytes(b'same'))
    files = sorted(tmp_path.glob('*_ao.dds'))
    assert len(files) == 10
    assert all(f.read_bytes() == b'same' for f in files)
    assert max(f.stat().st_nlink for f in files) == 3
    assert not list(tmp_path.glob('*.tmp'))


def test_link_cap_leaves_room_for_a_deploy():
    assert facegen.LINKS_PER_FILE * 2 <= 1024
