"""Outfits with a human piece the race has its own copy of: the copy listed right after the human one.

A fox matches the human piece through its Armor Race, and of two pieces matching one slot the one
listed last draws. So the output overrides every outfit holding a human piece that has a copy (bare-skin
arms, helmets), starting from the outfit's winning record, with the copy inserted after the human piece.

Real game data: FSF.esm holds the copies (<prefix>_<human EditorID>, e.g. FSFFox_..., FSFCanine_...).
"""
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
from fsfdata import game_data  # noqa: E402
sys.path.insert(0, str(ROOT))
from fsftools.plugin_loader import (
    load_order_for_plugin,
    load_plugins,
)
from fsftools.race_pieces import (
    _order_copies,
    _rec_key,
    _with_copies,
    add_race_pieces,
    race_copies,
)

RACES = ['FSFFoxRace']
TRUCKER = 'Clothes_Trucker_Tee_01'
HUMAN = 'AA_Clothes_Trucker_Tee_01_Skin'
HELMET_ARMO = 'Spacesuit_CrimsonFleet_Charger_Helmet'
HELMET = 'AA_Spacesuit_CrimsonFleet_Charger_Helmet'
FOX_HELMET = 'FSFCanine_' + HELMET


def new_output(masters):
    from esplib.plugin import Plugin
    out = Plugin()
    out.header.version = 0.96
    out.header.masters = list(masters)
    out.header.master_sizes = [0] * len(masters)
    out.header.is_esm = True
    out.header.next_object_id = 0x800
    return out


def build(order_for):
    data = game_data()
    order = order_for(data)
    plugins = load_plugins(data, order)
    masters = ['Starfield.esm', 'FSF.esm']
    out = new_output(masters)
    result = add_race_pieces(out, plugins, order, masters, data, RACES)
    return out, plugins, masters, result


@pytest.fixture(scope='module')
def fsf():
    return build(lambda data: load_order_for_plugin(data, 'FSF.esm'))


@pytest.fixture(scope='module')
def copies(fsf):
    _out, plugins, _masters, _result = fsf
    return race_copies(plugins, load_order_for_plugin(game_data(), 'FSF.esm'), RACES)


def ref(masters, rec):
    """rec's FormID in the output's numbering."""
    home = rec.plugin.header.masters
    index = int(rec.form_id.value) >> 24
    name = home[index] if index < len(home) else Path(rec.plugin.file_path).name
    return ([m.lower() for m in masters].index(name.lower()) << 24) | (int(rec.form_id.value) & 0xFFFFFF)


def addons(subs):
    subs = list(subs)
    return [(struct.unpack('<H', bytes(i.data))[0], struct.unpack('<I', bytes(m.data))[0])
            for i, m in zip([s for s in subs if s.signature == 'INDX'],
                            [s for s in subs if s.signature == 'MODL'])]


def test_finds_the_copies(copies):
    names = {human.editor_id: [c.editor_id for c in cs] for human, cs in copies.values()}
    assert len(names[HUMAN]) == 1 and names[HUMAN][0].endswith('_' + HUMAN), names[HUMAN]
    assert 'AA_Child_Hands_NOTPLAYABLE' not in names
    # The race's own body and hands stand in for the human race's, in an outfit that wears those
    # (Clothes_Naked_Body_SwimSuit).
    assert names['AA_Naked_Body'] == ['FSFCanine_AA_Naked_Body']
    assert names['AA_Naked_Hands'] == ['FSFCanine_AA_Naked_Hands']


def test_finds_pieces_that_are_not_skin(copies):
    """Any piece can have a copy: helmets aren't skin, and the prefix doesn't matter."""
    names = {human.editor_id: [c.editor_id for c in cs] for human, cs in copies.values()}
    assert names[HELMET] == [FOX_HELMET]


def test_race_skins_are_not_outfits(fsf):
    out, _plugins, _masters, _result = fsf
    edids = {r.editor_id for r in out.get_records_by_signature('ARMO')}
    assert 'Clothes_Naked_Body_SwimSuit' in edids
    assert 'Skin_Naked' not in edids


def test_copy_follows_the_human_piece(fsf, copies):
    out, plugins, masters, _result = fsf
    armos = {r.editor_id: r for r in out.get_records_by_signature('ARMO')}
    human = plugins.get_record_by_edid('ARMA', HUMAN)
    fox = next(cs[0] for h, cs in copies.values() if h.editor_id == HUMAN)
    for edid in (TRUCKER, 'Clothes_Resortwear_01'):
        pairs = addons(armos[edid].subrecords)
        at = [m for _i, m in pairs].index(ref(masters, human))
        assert pairs[at + 1] == (pairs[at][0], ref(masters, fox)), edid


def test_helmet_follows_the_human_helmet(fsf, copies):
    """On vanilla's outfit, so it holds whatever FSF.esm itself overrides."""
    _out, plugins, masters, _result = fsf
    vanilla = plugins.get_plugin('Starfield.esm').get_record_by_editor_id(HELMET_ARMO)
    pairs = addons(_with_copies(vanilla, vanilla.plugin, copies, masters, None))
    human = plugins.get_record_by_edid('ARMA', HELMET)
    at = [m for _i, m in pairs].index(ref(masters, human))
    assert pairs[at + 1] == (pairs[at][0], ref(masters, plugins.get_record_by_edid('ARMA', FOX_HELMET)))
    assert len(pairs) == len(addons(vanilla.subrecords)) + 1


def test_rest_of_the_outfit_is_the_winner(fsf):
    """Only the one INDX/MODL pair is new; a localized name and description become text."""
    out, plugins, _masters, _result = fsf
    armo = next(r for r in out.get_records_by_signature('ARMO') if r.editor_id == TRUCKER)
    winner = plugins.get_record_by_edid('ARMO', TRUCKER)
    got = [s.signature for s in armo.subrecords]
    want = [s.signature for s in winner.subrecords]
    at = got.index('MODL') + 2 * [m for _i, m in addons(winner.subrecords)].index(
        ref(['Starfield.esm'], plugins.get_record_by_edid('ARMA', HUMAN))) + 1
    assert got[:at] + got[at + 2:] == want
    assert bytes(armo.get_subrecord('FULL').data) == b'Space Trucker Casualwear\0'
    assert len(armo.get_subrecord('DESC').data) != 4
    assert int(armo.form_id.value) == int(winner.form_id.value)


def test_counts_and_notes(fsf):
    _out, _plugins, _masters, (counts, notes) = fsf
    assert counts['skin'] == 31
    assert counts['outfits'] >= counts['skin']
    assert not any('Trucker' in n for n in notes)
    # Only skin pieces are reported missing a copy: most helmets will never have one.
    assert not any('Helmet' in n for n in notes)


def test_rerun_adds_no_second_copy(fsf, copies):
    """An outfit that already lists the copy after the human piece (another patch did it) is left."""
    out, _plugins, masters, _result = fsf
    armo = next(r for r in out.get_records_by_signature('ARMO') if r.editor_id == TRUCKER)
    assert _with_copies(armo, armo.plugin, copies, masters, None) is None


def _as_races(rec, race_recs):
    """A copy of rec for the given races: the first as RNAM, the rest as additional races."""
    c = rec.copy()
    c.plugin = rec.plugin
    c.subrecords[:] = [s for s in c.subrecords if s.signature != 'MODL']
    rn = next(s for s in c.subrecords if s.signature == 'RNAM')
    rn.data = struct.pack('<I', int(race_recs[0].form_id.value))
    from esplib.record import SubRecord
    at = c.subrecords.index(rn) + 1
    c.subrecords[at:at] = [SubRecord('MODL', struct.pack('<I', int(r.form_id.value))) for r in race_recs[1:]]
    return c


def test_specific_copy_is_listed_last(fsf):
    """A copy shared by several races goes first, one for fewer races after it, so the specific
    one draws for its race."""
    _out, plugins, _masters, _result = fsf
    fox = plugins.get_record_by_edid('RACE', 'FSFFoxRace')
    crowd = plugins.get_record_by_edid('RACE', 'FSFFoxCrowdRace')
    piece = plugins.get_record_by_edid('ARMA', FOX_HELMET)
    shared, specific = _as_races(piece, [fox, crowd]), _as_races(piece, [crowd])
    race_keys = {_rec_key(fox), _rec_key(crowd)}
    ordered, notes = _order_copies([specific, shared], race_keys)
    assert ordered == [shared, specific]
    assert notes == []


def test_two_copies_for_the_same_races_are_reported(fsf):
    _out, plugins, _masters, _result = fsf
    fox = plugins.get_record_by_edid('RACE', 'FSFFoxRace')
    piece = plugins.get_record_by_edid('ARMA', FOX_HELMET)
    a, b = _as_races(piece, [fox]), _as_races(piece, [fox])
    _ordered, notes = _order_copies([a, b], {_rec_key(fox)})
    assert len(notes) == 1 and FOX_HELMET in notes[0]


CM = 'CM-MegaMod.esm'


@pytest.mark.skipif(not (game_data() / CM).exists(), reason=f'{CM} not installed')
def test_mod_changes_carried_forward():
    """CM-MegaMod overrides the trucker outfit (name, stats, mod slots): the override keeps them."""
    out, plugins, masters, (counts, _notes) = build(
        lambda data: load_order_for_plugin(data, CM) + ['FSF.esm'])
    armo = next(r for r in out.get_records_by_signature('ARMO') if r.editor_id == TRUCKER)
    cm = plugins.get_plugin(CM).get_record_by_editor_id(TRUCKER)
    for sig in ('FULL', 'DESC', 'DATA'):
        assert bytes(armo.get_subrecord(sig).data) == bytes(cm.get_subrecord(sig).data), sig
    assert len(armo.get_subrecords('OBTS')) == len(cm.get_subrecords('OBTS'))
    # Its mod slots name DLC mods, which become masters of the output; the header has them.
    assert 'sfbgs003.esm' in [m.lower() for m in masters]
    assert [m.lower() for m in out.header.masters] == [m.lower() for m in masters]
    assert counts['skin'] == 31
