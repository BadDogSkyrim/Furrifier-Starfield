"""Outfits with a human piece the furry race has its own copy of: list the copy right after it.

Some pieces don't suit a furry race as they are. A piece of bare human body (an ARMA flagged Is Skin
or Is Skin Hands: upper arms under a T-shirt, a hand) uses the human body material, so on a fox it
shows human skin; a helmet is shaped for a human head. A fox matches the human piece through its
race's Armor Race, and when two pieces match the same slot, the one listed last in the outfit draws
(in-game, 2026-11-12, arms and helmets). So the race plugin ships a copy of the piece for the race,
with its own nif, and the output lists the copy right after the human piece. Humans don't match the
copy, so nothing changes for them.

A copy is any ARMA that names one of the furry races (as its race or an additional race) and whose
EditorID is <prefix>_<the human piece's EditorID>, e.g. FSFFox_AA_Clothes_Trucker_Tee_01_Skin or
FSFCanine_AA_Spacesuit_CrimsonFleet_Charger_Helmet. The prefix isn't read: the races decide who
it's for. Adding a copy to the race plugin needs no change here.

A human piece can have several copies, e.g. one shared by all canine races and one for wolves only.
The copy for fewer races is listed later, so it draws for those races.

The outfit overrides start from each outfit's winning record, so other mods' changes to the outfit
(names, stats, mod slots) stay. That's why this is done per load order, not shipped in the race plugin.
"""
import struct
from pathlib import Path

from fsftools.formid_remap import Remapper, remap_record
from fsftools.plugin_loader import winning_records

IS_SKIN = 0x80
IS_SKIN_HANDS = 0x100


def _key(value: int, plugin) -> tuple[str, int]:
    """A reference as (home file, lowercased; object ID): the same record whichever file holds it."""
    from fsftools import formids
    return formids.key(value, plugin)


def _rec_key(rec):
    return _key(int(rec.form_id.value), rec.plugin)


def _u32(sub) -> int:
    return struct.unpack('<I', bytes(sub.data))[0]


def race_skins(plugins, order):
    """The races' own skins (their WNAM): a race's skin isn't an outfit, so it's left alone. The
    furry race's own body and hands do count as copies (FSFCanine_AA_Naked_Body for AA_Naked_Body),
    for an outfit that wears the human race's (Clothes_Naked_Body_SwimSuit)."""
    armos = set()
    for race in winning_records(plugins, 'RACE', order):
        wnam = race.get_subrecord('WNAM')
        if wnam is None or len(wnam.data) != 4 or not _u32(wnam):
            continue
        armos.add(_key(_u32(wnam), race.plugin))
    return armos


def _races_of(arma) -> set:
    """The races an ARMA names: its race and its additional races."""
    return {_key(_u32(s), arma.plugin) for s in arma.subrecords
            if s.signature in ('RNAM', 'MODL') and len(s.data) == 4}


def _race_keys(plugins, races: list[str]) -> set:
    keys = set()
    for edid in races:
        race = plugins.get_record_by_edid('RACE', edid)
        if race is None:
            raise ValueError(f"race {edid} isn't in the load order")
        keys.add(_rec_key(race))
    return keys


def _order_copies(copies: list, race_keys: set):
    """(copies in listing order, notes): those for more of the furry races first, so the one for
    fewer races is listed later and draws for them. Two copies for the same races are a mistake in
    the race plugin; they're noted and listed in load order."""
    ordered = sorted(copies, key=lambda c: -len(_races_of(c) & race_keys))
    notes = []
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            if _races_of(a) & race_keys == _races_of(b) & race_keys:
                notes.append(f"{a.editor_id} and {b.editor_id} are both copies for the same races: "
                             f"the later one draws")
    return ordered, notes


def race_copies(plugins, order, races: list[str], notes: list | None = None) -> dict[tuple[str, int], tuple]:
    """{human piece's key: (human piece, [its copies in listing order])}, for pieces that have a
    copy. Problems with the copies go on notes, if given."""
    race_keys = _race_keys(plugins, races)
    armas = list(winning_records(plugins, 'ARMA', order))
    # A piece for a furry race is never itself the human piece.
    human = {a.editor_id: a for a in armas if a.editor_id and not _races_of(a) & race_keys}
    found = {}
    for a in armas:
        if not _races_of(a) & race_keys:
            continue
        _prefix, _, rest = (a.editor_id or '').partition('_')
        target = human.get(rest)
        if target is None:
            continue
        found.setdefault(_rec_key(target), (target, []))[1].append(a)
    for key, (target, cs) in found.items():
        ordered, problems = _order_copies(cs, race_keys)
        found[key] = (target, ordered)
        if notes is not None:
            notes += problems
    return found


def _with_copies(armo, source, copies, masters, remapper, given=None):
    """The outfit's subrecords with each copy after its human piece, or None if nothing changes.

    An outfit's pieces are INDX/MODL pairs. Each copy gets its human piece's INDX. A copy already
    listed after its human piece (another patch put it there) isn't added twice. The human pieces
    that got a copy are appended to given, if passed."""
    subs = list(armo.subrecords)
    out, changed, i = [], False, 0
    while i < len(subs):
        s = subs[i]
        out.append(s)
        i += 1
        if s.signature != 'MODL' or len(s.data) != 4:
            continue
        hit = copies.get(_key(_u32(s), source))
        if hit is None:
            continue
        indx = out[-2] if len(out) >= 2 and out[-2].signature == 'INDX' else None
        if indx is None:
            raise ValueError(f"{armo.editor_id}: a piece without its INDX")
        following = set()
        j = i
        while j + 1 < len(subs) and subs[j].signature == 'INDX' and subs[j + 1].signature == 'MODL':
            following.add(_key(_u32(subs[j + 1]), source))
            j += 2
        for copy in hit[1]:
            if _rec_key(copy) in following:
                continue
            ref = copy_ref(copy, masters, remapper)
            out += [_new_sub('INDX', bytes(indx.data)), _new_sub('MODL', struct.pack('<I', ref))]
            changed = True
            if given is not None:
                given.append(hit[0])
    return out if changed else None


def copy_ref(copy, masters, remapper) -> int:
    """The copy as the output refers to it."""
    if remapper is None:
        from fsftools import formids
        home, obj = formids.decode(int(copy.form_id.value), copy.plugin)
        return formids.encoder_for(masters, copy.plugin.plugin_set).ref(home, obj)
    return remapper.remap(int(copy.form_id.value), copy.plugin)


def _new_sub(sig: str, data: bytes):
    from esplib.record import SubRecord
    return SubRecord(sig, data)


def _delocalize(rec, source, strings_for):
    """A localized source holds string IDs in FULL and DESC; the output isn't localized."""
    if not source.header.is_localized:
        return
    table = None
    for sub in rec.subrecords:
        if sub.signature not in ('FULL', 'DESC') or len(sub.data) != 4:
            continue
        if table is None:
            table = strings_for(source)
        string_id = struct.unpack('<I', bytes(sub.data))[0]
        text = table.get(string_id, '' if sub.signature == 'DESC' or string_id == 0 else rec.editor_id)
        sub.data = text.encode('utf-8') + b'\0'


def _is_skin(arma) -> bool:
    return bool(int(arma.flags) & (IS_SKIN | IS_SKIN_HANDS))


def add_race_pieces(out, plugins, order, masters: list[str], data_dir, races: list[str]):
    """Override every winning outfit holding a human piece that has a copy.

    masters is the output's list and grows if a winner needs another file. Returns (counts, notes):
    counts 'outfits' overridden, of which 'skin' got a skin piece and 'other' another piece (an
    outfit can be both). Only skin pieces with no copy are noted: most other pieces never get one."""
    from fsftools.string_table import load_all_string_tables
    tables = {}

    def strings_for(plugin):
        stem = Path(plugin.file_path).stem
        if stem not in tables:
            tables[stem] = load_all_string_tables(Path(data_dir), stem) if data_dir else {}
        return tables[stem]

    counts, notes = {'outfits': 0, 'skin': 0, 'other': 0}, []
    copies = race_copies(plugins, order, races, notes)
    skin_armos = race_skins(plugins, order)
    copy_keys = {_rec_key(c) for _h, cs in copies.values() for c in cs}
    remapper = Remapper(masters, plugins)
    used_without_copy = {}
    for armo in winning_records(plugins, 'ARMO', order):
        if _rec_key(armo) in skin_armos:
            continue
        source = armo.plugin
        rec = armo.copy()                 # its own subrecords: the loaded winner stays as it is
        rec.plugin = source               # the copy's references still read through its master list
        original = list(rec.subrecords)
        given = []
        try:
            new_subs = _with_copies(rec, source, copies, masters, remapper, given)
        except ValueError as e:
            notes.append(str(e))
            continue
        for s in armo.get_subrecords('MODL'):
            if len(s.data) == 4:
                used_without_copy.setdefault(_key(_u32(s), source), armo.editor_id)
        if new_subs is None:
            continue
        before = len(masters)
        try:
            # The inserted pieces are already in our numbering; remap only what came from the source.
            ours = {id(s) for s in original}
            inserted = [(s, bytes(s.data)) for s in new_subs if id(s) not in ours]
            rec.subrecords[:] = new_subs
            remap_record(rec, remapper, 'ARMO')
            for s, data in inserted:
                s.data = data
        except ValueError as e:
            del masters[before:]
            notes.append(f"{armo.editor_id} ({Path(source.file_path).name}): {e}")
            continue
        _delocalize(rec, source, strings_for)
        out.add_record(rec)
        counts['outfits'] += 1
        kinds = {_is_skin(h) for h in given}
        counts['skin'] += True in kinds
        counts['other'] += False in kinds

    # Human skin pieces in outfits with no copy, that a furry race matches through its Armor Race:
    # they still show human skin on it.
    armor_races = set()
    for edid in races:
        rnam = plugins.get_record_by_edid('RACE', edid).get_subrecord('RNAM')
        if rnam is not None and len(rnam.data) == 4:
            armor_races.add(_key(_u32(rnam), plugins.get_record_by_edid('RACE', edid).plugin))
    armas = {_rec_key(a): a for a in winning_records(plugins, 'ARMA', order) if _is_skin(a)}
    for key, outfit in used_without_copy.items():
        a = armas.get(key)
        if a is None or key in copies or key in copy_keys:
            continue
        piece_races = {_key(_u32(s), a.plugin) for s in a.subrecords
                       if s.signature in ('RNAM', 'MODL') and len(s.data) == 4}
        if piece_races & armor_races:
            notes.append(f"{a.editor_id} (in {outfit}) is a skin piece with no copy for "
                         f"{', '.join(races)}: shows human skin")

    out.header.masters = list(masters)
    out.header.master_sizes = [0] * len(masters)
    from fsftools import formids
    formids.settle(out, plugins)               # its FormIDs read by its masters' kinds
    return counts, notes
