"""Crowd hair (sf_furrify --hair --keep-hair with furry crowds): the fitted nifs and the lists that
give each breed its own. Real game data: vanilla's crowd hair onto the FSF snapshot's crowd heads."""
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fsftools import hair_fit  # noqa: E402
from tests import tt  # noqa: E402
from tests.fsfdata import BUILTIN, RACES, game_data  # noqa: E402
from tests.test_crowds import Output, scheme  # noqa: E402

ARMORS = ['CrowdHair_Cropped_NOTPLAYABLE', 'CrowdHair_Short_Ponytail_NOTPLAYABLE',
          'Clothes_Crowd_Hat_03_Beanie_NOTPLAYABLE']
FOX = 'FSFFoxRace'
HEADS = {'red_fox': ('Crowd_Fox_md1', 'crowdf_fox_01')}     # the test races' only crowd breed


def races_taking(tmp: Path, armors):
    """The test races, taking one chargen hair and the named crowd armors."""
    folder = tmp / 'races'
    folder.mkdir(exist_ok=True)
    for src in RACES.glob('*.toml'):
        text = src.read_text(encoding='utf-8')
        here = src.parent
        text = re.sub(r'"(\.\./[^"]+)"', lambda m, here=here: f'"{(here / m.group(1)).resolve().as_posix()}"', text)
        text += ('\n[hair]\ninclude = ["Human_*_Hair_Cropped"]\n'
                 f'crowd_include = {list(armors)!r}\n').replace("'", '"')
        (folder / src.name).write_text(text, encoding='utf-8')
    return folder


def run_furrifier(work: Path, races: Path, assets=True):
    (work / 'scheme.toml').write_text(scheme((FOX, 100)), encoding='utf-8')
    out = work / 'mod' / 'crowdhair.esm'
    cmd = [sys.executable, str(ROOT / 'sf_furrify.py'), '--data', str(game_data()), '--plugin', 'FSF.esm',
           '--out', str(out), '--scheme', str(work / 'scheme.toml'), '--builtin', str(BUILTIN),
           '--races', str(races), '--only', 'NoSuchNPC', '--crowd-test', '--hair', '--keep-hair']
    if assets:
        cmd += ['--assets', tt.SF_ASSETS]
    return out, subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)


def furrify(work: Path, races: Path):
    out, proc = run_furrifier(work, races)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return out, proc.stdout


def test_without_assets_it_says_to_give_them(tmp_path):
    """The vanilla crowd heads are in a BA2. Without --assets the crowd hair fit stops with an
    error saying so, not a traceback (Bad Dog's run 11-26 died in a FileNotFoundError)."""
    _, proc = run_furrifier(tmp_path, races_taking(tmp_path, ARMORS), assets=False)
    said = proc.stdout + proc.stderr
    assert proc.returncode == 2, said
    assert 'Traceback' not in said, said
    error = next((line for line in said.splitlines() if line.startswith('ERROR:')), '')
    assert 'crowd_head' in error and 'give --assets' in error, said


@pytest.fixture(scope='module')
def fitted(tmp_path_factory):
    from fsftools.plugin_loader import load_order_for_plugin, load_plugins
    if not Path(tt.SF_ASSETS).is_dir():
        pytest.fail(f'asset folder missing: {tt.SF_ASSETS}')
    work = tmp_path_factory.mktemp('crowd_hair')
    races = races_taking(work, ARMORS)
    out, log = furrify(work, races)
    game = load_plugins(game_data(), load_order_for_plugin(game_data(), 'FSF.esm'))
    return work, races, out, log, Output(out, game)


def model(rec, sig):
    sr = rec.get_subrecord(sig)
    return sr.data.rstrip(b'\0').decode('cp1252') if sr is not None else None


def test_each_breed_s_first_heads_get_every_taken_nif(fitted):
    """For each sex's head: Cropped, the short ponytail and its tie, and the beanie."""
    _, _, out, log, _ = fitted
    assert 'Crowd hair: 8 nifs for 2 heads (8 refitted, 0 up to date)' in log, log
    mod = out.parent
    for male, female in HEADS.values():
        for head, nif in ((male, 'Cropped_M_CROWD.nif'), (female, 'Cropped_F_CROWD.nif'),
                          (male, 'Outfit_Crowd_Hat_Beanie_01_M_CROWD.nif'),
                          (female, 'Short_Ponytail_F_HairTie_CROWD.nif')):
            path = mod / 'Meshes/Actors/FSFFox_Crowd/Hair' / head / nif
            assert path.is_file(), path
            for name in hair_fit.nif_mesh_names(path.read_bytes()):
                assert (mod / 'Geometries' / (name.replace('\\', '/') + '.mesh')).is_file(), (nif, name)


def test_the_ears_and_arms_are_cut_from_the_fit(fitted):
    """Fitted to the whole fox crowd head, a hair rides out over the ears by 5 cm. Without them it
    moves to the fox's skull: some, not that much."""
    _, _, out, _, _ = fitted
    vanilla = Path(tt.SF_ASSETS)
    van = hair_fit.load_lods(vanilla / 'Meshes/Actors/human_crowd/Mesh/Male/hairs/cropped_m_crowd.nif',
                             lambda n: vanilla / 'Geometries' / (n + '.mesh'))[0]
    mod = out.parent
    fit = hair_fit.load_lods(mod / 'Meshes/Actors/FSFFox_Crowd/Hair/Crowd_Fox_md1/Cropped_M_CROWD.nif',
                             lambda n: mod / 'Geometries' / (n + '.mesh'))[0]
    moved = np.linalg.norm(fit.positions - van.positions, axis=1)
    assert 0.001 < moved.max() < 0.03, moved.max()


def test_each_breed_wears_its_own_hair_list(fitted):
    _, _, _, _, output = fitted
    mix = output.by_edid('LVLI', f'FSF_LL_Crowd_{FOX}_Heads_Hairs_Hats_Akila')
    breeds = output.entries(mix)
    assert {b.editor_id for b in breeds} == {f'FSF_LL_Crowd_{FOX}_{b}_Heads_Hairs_Hats_Akila' for b in HEADS}
    lists = {}
    for both in breeds:
        assert both.get_subrecord('LVLF').data[0] & 4, 'Use All'
        heads, hairs = output.entries(both)
        breed = both.editor_id[len(f'FSF_LL_Crowd_{FOX}_'):-len('_Heads_Hairs_Hats_Akila')]
        assert heads.editor_id == f'FSF_LL_Crowd_Heads_{FOX}_{breed}'
        lists[breed] = hairs
    for breed, (male, female) in HEADS.items():
        armors = output.entries(lists[breed])
        assert sorted(a.editor_id for a in armors) == sorted(
            f'FSF_{e.removesuffix("_NOTPLAYABLE")}_{male}_{female}_NOTPLAYABLE' for e in ARMORS)
        for armor in armors:
            for addon in output.addons(armor):
                assert addon.editor_id.startswith('FSF_AA_')
                assert model(addon, 'MOD2').startswith(f'Actors\\FSFFox_Crowd\\Hair\\{male}\\'), addon.editor_id
                assert model(addon, 'MOD3').startswith(f'Actors\\FSFFox_Crowd\\Hair\\{female}\\'), addon.editor_id
    ponytail = next(a for a in output.entries(lists['red_fox']) if 'Short_Ponytail' in a.editor_id)
    assert len(output.addons(ponytail)) == 2, 'the hair and its tie'


def test_a_list_without_hats_gets_no_hat(fitted):
    _, _, _, _, output = fitted
    both = output.by_edid('LVLI', f'FSF_LL_Crowd_{FOX}_red_fox_Heads_Thin_Hairs_NoHats')
    _, hairs = output.entries(both)
    assert not [a for a in output.entries(hairs) if 'Hat' in a.editor_id]
    assert len(output.entries(hairs)) == 2


def test_a_rerun_fits_nothing(fitted):
    work, races, _, _, _ = fitted
    _, log = furrify(work, races)              # the same output folder again
    assert 'Crowd hair: 8 nifs for 2 heads (0 refitted, 8 up to date)' in log, log



def test_the_cut_head_keeps_its_scalp():
    """The crowd head loses its arms and its ears fold down, as HideEar folds the race's own head's,
    but the scalp stays whole: a hair's rays all find it. (HideEar moves the scalp round the ears a
    little, so the vertices it moves can't simply be dropped: that left a quarter of them missing.)"""
    from fsftools.crowd_hair import cut_head
    from fsftools.hair_stage import Assets, load_head, race_heads
    from fsftools.plugin_loader import load_order_for_plugin, load_plugins
    data = game_data()
    plugins = load_plugins(data, load_order_for_plugin(data, 'FSF.esm'))
    files = Assets(data, Path(tt.SF_ASSETS))
    own = load_head(plugins, files, race_heads(plugins, plugins.get_record_by_edid('RACE', FOX))['FEMALE'],
                    lambda *a: None)
    variant = r'Actors\FSFFox_Crowd\Mesh\Female\Variants\crowdf_fox_01_sk0_d4c3e3.nif'
    shape = hair_fit.load_lods(files.find(Path('Meshes') / variant), files.mesh, count=1)[0]
    head, _ = cut_head(shape, own)
    used = np.unique(head.tris)
    assert head.verts[used, 0].min() > -0.3, 'no arms'
    assert head.verts[used, 0].max() < own.head.verts[:, 0].max() + 0.01, 'the ears are folded down'
    hair = hair_fit.load_lods(files.find(Path('Meshes/Actors/human_crowd/Mesh/Female/hairs/Cropped_Bang_F_CROWD.nif')),
                              files.mesh, count=1)[0]
    p = hair.to_bone(hair.positions)
    hits = hair_fit.radial_hits(head, p / np.linalg.norm(p, axis=1)[:, None])
    assert np.isnan(hits).mean() < 0.01, f'{np.isnan(hits).mean():.0%} of the rays miss'
