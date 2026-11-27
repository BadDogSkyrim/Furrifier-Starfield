"""The furrifier's hair stage (sf_furrify --hair-only): which hairs, the records, reruns."""
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fsftools.hair_stage import fitted_edid, race_list_edid, wants  # noqa: E402
from tests import tt  # noqa: E402
from tests.fsfdata import BUILTIN, RACES, SCHEME, game_data  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class R:
    def __init__(self, edid):
        self.editor_id = edid


def test_wants_takes_globs_in_any_case():
    assert wants('Human_Female_Hair_Bob', [], [])
    assert wants('Human_Female_Hair_Bob', ['human_*_hair_b*'], [])
    assert not wants('Human_Female_Hair_Mullet', ['Human_*_Hair_B*'], [])
    assert not wants('Human_Female_Hair_Bob', [], ['*_Bob'])
    assert not wants('Human_Female_Hair_Bob', ['*'], ['*bob']), 'exclude wins'


def test_fitted_names():
    assert fitted_edid('Human_Female_Hair_Bob', 'FSFCanine') == 'FSFCanine_Female_Hair_Bob'
    assert fitted_edid('ModHair_Spiky', 'FSFCanine') == 'FSFCanine_ModHair_Spiky'


def test_race_list_is_named_for_its_races_unless_all():
    fox, hyena = R('FSFFoxRace'), R('FSFHyenaRace')
    assert race_list_edid('FSFCanine', [hyena, fox], [fox, hyena]) == 'FSFCanine_HairRaces'
    assert race_list_edid('FSFCanine', [fox], [fox, hyena]) == 'FSFCanine_HairRaces_FSFFoxRace'


def test_a_companion_is_found_where_the_part_is_not(tmp_path):
    """A loose nif in Data without its _facebones companion: the companion comes from the assets."""
    from fsftools.hair_stage import Assets
    data, assets = tmp_path / 'Data', tmp_path / 'assets'
    (data / 'Meshes/Actors/Hair').mkdir(parents=True)
    (assets / 'Meshes/actors/hair').mkdir(parents=True)
    (data / 'Meshes/Actors/Hair/Tail_F.nif').write_bytes(b'loose')
    (assets / 'Meshes/actors/hair/tail_f.nif').write_bytes(b'vanilla')
    (assets / 'Meshes/actors/hair/tail_f_facebones.nif').write_bytes(b'vanilla')
    found = Assets(data, assets).companion('Actors\\Hair\\Tail_F.nif')
    assert found is not None and found.read_bytes() == b'vanilla'
    assert Assets(data, None).companion('Actors\\Hair\\Tail_F.nif') is None


def races_with(tmp: Path, include, exclude=()):
    """The test races with a [hair] table; crowd manifests made absolute so the copies work."""
    folder = tmp / 'races'
    folder.mkdir(exist_ok=True)
    for src in RACES.glob('*.toml'):
        text = src.read_text(encoding='utf-8')
        here = src.parent
        text = re.sub(r'"(\.\./[^"]+)"', lambda m, here=here: f'"{(here / m.group(1)).resolve().as_posix()}"', text)
        text += f'\n[hair]\ninclude = {list(include)!r}\nexclude = {list(exclude)!r}\n'.replace("'", '"')
        (folder / src.name).write_text(text, encoding='utf-8')
    return folder


def hair_only(out: Path, races: Path):
    cmd = [sys.executable, str(ROOT / 'sf_furrify.py'), '--data', str(game_data()), '--plugin', 'FSF.esm',
           '--out', str(out), '--scheme', str(SCHEME), '--builtin', str(BUILTIN), '--races', str(races),
           '--assets', tt.SF_ASSETS, '--only', 'NoSuchNPC', '--hair-only']
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout


def records(path: Path):
    from esplib import Plugin
    Plugin._load_string_tables = lambda self: None
    p = Plugin.load(str(path))
    return p, {(r.signature, r.editor_id): r for r in p}


HAIRS = ['Human_*_Hair_Cropped', 'Human_*_Hair_Even_Buzz_Back', 'Human_*_Hair_Flat_Top']


@pytest.fixture(scope='module')
def fitted(tmp_path_factory):
    """One --hair-only run, shared by the tests below, which run in order: rerun, then exclude."""
    if not Path(tt.SF_ASSETS).is_dir():
        pytest.fail(f'asset folder missing: {tt.SF_ASSETS}')
    tmp = tmp_path_factory.mktemp('hair')
    out = tmp / 'mod'
    log = hair_only(out, races_with(tmp, HAIRS))
    return tmp, out, log


def test_hair_only_fits_the_included_hairs(fitted):
    _, out, log = fitted
    assert '6 refitted' in log, log
    plugin, recs = records(out / 'FSFHair.esm')
    assert plugin.header.masters == ['Starfield.esm', 'FSF.esm']
    for edid in ('FSFCanine_Female_Hair_Cropped', 'FSFCanine_Male_Hair_Cropped',
                 'FSFCanine_Female_Hair_Flat_Top', 'FSFCanine_Male_Hair_Flat_Top'):
        hdpt = recs[('HDPT', edid)]
        assert hdpt.get_subrecord('NAM3') is None, "a scalp mask is drawn for the human face's UVs"
        model = hdpt.get_subrecord('MODL').data.rstrip(b'\0').decode()
        assert (out / 'Meshes' / model.replace('\\', '/')).is_file(), model
        assert ('MRPH', f'MORPH_{edid}') in recs
        mrph = recs[('MRPH', f'MORPH_{edid}')]
        for sig in ('TCMP', 'TMPP'):
            folder = mrph.get_subrecord(sig).data.rstrip(b'\0').decode().replace('\\', '/')
            assert (out / folder / 'morph.dat').is_file(), folder
    from pyn.sf_morph import MorphFile
    for (sig, edid), mrph in recs.items():      # every morph file named exists and has keys
        for sr in mrph.subrecords if sig == 'MRPH' else []:
            if sr.signature in ('TCMP', 'TMPP'):
                dat = out / sr.data.rstrip(b'\0').decode().replace('\\', '/') / 'morph.dat'
                assert dat.is_file() and MorphFile.from_bytes(dat.read_bytes()).morph_names, (edid, dat)
    races = recs[('FLST', 'FSFCanine_HairRaces')]
    assert len(races.get_subrecords('LNAM')) == 2     # fox and hyena share the canine head
    assert (out / 'FSFTools' / 'hair_fit' / 'FSFHair.json').is_file()


def own_ids(plugin):
    """{(signature, EDID): object ID} of the records a plugin defines itself."""
    own = len(plugin.header.masters)
    return {(r.signature, r.editor_id): int(r.form_id.value) & 0xFFFFFF for r in plugin
            if int(r.form_id.value) >> 24 == own}


def references_resolve(plugin):
    """Every RNAM/MNAM/HNAM/LNAM naming the plugin itself lands on one of its own records."""
    own = len(plugin.header.masters)
    mine = {int(r.form_id.value) for r in plugin if int(r.form_id.value) >> 24 == own}
    bad = []
    for r in plugin:
        for sr in r.subrecords:
            if sr.signature in ('RNAM', 'MNAM', 'HNAM', 'LNAM') and len(sr.data) == 4:
                v = int.from_bytes(sr.data, 'little')
                if v >> 24 == own and v not in mine:
                    bad.append((r.editor_id, sr.signature, f'{v:08X}'))
    return bad


def test_own_formids_are_light(fitted):
    """The hair plugin is light: its own records must be 800-FFF. They were numbered from after
    the highest FormID in the plugin, overrides included -- vanilla's chargen lists, 3D9B0 -- so
    they came out 3D9B1 and up, which the game and the CK read as other records (11-26: an NPC's
    hair was a REFR in xEdit, and no hair showed in the CK)."""
    _, out, _ = fitted
    plugin, _ = records(out / 'FSFHair.esm')
    ids = own_ids(plugin)
    assert ids and all(0x800 <= v <= 0xFFF for v in ids.values()), \
        sorted(f'{v:06X}' for v in ids.values())
    assert 0x800 <= plugin.header.next_object_id <= 0x1000


CHARGEN_LISTS = {'MALE': 0x3D9AF, 'FEMALE': 0x3D9B0}     # HeadPartsChargenOptionsMale/Female


def chargen_list(recs, fid):
    found = [r for (sig, _), r in recs.items() if sig == 'FLST' and int(r.form_id.value) == fid]
    assert len(found) == 1, f'{fid:08X} overridden {len(found)} times'
    return [int.from_bytes(s.data[:4], 'little') for s in found[0].get_subrecords('LNAM')]


def named(plugin, values):
    """FormIDs in a plugin as (the file each belongs to, object ID)."""
    masters = list(plugin.header.masters) + [plugin.file_path.name]
    return [(masters[v >> 24].lower(), v & 0xFFFFFF) for v in values]


def test_fitted_hairs_are_chargen_options(fitted):
    """The chargen lists offer what the player plugin's do, then each sex's fitted hairs. The test
    player plugins make the same changes to vanilla's (FSF.esm's eyes and ruffs in, the human male
    eyes out), so the hair plugin's list is either one's in its order. No player plugin is a master:
    only one of them is active."""
    from esplib import Plugin
    _, out, _ = fitted
    plugin, recs = records(out / 'FSFHair.esm')
    assert not [m for m in plugin.header.masters if m.lower().startswith('fsfplayer')]
    for sex, fid in CHARGEN_LISTS.items():
        lists = []
        for name in ('Starfield.esm', 'FSFPlayer_FOX.esm', 'FSFPlayer_HYENA.esm'):
            src = Plugin.load(str(game_data() / name), only_signatures=['FLST'])
            rec = next(r for r in src if int(r.form_id.value) == fid)
            lists.append(named(src, [int.from_bytes(s.data[:4], 'little') for s in rec.get_subrecords('LNAM')]))
        vanilla, fox, hyena = lists
        assert fox == hyena and set(fox) != set(vanilla)
        mine = [int(recs[('HDPT', f'FSFCanine_{sex.capitalize()}_Hair_{h}')].form_id.value)
                for h in ('Cropped', 'Even_Buzz_Back', 'Flat_Top')]
        got = named(plugin, chargen_list(recs, fid))
        assert set(got) == set(fox) | set(named(plugin, mine)), 'extra parts come with their hair'
        assert got[-3:] == named(plugin, mine)


def test_extra_parts_are_fitted_with_their_hair(fitted):
    """Even_Buzz_Back's front part is fitted too, and the fitted hair names the fitted part."""
    _, out, log = fitted
    assert 'Even_Buzz' not in log, log          # nothing skipped
    _, recs = records(out / 'FSFHair.esm')
    for sex in ('Female', 'Male'):
        hair = recs[('HDPT', f'FSFCanine_{sex}_Hair_Even_Buzz_Back')]
        part = recs[('HDPT', f'FSFCanine_{sex}_Hair_Even_Buzz_Front')]
        assert [int.from_bytes(s.data, 'little') for s in hair.get_subrecords('HNAM')] == [int(part.form_id.value)]
        assert part.get_subrecord('RNAM').data == hair.get_subrecord('RNAM').data
        model = part.get_subrecord('MODL').data.rstrip(b'\0').decode().replace('\\', '/')
        assert (out / 'Meshes' / model).is_file(), model
        assert (out / 'Meshes' / model).with_name(Path(model).stem.lower() + '_facebones.nif').is_file()
        mrph = recs[('MRPH', f'MORPH_FSFCanine_{sex}_Hair_Even_Buzz_Front')]
        assert int.from_bytes(part.get_subrecord('MNAM').data, 'little') == int(mrph.form_id.value)


def test_a_rerun_fits_nothing_and_keeps_formids(fitted):
    tmp, out, _ = fitted
    before = {k: int(r.form_id.value) for k, r in records(out / 'FSFHair.esm')[1].items()}
    log = hair_only(out, tmp / 'races')
    assert '0 refitted, 6 up to date' in log, log
    after = {k: int(r.form_id.value) for k, r in records(out / 'FSFHair.esm')[1].items()}
    assert after == before


def test_an_excluded_hair_loses_its_records(fitted):
    tmp, out, _ = fitted
    before = {k: int(r.form_id.value) for k, r in records(out / 'FSFHair.esm')[1].items()}
    again = tmp / 'again'
    again.mkdir()
    log = hair_only(out, races_with(again, HAIRS, ['*Flat_Top']))
    assert '0 refitted, 4 up to date' in log, log
    _, recs = records(out / 'FSFHair.esm')
    assert ('HDPT', 'FSFCanine_Female_Hair_Flat_Top') not in recs
    assert ('MRPH', 'MORPH_FSFCanine_Male_Hair_Flat_Top') not in recs
    assert int(recs[('HDPT', 'FSFCanine_Female_Hair_Cropped')].form_id.value) == \
        before[('HDPT', 'FSFCanine_Female_Hair_Cropped')]
    ids = chargen_list(recs, CHARGEN_LISTS['FEMALE'])
    assert int(recs[('HDPT', 'FSFCanine_Female_Hair_Cropped')].form_id.value) in ids
    assert before[('HDPT', 'FSFCanine_Female_Hair_Flat_Top')] not in ids, 'a dropped hair leaves chargen'


def test_a_hair_added_on_a_rerun_is_light(fitted):
    """Flat_Top, dropped by the test above, comes back on a rerun: its new records are numbered
    800-FFF, though the plugin now overrides vanilla's chargen lists (3D9AF, 3D9B0)."""
    tmp, out, _ = fitted
    third = tmp / 'third'
    third.mkdir()
    hair_only(out, races_with(third, HAIRS))
    plugin, recs = records(out / 'FSFHair.esm')
    assert ('HDPT', 'FSFCanine_Female_Hair_Flat_Top') in recs
    ids = own_ids(plugin)
    assert all(0x800 <= v <= 0xFFF for v in ids.values()), sorted(f'{v:06X}' for v in ids.values())
    assert references_resolve(plugin) == []


def test_a_plugin_numbered_past_the_light_range_is_repaired(fitted):
    """A hair plugin written before the fix -- own records 3D9B1 and up, next object ID after
    them -- is renumbered into 800-FFF on the next run, its references following."""
    from esplib import Plugin
    from fsftools.plugin_writer import _patch_sf_light_flag
    from esplib.utils import FormID
    tmp, out, _ = fitted
    path = out / 'FSFHair.esm'
    Plugin._load_string_tables = lambda self: None
    plugin = Plugin.load(str(path))
    own = len(plugin.header.masters) << 24
    moved = {}
    for i, r in enumerate(sorted((r for r in plugin if int(r.form_id.value) & 0xFF000000 == own),
                                 key=lambda r: int(r.form_id.value))):
        moved[int(r.form_id.value)] = own | (0x3D9B1 + i)
        r.form_id = FormID(moved[int(r.form_id.value)])
    for r in plugin:
        for sr in r.subrecords:
            if sr.signature in ('RNAM', 'MNAM', 'HNAM', 'LNAM') and len(sr.data) == 4:
                v = int.from_bytes(sr.data, 'little')
                if v in moved:
                    sr.data = moved[v].to_bytes(4, 'little')
    plugin.header.next_object_id = 0x3D9B1 + len(moved)
    plugin.save(str(path))
    _patch_sf_light_flag(path)
    broken, _ = records(path)
    assert max(own_ids(broken).values()) > 0xFFF and not references_resolve(broken)

    light = tmp / 'light'
    light.mkdir(exist_ok=True)
    log = hair_only(out, races_with(light, HAIRS, ['*Flat_Top']))    # as the exclude test left it
    assert 'renumbered into the light range' in log, log
    plugin, recs = records(path)
    ids = own_ids(plugin)
    assert all(0x800 <= v <= 0xFFF for v in ids.values()), sorted(f'{v:06X}' for v in ids.values())
    assert len(set(ids.values())) == len(ids)
    assert references_resolve(plugin) == []
    assert 0x800 <= plugin.header.next_object_id <= 0x1000
    hair = recs[('HDPT', 'FSFCanine_Female_Hair_Cropped')]
    assert int.from_bytes(hair.get_subrecord('MNAM').data, 'little') == \
        int(recs[('MRPH', 'MORPH_FSFCanine_Female_Hair_Cropped')].form_id.value)
