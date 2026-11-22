"""race_copy: a new species from an existing one, on the real FSF.esm and FSFPlayer_FOX.esm."""
import re
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from esplib import Plugin

from fsftools.race_copy import copy_species, load_config

ROOT = Path(__file__).resolve().parent.parent
from fsfdata import RACE_COPIES, game_data  # noqa: E402
CONFIG = RACE_COPIES / 'FSFHyena.toml'


@pytest.fixture(scope='module')
def result():
    # The snapshot's FSF.esm already holds the hyena: this is copying it again, which updates it.
    data = game_data()
    cfg = load_config(CONFIG)
    fsf = Plugin.load(data / cfg['plugin'])
    source = {int(r.form_id.value): r.editor_id for r in Plugin.load(data / cfg['plugin'])}
    player = Plugin.load(data / cfg['player_from'])
    report = copy_species(fsf, player, cfg)
    return fsf, player, report, source, cfg


def _rec(plugin, edid):
    found = [r for r in plugin if r.editor_id == edid]
    assert len(found) == 1, f"{edid}: {len(found)} records"
    return found[0]


def _fid(rec):
    return int(rec.form_id.value)


def _u32s(rec, sig):
    return [struct.unpack('<I', bytes(s.data))[0] for s in rec.get_subrecords(sig)]


def _str(sub):
    return bytes(sub.data).rstrip(b'\0').decode('cp1252')


def _strings(rec, sig):
    return [_str(s) for s in rec.get_subrecords(sig)]


def _refs(rec, fids):
    """The FormIDs from fids that rec mentions anywhere."""
    found = set()
    for s in rec.subrecords:
        d = bytes(s.data)
        for off in range(len(d) - 3):
            v = struct.unpack_from('<I', d, off)[0]
            if v in fids:
                found.add(v)
    return found


def test_the_new_races_exist(result):
    fsf, *_ = result
    race = _rec(fsf, 'FSFHyenaRace')
    crowd = _rec(fsf, 'FSFHyenaCrowdRace')
    assert _strings(race, 'FULL') == ['Hyena']
    assert _strings(race, 'SNAM') == ['Hyenas']
    assert _strings(crowd, 'SNAM') == ['Hyenas']
    assert _fid(race) >> 24 == 1 and _fid(crowd) >> 24 == 1


def test_the_fox_crowd_race_is_named_foxes(result):
    fsf, *_ = result
    assert _strings(_rec(fsf, 'FSFFoxCrowdRace'), 'SNAM') == ['Foxes']


def test_copies_reference_no_fox_only_record(result):
    # Every FSF.esm record the copies came from, or that was dropped, is fox-only.
    fsf, player, report, source, _cfg = result
    fox_only = set(report['copied']) | set(report['dropped'])
    for rec in list(fsf) + list(player):
        if _fid(rec) in report['new'] or rec.editor_id in report['player_changed']:
            bad = _refs(rec, fox_only)
            assert not bad, f"{rec.editor_id} still refers to {[source[f] for f in bad]}"


def test_copies_name_no_fox(result):
    fsf, player, report, *_ = result
    for rec in fsf:
        if _fid(rec) not in report['new']:
            continue
        for s in rec.subrecords:
            d = bytes(s.data)
            if s.signature in ('EDID', 'FULL', 'MOD2', 'MOD3', 'TMPP', 'VNAM', 'LNAM', 'TNAM', 'YNAM',
                               'BSTT', 'HSTT', 'FSTT', 'FCTP', 'MPGM', 'FMRU', 'FMRN', 'FMRS', 'QNAM',
                               'BMPN'):
                assert not re.search(rb'(?i)fox|fennec', d), f"{rec.editor_id} {s.signature} {d}"


def test_the_hyena_has_one_phenotype_per_sex(result):
    fsf, *_ = result
    race = _rec(fsf, 'FSFHyenaRace')
    assert _strings(race, 'FMRN') == ['male_hyena_md1', 'female_hyena_md1']
    groups = _strings(race, 'MPGM')
    assert len(groups) == 18
    assert {g.rsplit('_', 1)[0] for g in groups} == {'male_hyena_md1', 'female_hyena_md1'}
    assert _strings(race, 'FCTP') == [r'actors\FSFHyena\faces\chargen'] * 2
    assert _strings(race, 'FSTT') == ['FSFHyenaFaceSkinTones']
    assert _strings(race, 'BSTT') == ['Male_FSFHyena_Body_Skin_Tones', 'Female_FSFHyena_Body_Skin_Tones']


def test_tone_lists_lose_the_fennec_tones(result):
    fsf, *_ = result
    group = _rec(fsf, 'SimpleGroup_FSFHyena_Body_Skin_Tones')
    keys = _strings(group, 'LNAM')
    assert len(keys) == 11 and _u32s(group, 'ITMC') == [11]
    assert _strings(group, 'VNAM')[0] == r'Textures\Actors\FSFHyena\naked_body\male_hyena_body_sk1_color.dds'
    faces = _rec(fsf, 'ComplexGroup_FSFHyenaFaceSkinTones')
    assert _strings(faces, 'LNAM') == ['female_hyena_md1', 'female_default', 'male_hyena_md1', 'male_default']
    assert _u32s(faces, 'ITMC') == [4]
    derms = sorted(r.editor_id for r in fsf if 'FSFHyenaDermaestheticSkinTone' in (r.editor_id or ''))
    assert len(derms) == 11


def test_the_hyena_has_its_own_skin_and_tail(result):
    fsf, *_ = result
    race = _rec(fsf, 'FSFHyenaRace')
    crowd = _rec(fsf, 'FSFHyenaCrowdRace')
    skin = _rec(fsf, 'FSFHyena_Skin_Naked')
    tail = _rec(fsf, 'FSFHyena_AA_Naked_Tail')
    assert _u32s(race, 'WNAM') == [_fid(skin)]
    assert _u32s(skin, 'RNAM') == [_fid(race)]
    assert _u32s(skin, 'MODL') == [_fid(_rec(fsf, 'FSFCanine_AA_Naked_Body')),
                                   _fid(_rec(fsf, 'FSFCanine_AA_Naked_Hands')), _fid(tail)]
    assert _u32s(tail, 'RNAM') == [_fid(race)]
    assert _fid(crowd) in _u32s(tail, 'MODL')
    assert _strings(tail, 'MOD2') == [r'Actors\fsfcanine\Mesh\TAIL\CanineMaleTailBrush.nif']
    body = _rec(fsf, 'FSFHyena_Skin_Crowd_Base_Body_NOTPLAYABLE')
    assert _u32s(crowd, 'WNAM') == [_fid(body)]
    assert _u32s(body, 'RNAM') == [_fid(crowd)]


def test_the_crowd_head_placeholder(result):
    fsf, *_ = result
    head = _rec(fsf, 'FSF_AA_CrowdHead_hyena_md1_NOTPLAYABLE')
    assert _u32s(head, 'RNAM') == [_fid(_rec(fsf, 'FSFHyenaCrowdRace'))]
    assert _strings(head, 'MOD2') == [r'Actors\fsfhyena_crowd\Mesh\male\Crowd_Hyena_md1.nif']
    morph = _rec(fsf, 'MORPH_FSFHyena_Crowd_Male_Hyena_md1_Head')
    assert _u32s(head, 'NAM4') == [_fid(morph)]
    assert _strings(morph, 'TMPP') == [r'meshes\morphs\FSFHyena_crowd\male\performance\Crowd_Hyena_md1']


def test_shared_records_gain_the_hyena_where_the_fox_is(result):
    fsf, *_ = result
    hyena, hyena_crowd = _fid(_rec(fsf, 'FSFHyenaRace')), _fid(_rec(fsf, 'FSFHyenaCrowdRace'))
    body = _rec(fsf, 'FSFCanine_AA_Naked_Body')
    assert hyena in _u32s(body, 'MODL') and hyena_crowd not in _u32s(body, 'MODL')
    # A shared piece the fox crowd wears too gains both hyena races, once each.
    fox, fox_crowd = _fid(_rec(fsf, 'FSFFoxRace')), _fid(_rec(fsf, 'FSFFoxCrowdRace'))
    helmet = _rec(fsf, 'FSFCanine_AA_Spacesuit_Miner_Helmet_01')
    assert sorted(_u32s(helmet, 'MODL')) == sorted([fox_crowd, hyena, hyena_crowd])
    assert _u32s(helmet, 'RNAM') == [fox]
    heads = _rec(fsf, 'HeadPartsFSFCanineRace')
    assert _u32s(heads, 'LNAM')[-1] == hyena and hyena_crowd not in _u32s(heads, 'LNAM')
    # The fox's own pieces don't change.
    assert hyena_crowd not in _u32s(_rec(fsf, 'FSF_AA_CrowdHead_fox_md1_NOTPLAYABLE'), 'MODL')


def test_additional_races_stay_before_the_footstep_sound(result):
    fsf, *_ = result
    tee = _rec(fsf, 'FSF_AA_Clothes_Trucker_Tee_01_Skin')
    sigs = [s.signature for s in tee.subrecords]
    assert sigs.index('MODL') > sigs.index('NAM6') and sigs.index('MODL') < sigs.index('MNAM')
    assert _u32s(tee, 'MODL') == [_fid(_rec(fsf, 'FSFHyenaRace'))]


def test_arm_pieces_are_renamed(result):
    fsf, _player, _report, source, _cfg = result
    assert not [r for r in fsf if (r.editor_id or '').startswith('FSFFox_AA_Clothes_')]
    pieces = [e for e in source.values() if (e or '').startswith(('FSFFox_AA_Clothes_', 'FSF_AA_Clothes_'))]
    assert pieces
    assert len([r for r in fsf if (r.editor_id or '').startswith('FSF_AA_Clothes_')]) == len(pieces)


def test_presets_are_copied_without_the_fennecs(result):
    fsf, _player, report, *_ = result
    presets = [r for r in fsf if (r.editor_id or '').startswith('_FSFHyenaChargenPreset')]
    assert len(presets) == 7
    race = _rec(fsf, 'FSFHyenaRace')
    assert sorted(_u32s(race, 'RPRM') + _u32s(race, 'RPRF')) == sorted(_fid(p) for p in presets)


def test_the_player_plugin(result):
    fsf, player, report, *_ = result
    hyena = _fid(_rec(fsf, 'FSFHyenaRace'))
    assert _u32s(_rec(player, 'Player'), 'RNAM') == [hyena]
    presets = {_fid(r) for r in fsf if (r.editor_id or '').startswith('_FSFHyenaChargenPreset')}
    listed = set(_u32s(_rec(player, 'CharGenPresets'), 'LNAM'))
    assert presets <= listed
    assert not listed & set(report['copied']) and not listed & set(report['dropped'])
    derm = _rec(player, 'ComplexGroup_Chargen_Dermaesthetic')
    assert _u32s(derm, 'ITMC') == [11]
    assert _strings(derm, 'VNAM')[1] == 'SimpleGroup_chargen_FSFHyenaDermaestheticSkinTone01'
    # The ruffs are shared, so their follicle masks stay.
    assert any('FSFFox_Ruff' in v for v in _strings(_rec(player, 'SimpleGroup_BeardFollicleMask'), 'VNAM'))
    assert not [r for r in player if r.editor_id == '_FSFFoxMaleTest']
    for r in player:
        if (r.editor_id or '').startswith('_FSFHyenaChargenPreset'):
            assert _fid(r) in presets
    assert player.header.masters == ['Starfield.esm', 'FSF.esm']


def test_written_plugins_read_back_the_same(result, tmp_path):
    fsf, player, *_ = result
    for plugin, name in ((fsf, 'FSF.esm'), (player, 'FSFPlayer_HYENA.esm')):
        data = plugin.to_bytes()
        (tmp_path / name).write_bytes(data)
        again = Plugin.load(tmp_path / name)
        assert again.to_bytes() == data
        assert sorted((int(r.form_id.value), r.editor_id) for r in again) == \
            sorted((int(r.form_id.value), r.editor_id) for r in plugin)


def test_new_formids_are_unused(result):
    fsf, _player, report, source, _cfg = result
    # A FormID already in the plugin can only be the same record: an earlier run's copy.
    edids = {int(r.form_id.value): r.editor_id for r in fsf}
    assert {f: (source[f], edids[f]) for f in report['new'] & set(source) if source[f] != edids[f]} == {}
    ids = [int(r.form_id.value) for r in fsf]
    assert len(ids) == len(set(ids))
    assert fsf.header.next_object_id > max(i & 0xFFFFFF for i in ids if i >> 24 == 1)
