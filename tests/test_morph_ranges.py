"""Per-breed morph ranges: run the furrifier on real game data and read the plugin back."""
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
from fsfdata import BUILTIN, RACES, SCHEME, game_data  # noqa: E402
sys.path.insert(0, str(ROOT))
from fsftools.config import MorphRange  # noqa: E402
from fsftools.furrify_npc import roll_morph  # noqa: E402

NPCS = ['Companion_SarahMorgan', 'Companion_SamCoe', 'FC_Neon_GenericCustomerF0*',
        'FC_Neon_GenericCustomerM0*', 'CF06_LvlSyndicate_Unaggressive_F01']
MARKER = '# -- Morph ranges --'

BASE = """
[morph_defaults.male_fox_md1]
Ears = { chance = 100, min = 0.2, max = 0.4 }
Nose = { chance = 0, min = 0.0, max = 1.0 }
Neck = { chance = 100, min = 0.1, max = 0.9, skew = "low" }

[morph_defaults.female_fox_md1]
Ears = { min = 0.6, max = 0.7 }
"""

BREED = """
[[breeds]]
name = "only"
weight = 100
phenotypes_male = [["male_fox_md1", 100]]
phenotypes_female = [["female_fox_md1", 100]]
"""


def text(sr):
    return sr.data.rstrip(b'\0').decode('utf-8')


def fox_toml(section):
    """The shipped fox config with its morph ranges and breeds replaced."""
    shipped = (RACES / 'FSFFoxRace.toml').read_text(encoding='utf-8')
    assert MARKER in shipped
    return shipped.split(MARKER)[0] + section


def run_furrifier(tmp_path, name, section):
    """Returns (returncode, output path, combined log)."""
    work = tmp_path / name
    (work / 'races').mkdir(parents=True)
    (work / 'races' / 'FSFFoxRace.toml').write_bytes(fox_toml(section).encode('utf-8'))
    out = work / 'morphtest.esm'
    cmd = [sys.executable, str(ROOT / 'sf_furrify.py'), '--data', str(game_data()), '--plugin', 'FSF.esm', '--out', str(out),
           '--scheme', str(SCHEME), '--builtin', str(BUILTIN),
           '--races', str(work / 'races')]
    for n in NPCS:
        cmd += ['--only', n]
    run = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    return run.returncode, out, run.stdout + run.stderr


def built(tmp_path, name, section):
    """{NPC EditorID: (is_female, {BMPN: BMPV})} from a successful run, and the plugin's path."""
    code, out, log = run_furrifier(tmp_path, name, section)
    assert code == 0, log
    from esplib import Plugin
    result = {}
    for npc in Plugin.load(str(out)).get_records_by_signature('NPC_'):
        keys = [text(s) for s in npc.get_subrecords('BMPN')]
        values = [struct.unpack('<f', s.data)[0] for s in npc.get_subrecords('BMPV')]
        assert len(keys) == len(values), npc.editor_id
        result[npc.editor_id] = (bool(npc.get_subrecord('ACBS').data[0] & 1), dict(zip(keys, values)))
    assert any(f for f, _ in result.values()) and not all(f for f, _ in result.values())
    return result, out


def near(value, low, high):
    return low - 1e-6 <= value <= high + 1e-6


def test_values_stay_in_the_sexes_own_ranges(tmp_path):
    npcs, _ = built(tmp_path, 'a', BASE + BREED)
    for edid, (is_female, morphs) in npcs.items():
        if is_female:
            assert set(morphs) == {'female_fox_md1_Ears'}, edid
            assert near(morphs['female_fox_md1_Ears'], 0.6, 0.7), edid
        else:
            assert set(morphs) == {'male_fox_md1_Ears', 'male_fox_md1_Neck'}, edid
            assert near(morphs['male_fox_md1_Ears'], 0.2, 0.4), edid
            assert near(morphs['male_fox_md1_Neck'], 0.1, 0.9), edid
    males = [m for f, m in npcs.values() if not f]
    assert len({m['male_fox_md1_Neck'] for m in males}) > 1, 'NPCs should differ'


def test_two_runs_are_byte_identical(tmp_path):
    _, first = built(tmp_path, 'a', BASE + BREED)
    _, second = built(tmp_path, 'b', BASE + BREED)
    assert first.read_bytes() == second.read_bytes()


def test_changing_one_range_changes_only_that_key(tmp_path):
    before, _ = built(tmp_path, 'a', BASE + BREED)
    edited = BASE.replace('min = 0.1, max = 0.9', 'min = 0.5, max = 0.6')
    assert edited != BASE
    after, _ = built(tmp_path, 'b', edited + BREED)
    changed = 0
    for edid, (_, morphs) in before.items():
        for key, value in morphs.items():
            if key == 'male_fox_md1_Neck':
                assert near(after[edid][1][key], 0.5, 0.6)
                changed += after[edid][1][key] != value
            else:
                assert after[edid][1][key] == value, (edid, key)
    assert changed


def test_breed_overrides_only_what_it_lists(tmp_path):
    section = BASE + BREED + """
[breeds.morphs.male_fox_md1]
Ears = { chance = 100, min = 0.8, max = 0.9 }
"""
    npcs, _ = built(tmp_path, 'a', section)
    for edid, (is_female, morphs) in npcs.items():
        if is_female:
            assert near(morphs['female_fox_md1_Ears'], 0.6, 0.7), edid
        else:
            assert near(morphs['male_fox_md1_Ears'], 0.8, 0.9), edid
            assert near(morphs['male_fox_md1_Neck'], 0.1, 0.9), 'the rest keep the default'


def test_blend_is_scaled_to_fit_the_region_cap(tmp_path):
    section = """
[morph_defaults.male_fox_md1]
Ears = { min = 0.7, max = 0.7 }
Nose = { min = 1.0, max = 1.0 }
Neck = { min = 0.2, max = 0.2 }

[morph_defaults.female_fox_md1]
Ears = { min = 0.5, max = 0.5 }
""" + BREED + """
[breeds.blend.male_fennec_md1]
Ears = { min = 0.6, max = 0.6 }
Nose = { min = 0.5, max = 0.5 }
Cheeks = { min = 0.4, max = 0.4 }
Neck = { min = 0.3, max = 0.3 }
"""
    npcs, _ = built(tmp_path, 'a', section)
    for edid, (is_female, morphs) in npcs.items():
        if is_female:
            assert set(morphs) == {'female_fox_md1_Ears'}, 'a male blend must not reach a female'
            continue
        assert near(morphs['male_fennec_md1_Ears'], 0.3, 0.3), 'scaled: 0.7 + 0.3 = 1.0'
        assert 'male_fennec_md1_Nose' not in morphs, 'no room left beside a full-weight key'
        assert near(morphs['male_fennec_md1_Cheeks'], 0.4, 0.4), 'nothing else in the region'
        assert near(morphs['male_fennec_md1_Neck'], 0.3, 0.3), 'under the cap, untouched'
        assert near(morphs['male_fox_md1_Ears'], 0.7, 0.7), 'the main phenotype is never scaled'


@pytest.mark.parametrize('section, expected', [
    ('[morph_defaults.male_fox_md1]\nSnout = { min = 0.0, max = 1.0 }\n'
     '[morph_defaults.female_fox_md1]\nEars = {}\n' + BREED, 'male_fox_md1_Snout'),
    ('[morph_defaults.male_wolf_md1]\nEars = {}\n[morph_defaults.male_fox_md1]\nEars = {}\n'
     '[morph_defaults.female_fox_md1]\nEars = {}\n' + BREED, 'male_wolf_md1_Ears'),
    ('[morph_defaults.male_fox_md1]\nEars = { min = 0.9, max = 0.1 }\n'
     '[morph_defaults.female_fox_md1]\nEars = {}\n' + BREED, 'min'),
    ('[morph_defaults.male_fox_md1]\nEars = { max = 1.5 }\n'
     '[morph_defaults.female_fox_md1]\nEars = {}\n' + BREED, 'max'),
    ('[morph_defaults.male_fox_md1]\nEars = { chance = 101 }\n'
     '[morph_defaults.female_fox_md1]\nEars = {}\n' + BREED, 'chance'),
    ('[morph_defaults.male_fox_md1]\nEars = { skew = "sideways" }\n'
     '[morph_defaults.female_fox_md1]\nEars = {}\n' + BREED, 'sideways'),
    ('[morph_defaults.male_fox_md1]\nEars = { mx = 0.5 }\n'
     '[morph_defaults.female_fox_md1]\nEars = {}\n' + BREED, 'mx'),
    ('[morph_defaults.male_fox_md1]\nEars = {}\n' + BREED, 'female_fox_md1'),
    (BASE + BREED + '[breeds.morphs.male_fennec_md1]\nEars = {}\n', 'male_fennec_md1'),
])
def test_bad_config_stops_at_startup(tmp_path, section, expected):
    code, out, log = run_furrifier(tmp_path, 'a', section)
    assert code == 2, log
    assert expected in log, log
    assert not out.exists()


def test_skew_matches_the_fo4_furrifier():
    def mean(skew):
        rng = MorphRange(min=0.0, max=1.0, skew=skew)
        return sum(roll_morph(rng, f'npc{i}', 'k') for i in range(4000)) / 4000
    assert abs(mean('even') - 0.5) < 0.03
    assert abs(mean('low') - 1 / 3) < 0.03, 'v*v'
    assert abs(mean('high') - 2 / 3) < 0.03, '1-(1-v)*(1-v)'


def test_chance_is_honoured():
    hits = [roll_morph(MorphRange(chance=25), f'npc{i}', 'k') is not None for i in range(4000)]
    assert abs(sum(hits) / 4000 - 0.25) < 0.03
    assert all(roll_morph(MorphRange(chance=0), f'npc{i}', 'k') is None for i in range(200))
    assert all(roll_morph(MorphRange(chance=100), f'npc{i}', 'k') is not None for i in range(200))


def test_shipped_config_writes_only_race_keys(tmp_path):
    """The real TOML, through the real race."""
    from fsftools.plugin_loader import load_order_for_plugin, load_plugins
    work = tmp_path / 'real'
    work.mkdir()
    out = work / 'morphtest.esm'
    cmd = [sys.executable, str(ROOT / 'sf_furrify.py'), '--data', str(game_data()), '--plugin', 'FSF.esm', '--out', str(out),
           '--scheme', str(SCHEME), '--builtin', str(BUILTIN),
           '--races', str(RACES)]
    for n in NPCS:
        cmd += ['--only', n]
    run = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    assert run.returncode == 0, run.stdout + run.stderr
    data = game_data()
    race = load_plugins(data, load_order_for_plugin(data, 'FSF.esm')).get_record_by_edid('RACE', 'FSFFoxRace')
    declared = {text(s) for s in race.get_subrecords('MPGM')}
    from esplib import Plugin
    seen = []
    for npc in Plugin.load(str(out)).get_records_by_signature('NPC_'):
        keys = [text(s) for s in npc.get_subrecords('BMPN')]
        assert keys and set(keys) <= declared, npc.editor_id
        for s in npc.get_subrecords('BMPV'):
            value = struct.unpack('<f', s.data)[0]
            assert 0.0 <= value <= 1.0, npc.editor_id
            seen.append(round(value, 3))
    assert len(set(seen)) > 3, 'values should vary'
