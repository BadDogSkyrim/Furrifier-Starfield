"""Crowds: run the furrifier on real game data and read the plugin back."""
import re
import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
from fsfdata import BUILTIN, RACES, game_data  # noqa: E402
sys.path.insert(0, str(ROOT))
from fsftools.config import BreedDef, RaceConfig, SchemeConfig  # noqa: E402
from fsftools.crowd_builder import CrowdError, crowd_plan, whole_shares, write_test_batch  # noqa: E402
from fsftools.plugin_loader import load_full_order, load_order_for_plugin, load_plugins  # noqa: E402

OUTFITS = 39
PAIRINGS = 15
FOX_LIST = 'FSF_LL_Crowd_Heads_FSFFoxRace'


def scheme(*proportions):
    return '[proportions]\n' + ''.join(f'{k} = {v}\n' for k, v in proportions)


def run(tmp_path, name, scheme_text, *extra):
    """Crowds only, by asking for no named NPC. Returns (output path, process)."""
    work = tmp_path / name
    work.mkdir()
    (work / 'scheme.toml').write_text(scheme_text, encoding='utf-8')
    out = work / 'crowdtest.esm'
    cmd = [sys.executable, str(ROOT / 'sf_furrify.py'), '--data', str(game_data()), '--plugin', 'FSF.esm', '--out', str(out),
           '--scheme', str(work / 'scheme.toml'), '--builtin', str(BUILTIN),
           '--races', str(RACES), '--only', 'NoSuchNPC', '--crowd-test', *extra]
    return out, subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)


def run_no_test_npcs(tmp_path):
    work = tmp_path / 'plain'
    work.mkdir()
    (work / 'scheme.toml').write_text(scheme(('FSFFoxRace', 100)), encoding='utf-8')
    out = work / 'plain.esm'
    return out, subprocess.run(
        [sys.executable, str(ROOT / 'sf_furrify.py'), '--data', str(game_data()), '--plugin', 'FSF.esm', '--out', str(out),
         '--scheme', str(work / 'scheme.toml'), '--builtin', str(BUILTIN),
         '--races', str(RACES), '--only', 'NoSuchNPC'], capture_output=True, text=True, cwd=ROOT)


@pytest.fixture(scope='module')
def game():
    data = game_data()
    return load_plugins(data, load_order_for_plugin(data, 'FSF.esm'))


class Output:
    """A written plugin, its references resolved by EditorID against the game."""

    def __init__(self, path, game):
        from esplib import Plugin
        self.plugin = Plugin.load(str(path))
        self.game = game
        self.vanilla = game.get_plugin('Starfield.esm')
        self.fsf = game.get_plugin('FSF.esm')
        self.masters = list(self.plugin.header.masters)
        self.own = {}
        for sig in ('LVLI', 'ARMO', 'ARMA', 'OTFT', 'NPC_'):
            for r in self.plugin.get_records_by_signature(sig):
                self.own[int(r.form_id.value)] = r

    def records(self, sig):
        return list(self.plugin.get_records_by_signature(sig))

    def by_edid(self, sig, edid):
        return next((r for r in self.records(sig) if r.editor_id == edid), None)

    def resolve(self, ref):
        if ref in self.own:
            return self.own[ref]
        return {0: self.vanilla, 1: self.fsf}[ref >> 24].get_record_by_form_id(ref)

    def entries(self, lst):
        return [self.resolve(struct.unpack_from('<I', s.data, 4)[0]) for s in lst.get_subrecords('LVLO')]

    def overrides(self):
        return [o for o in self.records('OTFT') if not o.editor_id.startswith('FSF_')]

    def items(self, outfit):
        data = bytes(outfit.get_subrecord('INAM').data)
        return list(struct.unpack(f'<{len(data) // 4}I', data))

    def head_armors(self, lst):
        """Every armor reachable from a list, through sub-lists."""
        found = []
        for e in self.entries(lst):
            found += self.head_armors(e) if e.signature == 'LVLI' else [e]
        return found

    def addons(self, armor):
        return [self.resolve(struct.unpack('<I', s.data)[0]) for s in armor.get_subrecords('MODL')]


@pytest.fixture(scope='module')
def all_fox(tmp_path_factory, game):
    out, proc = run(tmp_path_factory.mktemp('all_fox'), 'a', scheme(('FSFFoxRace', 100)))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return Output(out, game), out, proc


@pytest.fixture(scope='module')
def mixed(tmp_path_factory, game):
    out, proc = run(tmp_path_factory.mktemp('mixed'), 'a', scheme(('FSFFoxRace', 40), ('_HUMAN', 60)))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return Output(out, game)


def test_whole_shares():
    assert whole_shares({'a': 40, 'b': 60}, 'x') == {'a': 2, 'b': 3}
    assert whole_shares({'a': 40}, 'x') == {'a': 1}
    assert whole_shares({'a': 40, 'b': 0}, 'x') == {'a': 1}
    assert whole_shares({}, 'x') == {}
    with pytest.raises(CrowdError):
        whole_shares({'a': 149, 'b': 151}, 'x')


def manifest_file(tmp_path, sex, names):
    path = tmp_path / f'{sex}.json'
    nifs = {'average': 'a.nif', 'thin': 't.nif', 'overweight': 'o.nif'}
    path.write_text(json.dumps({
        'sex': sex, 'tail': {'addon': 'Tail', 'nifs': {str(t): 'tail.nif' for _, t in names}},
        'variants': [{'name': n, 'tone': t, 'head': n + '.nif', 'nifs': nifs} for n, t in names]}))
    return str(path)


def planned(tmp_path, breeds, males, females, skin_tones=(0, 1)):
    race = RaceConfig('R', 'FSF.esm', skin_tones=list(skin_tones), breeds=breeds,
                      crowd_manifests=[manifest_file(tmp_path, 'male', males),
                                       manifest_file(tmp_path, 'female', females)])
    return crowd_plan({'R': race}, SchemeConfig(proportions={'R': 100}))


def test_breeds_take_their_heads_by_glob_and_tone(tmp_path):
    plan = planned(tmp_path,
                   [BreedDef('red', 90, crowd_heads=['Fox_*', 'fox_f_*']),
                    BreedDef('fen', 10, skin_tone_override=[5], crowd_heads=['fen_*']),
                    BreedDef('arctic', 0)],
                   [('Fox_a', 0), ('Fox_b', 5), ('fen_m_a', 5), ('fen_m_b', 0)],
                   [('fox_f_a', 0), ('fox_f_b', 0), ('fen_f_a', 5)])
    race = plan.races['R']
    assert race.breed_shares == {'fen': 1, 'red': 9}, 'weight 0 is out, the rest reduced'
    red = race.heads['red']
    assert [(p.male['name'], p.female['name']) for p in red] == [('Fox_a', 'fox_f_a'), ('Fox_a', 'fox_f_b')], \
        'the race tones limit red, and the sex with fewer repeats'
    assert [(p.male['name'], p.female['name']) for p in race.heads['fen']] == [('fen_m_a', 'fen_f_a')]


def test_a_breed_left_with_no_heads_is_an_error(tmp_path):
    with pytest.raises(CrowdError, match='no crowd head'):
        planned(tmp_path, [BreedDef('red', 90, crowd_heads=['Nope_*'])], [('Fox_a', 0)], [('fox_f', 0)])


def test_a_breed_with_a_weight_needs_crowd_heads(tmp_path):
    with pytest.raises(CrowdError, match='no crowd_heads'):
        planned(tmp_path, [BreedDef('red', 90)], [('Fox_a', 0)], [('fox_f', 0)])


def test_the_sexes_pair_across_tones_and_every_head_is_used(tmp_path):
    """The sexes have different tones; a head armor only ever shows one of its two heads."""
    plan = planned(tmp_path, [BreedDef('red', 1, crowd_heads=['*'])],
                   [('a', 0), ('b', 1), ('c', 1)], [('d', 0)])
    race = plan.races['R']
    assert [(p.male['name'], p.female['name']) for p in race.heads['red']] == [('a', 'd'), ('b', 'd'), ('c', 'd')]
    assert not plan.warnings
    assert len({p.name for p in race.heads['red']}) == 3


def test_a_tail_addon_has_each_sex_s_own_tone(tmp_path):
    plan = planned(tmp_path, [BreedDef('red', 1, crowd_heads=['*'])],
                   [('a', 0), ('b', 1), ('c', 1)], [('d', 0)])
    race = plan.races['R']
    assert sorted(race.tail_nifs) == [(0, 0), (1, 0)], 'one addon per pair of tones in use'
    assert race.heads['red'][1].tail == (1, 0)


def test_a_sex_with_no_heads_in_a_breed_is_an_error(tmp_path):
    with pytest.raises(CrowdError, match='no crowd head'):
        planned(tmp_path, [BreedDef('red', 1, crowd_heads=['a*'])], [('a', 0)], [('d', 0)])


def with_beard_colors(path, colors):
    m = json.loads(Path(path).read_text())
    m['variants'][0]['beard'] = 'Ruff01'
    m['beard_colors'] = colors
    Path(path).write_text(json.dumps(m))


def test_one_beard_colour_list_for_both_sexes(tmp_path):
    """A ruff addon carries both sexes' ruffs and names one colour list, so the manifests must agree."""
    race = RaceConfig('R', 'FSF.esm', skin_tones=[0], breeds=[BreedDef('red', 1, crowd_heads=['*'])],
                      crowd_manifests=[manifest_file(tmp_path, 'male', [('a', 0)]),
                                       manifest_file(tmp_path, 'female', [('d', 0)])])
    with_beard_colors(race.crowd_manifests[0], 'Male_Colors')
    with_beard_colors(race.crowd_manifests[1], 'Fem_Colors')
    with pytest.raises(CrowdError, match='Male_Colors.*Fem_Colors|Fem_Colors.*Male_Colors'):
        crowd_plan({'R': race}, SchemeConfig(proportions={'R': 100}))
    with_beard_colors(race.crowd_manifests[1], 'Male_Colors')
    assert crowd_plan({'R': race}, SchemeConfig(proportions={'R': 100})).races['R'].beard_colors == 'Male_Colors'


def test_female_beards_alone_still_name_their_colours(tmp_path):
    race = RaceConfig('R', 'FSF.esm', skin_tones=[0], breeds=[BreedDef('red', 1, crowd_heads=['*'])],
                      crowd_manifests=[manifest_file(tmp_path, 'male', [('a', 0)]),
                                       manifest_file(tmp_path, 'female', [('d', 0)])])
    with_beard_colors(race.crowd_manifests[1], 'Fem_Colors')
    assert crowd_plan({'R': race}, SchemeConfig(proportions={'R': 100})).races['R'].beard_colors == 'Fem_Colors'


def test_a_tone_with_no_tail_is_an_error(tmp_path):
    race = RaceConfig('R', 'FSF.esm', skin_tones=[0, 1], breeds=[BreedDef('red', 1, crowd_heads=['*'])],
                      crowd_manifests=[manifest_file(tmp_path, 'male', [('a', 0), ('b', 1)]),
                                       manifest_file(tmp_path, 'female', [('d', 0)])])
    male = json.loads(Path(race.crowd_manifests[0]).read_text())
    del male['tail']['nifs']['1']
    Path(race.crowd_manifests[0]).write_text(json.dumps(male))
    with pytest.raises(CrowdError, match='male tone'):
        crowd_plan({'R': race}, SchemeConfig(proportions={'R': 100}))


def test_each_sex_wears_a_tail_in_its_own_head_s_tone(all_fox):
    """Real manifests: each sex's tail takes its own head's tone, whatever tones each sex has."""
    output = all_fox[0]
    tone = lambda addon, sig: int(re.search(r'_sk(\d+)', addon.get_subrecord(sig).get_string()).group(1))  # noqa: E731
    armors = [a for a in output.records('ARMO') if 'CrowdHead' in a.editor_id]
    assert armors
    for armor in armors:
        head, tail = output.addons(armor)[:2]
        assert tone(tail, 'MOD2') == tone(head, 'MOD2'), armor.editor_id
        assert tone(tail, 'MOD3') == tone(head, 'MOD3'), armor.editor_id


def test_every_crowd_outfit_is_overridden_keeping_its_clothes(all_fox, game):
    output = all_fox[0]
    overrides = output.overrides()
    assert len(overrides) == OUTFITS
    assert not output.by_edid('NPC_', 'CrowdActor_Akila_Male_01'), 'crowd actors stay as they are'
    assert not output.records('GBFM'), 'regions stay as they are'
    for outfit in overrides:
        vanilla = output.vanilla.get_record_by_form_id(int(outfit.form_id.value))
        before, after = output.items(vanilla), output.items(outfit)
        assert len(after) == 2, outfit.editor_id
        old = {output.resolve(i).editor_id for i in before}
        new = [output.resolve(i).editor_id for i in after]
        clothes = [e for e in old if not e.startswith(('LL_Crowd_Heads', 'LL_Crowd_Hairs'))]
        assert clothes[0] in new, outfit.editor_id
        assert sum(e.startswith('FSF_LL_Crowd_Mix_') for e in new) == 1, outfit.editor_id
    assert sum(r.editor_id.startswith('FSF_LL_Crowd_Mix_') for r in output.records('LVLI')) == PAIRINGS


def test_all_fox_has_no_human_branch(all_fox):
    output = all_fox[0]
    assert not [r for r in output.records('LVLI') if 'Crowd_Human' in r.editor_id]
    mix = output.by_edid('LVLI', 'FSF_LL_Crowd_Mix_Heads_Hairs_Hats_Akila')
    assert [e.editor_id for e in output.entries(mix)] == [FOX_LIST]


def test_mix_lists_hold_the_scheme_ratio(mixed):
    mix = mixed.by_edid('LVLI', 'FSF_LL_Crowd_Mix_Heads_Thin_Hairs_NoHats')
    assert sorted(e.editor_id for e in mixed.entries(mix)) == \
        [FOX_LIST + '_Thin'] * 2 + ['FSF_LL_Crowd_Human_Heads_Thin_Hairs_NoHats'] * 3


def test_human_branch_uses_all_of_vanillas_lists(mixed):
    human = mixed.by_edid('LVLI', 'FSF_LL_Crowd_Human_Heads_Hairs_Hats_Akila')
    assert [e.editor_id for e in mixed.entries(human)] == ['LL_Crowd_Heads', 'LL_Crowd_Hairs_Hats_Akila']
    assert human.get_subrecord('LVLF').data[0] & 4, 'Use All'
    mix = mixed.by_edid('LVLI', 'FSF_LL_Crowd_Mix_Heads_Hairs_Hats_Akila')
    assert not mix.get_subrecord('LVLF').data[0] & 4, 'the mix picks one'


def test_keep_hair_gives_furry_heads_the_outfit_s_hair(tmp_path, game):
    """--keep-hair: each race's entry is a Use All of its head list and the outfit's own hair list."""
    out, proc = run(tmp_path, 'hair', scheme(('FSFFoxRace', 40), ('_HUMAN', 60)), '--keep-hair')
    assert proc.returncode == 0, proc.stdout + proc.stderr
    output = Output(out, game)
    mix = output.by_edid('LVLI', 'FSF_LL_Crowd_Mix_Heads_Thin_Hairs_NoHats')
    assert sorted(e.editor_id for e in output.entries(mix)) == \
        ['FSF_LL_Crowd_FSFFoxRace_Heads_Thin_Hairs_NoHats'] * 2 + \
        ['FSF_LL_Crowd_Human_Heads_Thin_Hairs_NoHats'] * 3
    fox = output.by_edid('LVLI', 'FSF_LL_Crowd_FSFFoxRace_Heads_Hairs_Hats_Akila')
    assert [e.editor_id for e in output.entries(fox)] == [FOX_LIST, 'LL_Crowd_Hairs_Hats_Akila']
    assert fox.get_subrecord('LVLF').data[0] & 4, 'Use All'


def test_all_human_changes_nothing(tmp_path, game):
    out, proc = run(tmp_path, 'human', scheme(('_HUMAN', 100)))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    from esplib import Plugin
    plugin = Plugin.load(str(out))
    assert not list(plugin.get_records_by_signature('OTFT'))
    assert not list(plugin.get_records_by_signature('LVLI'))


def test_outfit_body_types_reach_only_their_own_heads(all_fox):
    output = all_fox[0]
    for suffix in ('_Thin', '_Overweight', ''):
        armors = output.head_armors(output.by_edid('LVLI', FOX_LIST + suffix))
        assert armors
        for armor in armors:
            model = output.addons(armor)[0].get_subrecord('MOD2').get_string().lower()
            if suffix:
                assert armor.editor_id.endswith(suffix + '_NOTPLAYABLE') and model.endswith(suffix.lower() + '.nif')
            else:
                assert not model.endswith(('_thin.nif', '_overweight.nif'))


def test_breed_lists_follow_breed_weights_and_tones(all_fox):
    output = all_fox[0]
    lst = output.by_edid('LVLI', FOX_LIST)
    names = sorted(e.editor_id for e in output.entries(lst))
    assert names == [FOX_LIST + '_red_fox'], 'fennec has weight 0, so no list'
    red = output.head_armors(output.by_edid('LVLI', FOX_LIST + '_red_fox'))
    assert red
    for armor in red:
        addon = output.addons(armor)[0]
        assert 'crowd_fox_' in addon.get_subrecord('MOD2').get_string().lower()
        assert 'crowdf_fox_' in addon.get_subrecord('MOD3').get_string().lower()


def test_head_armors_hold_both_sexes_on_the_crowd_race(all_fox):
    output = all_fox[0]
    crowd_race = int(output.vanilla.get_record_by_editor_id('HumanCrowdRace').form_id.value)
    armors = output.head_armors(output.by_edid('LVLI', FOX_LIST))
    for armor in armors:
        addons = output.addons(armor)
        assert len(addons) == 3, 'head, tail, beard'
        head, tail, beard = addons
        for addon in addons:
            assert struct.unpack('<I', addon.get_subrecord('RNAM').data)[0] == crowd_race, addon.editor_id
            assert not addon.get_subrecords('MODL'), addon.editor_id
        assert head.get_subrecord('MOD2').get_string() and head.get_subrecord('MOD3').get_string()
        assert head.get_subrecord('NAM4') is not None and head.get_subrecord('NAM6') is not None
        assert tail.get_subrecord('MOD2').get_string() and tail.get_subrecord('MOD3').get_string()
        assert not int(tail.flags) & 0x180, 'a tail keeps its own colour'
        assert beard.get_subrecord('MOD2').get_string(), 'males have the beard'
        female = beard.get_subrecord('MOD3').get_string()
        assert '\\female\\beards\\' in female.lower(), f'females have theirs too: {female!r}'
        def body_type(nif):
            found = re.search(r'_(thin|overweight)\.nif$', nif.lower())
            return found.group(1) if found else 'average'
        assert body_type(female) == body_type(head.get_subrecord('MOD3').get_string()), female
        assert beard.get_subrecord('TNAM').get_string() == 'FSFFox_Crowd_Beard_Colors'
        slots = struct.unpack('<Q', armor.get_subrecord('BO64').data)[0]
        # Slot 17, the Beard slot, hides the tail on the same armor; slot 9 shows both (in game 11-06).
        assert slots == (1 << 2) | (1 << 15) | (1 << 9)
        assert struct.unpack('<Q', output.addons(armor)[2].get_subrecord('BO64').data)[0] == 1 << 9


def test_masters_and_new_ids(all_fox):
    output = all_fox[0]
    assert output.masters[:2] == ['Starfield.esm', 'FSF.esm']
    new = [r for r in output.own.values() if r.form_id.value >> 24 == len(output.masters)]
    ids = [int(r.form_id.value) & 0xFFFFFF for r in new]
    assert min(ids) == 0x800 and max(ids) < 0x1000 and len(set(ids)) == len(ids)
    assert output.own[(len(output.masters) << 24) | 0x800].editor_id == 'FSF_CrowdTest_M'


def test_test_npcs_stay_crowd_race_and_are_always_foxes(all_fox):
    output, out, _ = all_fox
    crowd_race = int(output.vanilla.get_record_by_editor_id('HumanCrowdRace').form_id.value)
    npcs = [n for n in output.records('NPC_') if n.editor_id.startswith('FSF_CrowdTest_')]
    assert len(npcs) == 6
    thin_f = output.by_edid('NPC_', 'FSF_CrowdTest_F_Thin')
    outfit = output.resolve(struct.unpack('<I', thin_f.get_subrecord('DOFT').data)[0])
    names = [output.resolve(i).editor_id for i in output.items(outfit)]
    assert FOX_LIST + '_Thin' in names
    for npc in npcs:
        assert struct.unpack('<I', npc.get_subrecord('RNAM').data)[0] == crowd_race
    lines = (out.parent / 'fsfnpc_crowd.txt').read_text().splitlines()
    assert len(lines) == 6 and all(line.startswith('player.placeatme ') for line in lines)


def test_a_normal_build_has_no_test_npcs(all_fox, tmp_path):
    out, proc = run_no_test_npcs(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    from esplib import Plugin
    plugin = Plugin.load(str(out))
    assert not any('CrowdTest' in (r.editor_id or '') for r in plugin.get_records_by_signature('NPC_'))


def test_the_full_order_has_every_official_master():
    """One missing light master moved every later light plugin's FE slot, and the batch placed the
    wrong plugin's records. A missing master's overrides also wouldn't be seen."""
    import sf_racecheck
    data = game_data()
    order = load_full_order(data)
    present = [m for m in sf_racecheck.OFFICIAL_MASTERS if (data / m).exists()]
    assert present == [m for m in order if m in present]


def light_or_full(path, light):
    with open(path, 'wb') as f:
        f.write(b'TES4' + b'\0' * 4 + struct.pack('<I', 0x100 if light else 0) + b'\0' * 12)


def test_the_batch_counts_the_light_plugins_before_ours(tmp_path):
    for name, light in (('a.esm', True), ('b.esm', False), ('c.esm', True), ('mine.esm', True)):
        light_or_full(tmp_path / name, light)

    class Npc:
        editor_id = 'X'

        class form_id:
            value = 0x02000801

    lines = write_test_batch(tmp_path / 'b.txt', 'mine.esm', [Npc], tmp_path, ['a.esm', 'b.esm', 'c.esm', 'mine.esm'])
    assert lines == ['player.placeatme FE002801 1']


def test_two_runs_are_identical(all_fox, tmp_path, game):
    _, first, _ = all_fox
    second, proc = run(tmp_path, 'again', scheme(('FSFFoxRace', 100)))
    assert proc.returncode == 0
    assert second.read_bytes() == first.read_bytes()


def test_skeleton_is_copied_over_vanillas_path(tmp_path, game):
    data = game_data()
    out, proc = run(tmp_path, 'skel', scheme(('FSFFoxRace', 100)), '--crowd-skeleton')
    assert proc.returncode == 0, proc.stdout + proc.stderr
    mod = out.parent           # the skeleton goes in the output folder
    root = mod / 'Meshes' / 'Actors' / 'human_crowd' / 'CharacterAssets'
    source = data / 'Meshes' / 'actors' / 'FSFCanine_Crowd' / 'characterassets'
    for rel in ('skeleton.nif', 'skeleton_facebones.nif', 'Female/skeleton.nif', 'Female/skeleton_facebones.nif'):
        assert (root / rel).read_bytes() == (source / rel).read_bytes(), rel


def test_a_race_without_manifests_stops_at_startup(tmp_path):
    work = tmp_path / 'races'
    work.mkdir()
    fox = (RACES / 'FSFFoxRace.toml').read_text(encoding='utf-8')
    start = fox.index('crowd_manifests = [')
    fox = fox[:start] + fox[fox.index(']\n', start) + 2:]
    (work / 'FSFFoxRace.toml').write_text(fox, encoding='utf-8')
    (tmp_path / 'scheme.toml').write_text(scheme(('FSFFoxRace', 100)), encoding='utf-8')
    proc = subprocess.run([sys.executable, str(ROOT / 'sf_furrify.py'), '--data', str(game_data()), '--plugin', 'FSF.esm', '--out',
                           str(tmp_path / 'x.esm'), '--scheme', str(tmp_path / 'scheme.toml'),
                           '--builtin', str(BUILTIN), '--races', str(work), '--dry-run'],
                          capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 2 and 'no crowd_manifests' in proc.stdout


def test_named_npcs_follow_relative_weights(tmp_path):
    """A class row wins over the default; a race alone is all of them; humans come from a weight."""
    def count(text):
        (tmp_path / 'scheme.toml').write_text(text, encoding='utf-8')
        proc = subprocess.run([sys.executable, str(ROOT / 'sf_furrify.py'), '--data', str(game_data()), '--plugin', 'FSF.esm', '--out',
                               str(tmp_path / 'x.esm'), '--scheme', str(tmp_path / 'scheme.toml'),
                               '--builtin', str(BUILTIN), '--races', str(RACES),
                               '--dry-run'], capture_output=True, text=True, cwd=ROOT)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        block = proc.stdout.split('Assignment:')[1].split('\n\n')[0]
        return {k.strip(): int(v) for k, v in (ln.split(':') for ln in block.strip().splitlines())}

    all_fox = count(scheme(('FSFFoxRace', 40)))
    assert 'HUMAN' not in all_fox
    total = all_fox['FSFFoxRace']
    forty = count(scheme(('FSFFoxRace', 40), ('_HUMAN', 60)))
    assert forty['FSFFoxRace'] + forty['HUMAN'] == total
    assert 0.35 < forty['FSFFoxRace'] / total < 0.45, forty
