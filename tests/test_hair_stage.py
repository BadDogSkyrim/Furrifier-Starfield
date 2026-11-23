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


@pytest.fixture(scope='module')
def fitted(tmp_path_factory):
    """One --hair-only run, shared by the tests below, which run in order: rerun, then exclude."""
    if not Path(tt.SF_ASSETS).is_dir():
        pytest.fail(f'asset folder missing: {tt.SF_ASSETS}')
    tmp = tmp_path_factory.mktemp('hair')
    out = tmp / 'mod'
    log = hair_only(out, races_with(tmp, ['Human_*_Hair_Cropped', 'Human_*_Hair_Flat_Top']))
    return tmp, out, log


def test_hair_only_fits_the_included_hairs(fitted):
    _, out, log = fitted
    assert '4 refitted' in log, log
    plugin, recs = records(out / 'FSFHair.esm')
    assert plugin.header.masters == ['Starfield.esm', 'FSF.esm']
    for edid in ('FSFCanine_Female_Hair_Cropped', 'FSFCanine_Male_Hair_Cropped',
                 'FSFCanine_Female_Hair_Flat_Top', 'FSFCanine_Male_Hair_Flat_Top'):
        hdpt = recs[('HDPT', edid)]
        model = hdpt.get_subrecord('MODL').data.rstrip(b'\0').decode()
        assert (out / 'Meshes' / model.replace('\\', '/')).is_file(), model
        assert ('MRPH', f'MORPH_{edid}') in recs
        mrph = recs[('MRPH', f'MORPH_{edid}')]
        for sig in ('TCMP', 'TMPP'):
            folder = mrph.get_subrecord(sig).data.rstrip(b'\0').decode().replace('\\', '/')
            assert (out / folder / 'morph.dat').is_file(), folder
    races = recs[('FLST', 'FSFCanine_HairRaces')]
    assert len(races.get_subrecords('LNAM')) == 2     # fox and hyena share the canine head
    assert (out / 'FSFTools' / 'hair_fit' / 'FSFHair.json').is_file()


def test_a_rerun_fits_nothing_and_keeps_formids(fitted):
    tmp, out, _ = fitted
    before = {k: int(r.form_id.value) for k, r in records(out / 'FSFHair.esm')[1].items()}
    log = hair_only(out, tmp / 'races')
    assert '0 refitted, 4 up to date' in log, log
    after = {k: int(r.form_id.value) for k, r in records(out / 'FSFHair.esm')[1].items()}
    assert after == before


def test_an_excluded_hair_loses_its_records(fitted):
    tmp, out, _ = fitted
    before = {k: int(r.form_id.value) for k, r in records(out / 'FSFHair.esm')[1].items()}
    again = tmp / 'again'
    again.mkdir()
    log = hair_only(out, races_with(again, ['Human_*_Hair_Cropped', 'Human_*_Hair_Flat_Top'], ['*Flat_Top']))
    assert '0 refitted, 2 up to date' in log, log
    _, recs = records(out / 'FSFHair.esm')
    assert ('HDPT', 'FSFCanine_Female_Hair_Flat_Top') not in recs
    assert ('MRPH', 'MORPH_FSFCanine_Male_Hair_Flat_Top') not in recs
    assert int(recs[('HDPT', 'FSFCanine_Female_Hair_Cropped')].form_id.value) == \
        before[('HDPT', 'FSFCanine_Female_Hair_Cropped')]
