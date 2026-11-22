"""Skin tones per sex: the two sexes of a race can have different numbers of tones."""
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from fsfdata import BUILTIN, RACES, SCHEME, game_data  # noqa: E402
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from fsftools.config import BreedDef, RaceConfig, SchemeConfig, load_races  # noqa: E402
from fsftools.crowd_builder import _pair_breed  # noqa: E402
from fsftools.probability import RaceAssigner  # noqa: E402


def race(**kw):
    return RaceConfig('R', 'FSF.esm', skin_tones=list(range(11)), skin_tones_female=list(range(6)), **kw)


def test_race_tones_differ_by_sex():
    r = race()
    assert r.tones_for('MALE') == list(range(11))
    assert r.tones_for('FEMALE') == list(range(6))
    assert r.tones_for('female') == list(range(6)), "the crowd manifests spell it in lower case"


def test_one_list_serves_both_sexes():
    r = RaceConfig('R', 'FSF.esm', skin_tones=[0, 1])
    assert r.tones_for('MALE') == [0, 1]
    assert r.tones_for('FEMALE') == [0, 1]


def test_a_breed_narrows_each_sex():
    both = BreedDef('arctic', skin_tone_override=[0, 1])
    apart = BreedDef('fennec', skin_tone_override=[11, 12], skin_tone_override_female=[3, 4])
    r = race(breeds=[both, apart])
    assert r.tones_for('FEMALE', both) == [0, 1]
    assert r.tones_for('MALE', apart) == [11, 12]
    assert r.tones_for('FEMALE', apart) == [3, 4]


def test_the_assigner_stays_in_the_sex_s_tones():
    r = race(breeds=[BreedDef('red', 100)])
    assigner = RaceAssigner(SchemeConfig(), {'R': r})
    females = {assigner.assign_skin_tone(f'NPC{i}', 'R', 'red', 'FEMALE') for i in range(300)}
    males = {assigner.assign_skin_tone(f'NPC{i}', 'R', 'red', 'MALE') for i in range(300)}
    assert females == set(range(6))
    assert males == set(range(11))


def variant(name, tone):
    return {'name': name, 'tone': tone, 'nifs': {'average': 'a', 'thin': 't', 'overweight': 'o'}}


def test_crowd_heads_keep_to_their_own_sex_s_tones():
    """A tone only the other sex may use isn't a head to pair, even if one was baked."""
    breed = BreedDef('red', 100, crowd_heads=['*'])
    r = RaceConfig('R', 'FSF.esm', skin_tones=[0, 1, 2], skin_tones_female=[0, 1])
    manifests = {'male': {'variants': [variant('m0', 0), variant('m2', 2)]},
                 'female': {'variants': [variant('f0', 0), variant('f2', 2)]}}
    warnings = []
    pairs = _pair_breed(r, breed, manifests, warnings)
    assert [(p.male['name'], p.female['name']) for p in pairs] == [('m0', 'f0'), ('m2', 'f0')]
    assert not warnings


def run_cli(races_dir, tmp_path):
    return subprocess.run(
        [sys.executable, str(ROOT / 'sf_furrify.py'), '--data', str(game_data()), '--plugin', 'FSF.esm', '--out', str(tmp_path / 'x.esm'),
         '--scheme', str(SCHEME), '--builtin', str(BUILTIN),
         '--races', str(races_dir), '--only', 'NoSuchNPC', '--dry-run'],
        capture_output=True, text=True, cwd=ROOT)


def edited_races(tmp_path, change):
    races = tmp_path / 'races'
    shutil.copytree(RACES, races)
    path = races / 'FSFFoxRace.toml'
    with open(path, encoding='utf-8', newline='') as f:
        text = f.read()
    new = change(text)
    assert new != text
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(new)
    return races


def test_the_shipped_fox_tones_are_all_real(tmp_path):
    proc = run_cli(RACES, tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_a_tone_the_sex_does_not_have_stops_the_run(tmp_path):
    """A tone past the race's body tones would be a bald NPC, found only in game."""
    races = edited_races(tmp_path, lambda t: re.sub(r'skin_tones_female = \[[^\]]*\]',
                                                    'skin_tones_female = [0, 40]', t))
    proc = run_cli(races, tmp_path)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert 'FEMALE' in proc.stdout and 'tone 40' in proc.stdout, proc.stdout


def test_a_breed_with_no_weight_is_not_checked(tmp_path):
    """The fixture's fennec has a bad tone (40), and it's switched off."""
    cfg = load_races(RACES)['FSFFoxRace']
    fennec = next(b for b in cfg.breeds if b.name == 'fennec')
    assert fennec.weight == 0 and 40 in fennec.skin_tone_override
    proc = run_cli(RACES, tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_a_breed_with_weight_is_checked(tmp_path):
    def turn_on(text):
        return re.sub(r'(name = "fennec"\r?\n)weight = 0', r'\1weight = 10', text)
    proc = run_cli(edited_races(tmp_path, turn_on), tmp_path)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert 'fennec' in proc.stdout and 'FEMALE' in proc.stdout, proc.stdout
