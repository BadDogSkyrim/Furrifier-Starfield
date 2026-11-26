"""Facial hair: which parts a race may draw (their RNAM race list) and how often (facial_hair_<sex>).

The race filter reads the FSF snapshot (tests/fixtures/fsf). There the fox ruffs list
HeadPartsFSFCanineRace (FSFFoxRace, HumanRace, FSFHyenaRace); Beard01-03, Ruff02a, Ruff05 and
Ruff06 have no RNAM; no part lists either crowd race.
"""
import copy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fsfdata import RACES, game_data  # noqa: E402
from fsftools.config import _load_one_race  # noqa: E402
from fsftools.furrify_npc import _plan_head_parts  # noqa: E402
from fsftools.plugin_loader import load_order_for_plugin, load_plugins  # noqa: E402
from fsftools.race_data import RaceAppearance  # noqa: E402

FOX_MALE = {'FSFFox_Male_Ruff01', 'FSFFox_Male_Ruff02', 'FSFFox_Male_Ruff03', 'FSFFox_Male_Ruff04',
            'FSFFox_Male_Ruff04b2', 'FSFFox_Male_Ruff07', 'FSFFox_Male_Ruff07b2', 'FSFFox_Male_Ruff08',
            'FSFFox_Male_Ruff08b1', 'FSFFox_Male_Ruff09', 'FSFFox_Male_Ruff09b3'}
FOX_FEMALE = {'FSFFox_Fem_Ruff01', 'FSFFox_Fem_Ruff02', 'FSFFox_Fem_Ruff03'}


@pytest.fixture(scope='module')
def plugins():
    data = game_data()
    return load_plugins(data, load_order_for_plugin(data, 'FSFPlayer_FOX.esm'))


def facial_hair(plugins, editorid, crowd=None, **chances):
    """Run only the facial-hair loading of RaceAppearance for a race config. Returns (parts, problems)."""
    cfg = copy.copy(_load_one_race(RACES / 'FSFFoxRace.toml'))
    cfg.editorid, cfg.crowd_race_editorid = editorid, crowd
    for k, v in chances.items():
        setattr(cfg, k, v)
    ra = RaceAppearance.__new__(RaceAppearance)
    ra.cfg, ra.problems = cfg, []
    parts = ra._load_facial_hair(plugins)
    return {sex: {h.editor_id for h in p} for sex, p in parts.items()}, ra.problems


def test_only_parts_that_list_the_race(plugins):
    parts, problems = facial_hair(plugins, 'FSFFoxRace')
    assert parts == {'MALE': FOX_MALE, 'FEMALE': FOX_FEMALE}, 'parts with no RNAM are for no race'
    assert not problems


def test_a_race_no_part_lists_gets_none(plugins):
    parts, _ = facial_hair(plugins, 'FSFFoxCrowdRace')
    assert parts == {'MALE': set(), 'FEMALE': set()}


def test_the_crowd_race_counts_too(plugins):
    """A part that lists only the crowd race is still the race's. In the snapshot no part lists a
    crowd race, so this names the crowd race as the race and the listed race as its crowd race."""
    parts, _ = facial_hair(plugins, 'FSFFoxCrowdRace', crowd='FSFFoxRace')
    assert parts == {'MALE': FOX_MALE, 'FEMALE': FOX_FEMALE}


def test_a_chance_with_no_parts_stops_at_startup(plugins):
    _, problems = facial_hair(plugins, 'FSFFoxCrowdRace', facial_hair_male=0.5)
    assert len(problems) == 1 and 'facial_hair_male' in problems[0], problems
    _, problems = facial_hair(plugins, 'FSFFoxCrowdRace', facial_hair_male=0.0)
    assert not problems, 'a chance of 0 needs no parts'
    _, problems = facial_hair(plugins, 'FSFFoxCrowdRace')
    assert not problems, 'unset needs no parts: a race may simply have none'


# -- The chance --

def toml_with(tmp_path, line):
    shipped = (RACES / 'FSFFoxRace.toml').read_text(encoding='utf-8')
    assert '\n[race]\n' in shipped
    path = tmp_path / 'race.toml'
    path.write_bytes(shipped.replace('\n[race]\n', f'\n[race]\n{line}\n', 1).encode('utf-8'))
    return _load_one_race(path)


def test_the_chances_are_read_per_sex(tmp_path):
    cfg = toml_with(tmp_path, 'facial_hair_male = 0.7\nfacial_hair_female = 0')
    assert (cfg.facial_hair_chance('MALE'), cfg.facial_hair_chance('female')) == (0.7, 0.0)
    assert not cfg.problems
    cfg = _load_one_race(RACES / 'FSFFoxRace.toml')
    assert cfg.facial_hair_chance('MALE') == cfg.facial_hair_chance('FEMALE') == 1.0, 'unset is always'


@pytest.mark.parametrize('value', ['1.5', '-0.1', '"often"', 'true'])
def test_a_chance_outside_0_to_1_is_a_problem(tmp_path, value):
    cfg = toml_with(tmp_path, f'facial_hair_male = {value}')
    assert len(cfg.problems) == 1 and 'facial_hair_male' in cfg.problems[0], cfg.problems


def planned(chance, n=200):
    """How many of n NPCs get a facial-hair part at this chance, and whether every pick is stable."""
    parts = [SimpleNamespace(editor_id=f'Beard{i}') for i in range(3)]
    cfg = SimpleNamespace(facial_hair_chance=lambda sex: chance)
    appearance = SimpleNamespace(cfg=cfg, base_parts={'MALE': ['head']}, facial_hair={'MALE': parts},
                                 beard_colors={})
    got = []
    for i in range(n):
        change = SimpleNamespace(sex='MALE', facial_hair_color=None)
        _plan_head_parts(change, appearance, f'npc{i}')
        again = SimpleNamespace(sex='MALE', facial_hair_color=None)
        _plan_head_parts(again, appearance, f'npc{i}')
        assert change.head_parts == again.head_parts, 'the same NPC always gets the same answer'
        assert change.head_parts[0] == 'head' and len(change.head_parts) <= 2
        got.append(len(change.head_parts) == 2)
    return sum(got)


def test_the_chance_decides_who_gets_facial_hair():
    assert planned(0.0) == 0
    assert planned(1.0) == 200
    assert 70 < planned(0.5) < 130
