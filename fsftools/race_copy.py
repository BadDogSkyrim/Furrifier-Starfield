"""A new species from an existing one: copy the source species' own records, share the rest.

    python sf_race_copy.py <Data>/FSFTools/furrify/race_copies/FSFHyena.toml --out C:/tmp/sf_hyena/out

The config (see race_copies/FSFHyena.toml) names:
  copy.records    records the new species gets its own copy of, with a new FormID. Strings are
                  rewritten ([strings] exact, then [words] keeping case) and references to other copied
                  records point at their copies.
  copy.drop       a regex for list entries that don't carry over (AVMD entries, race morph groups and
                  phenotypes, NPC morph values); drop_records are left out, and references to them
                  removed.
  shared.records  records both species use: the new race is added wherever the source race is listed.
  player_from/to  the source's player plugin, rewritten the same way into the new species' one.

Writes the new main plugin and the new player plugin; the source player plugin is untouched. All
plugins go through esplib, which round-trips them byte for byte.
"""
import argparse
import fnmatch
import re
import struct
import sys
import tomllib
from pathlib import Path

from esplib import Plugin, SubRecord
from esplib.utils import FormID

# String subrecords rewritten in a copy, by record type. Others are binary or left alone.
STRING_SUBS = {
    'RACE': {'EDID', 'FULL', 'SNAM', 'BSTT', 'HSTT', 'FSTT', 'FCTP', 'MPGM', 'FMRU', 'FMRN', 'FMRS'},
    'AVMD': {'EDID', 'YNAM', 'TNAM', 'LNAM', 'VNAM'},
    'ARMA': {'EDID', 'MOD2', 'MOD3', 'MOD4', 'MOD5'},
    'ARMO': {'EDID', 'FULL'},
    'MRPH': {'EDID', 'TMPP'},
    'NPC_': {'EDID', 'FULL', 'TNAM', 'QNAM', 'VNAM', 'BMPN'},
    'FLST': {'EDID'},
    'CNDF': {'EDID'},
}
# Subrecords that start a list entry, and the subrecords that belong to it.
ENTRIES = {
    'AVMD': ('LNAM', {'VNAM', 'NNAM'}),
    'RACE': ('FMRI', {'FMRU', 'FMRN', 'FMRS'}),
    'NPC_': ('BMPN', {'BMPV'}),
}
# Single subrecords dropped when they match.
SINGLE_DROPS = {'RACE': {'MPGM'}}


def load_config(path) -> dict:
    with open(path, 'rb') as f:
        return tomllib.load(f)


def _u32(data: bytes) -> int:
    return struct.unpack('<I', data)[0]


def _string(sub) -> str:
    return bytes(sub.data).rstrip(b'\0').decode('cp1252')


def _set_string(sub, text: str):
    sub.data = text.encode('cp1252') + b'\0'


def _matches(edid: str, patterns) -> bool:
    return any(fnmatch.fnmatchcase(edid or '', p) for p in patterns)


class Rewriter:
    """Strings and references of the source species, rewritten for the new one."""

    def __init__(self, cfg):
        self.strings = cfg.get('strings', {})
        self.words = cfg.get('words', {})
        self.drop = re.compile(cfg['copy']['drop'], re.I) if cfg['copy'].get('drop') else None
        self.fids = {}              # source FormID -> new FormID
        self.dropped = set()        # source FormIDs left out
        self.dropped_names = set()  # their EditorIDs, for entries that name them

    def text(self, s: str) -> str:
        for old, new in self.strings.items():
            s = s.replace(old, new)
        for old, new in self.words.items():
            s = re.sub(re.escape(old), lambda m, new=new: _case_like(m.group(0), new), s, flags=re.I)
        return s

    def dropped_entry(self, strings) -> bool:
        return any((self.drop and self.drop.search(s)) or s in self.dropped_names for s in strings)

    def record(self, rec, rename_edid=True):
        """Rewrite rec in place: drop entries, rewrite strings, re-point references."""
        self._drop_entries(rec)
        subs = STRING_SUBS.get(rec.signature, set())
        for s in rec.subrecords:
            if s.signature in subs and (rename_edid or s.signature != 'EDID'):
                _set_string(s, self.text(_string(s)))
        self._repoint(rec)

    def _drop_entries(self, rec):
        start, members = ENTRIES.get(rec.signature, (None, set()))
        singles = SINGLE_DROPS.get(rec.signature, set())
        subs, out, removed, i = rec.subrecords, [], 0, 0
        while i < len(subs):
            s = subs[i]
            if s.signature == start:
                j = i + 1
                while j < len(subs) and subs[j].signature in members:
                    j += 1
                entry = subs[i:j]
                texts = [_string(e) for e in entry if e.signature not in ('NNAM', 'BMPV', 'FMRI')]
                if self.dropped_entry(texts):
                    removed += 1
                else:
                    out += entry
                i = j
                continue
            if s.signature in singles and self.dropped_entry([_string(s)]):
                i += 1
                continue
            if len(s.data) == 4 and _u32(s.data) in self.dropped and s.signature not in ('ITMC', 'NNAM'):
                i += 1                      # a reference to a record that doesn't carry over
                continue
            out.append(s)
            i += 1
        rec.subrecords[:] = out
        if removed and rec.signature == 'AVMD':
            itmc = rec.get_subrecord('ITMC')
            itmc.data = struct.pack('<I', _u32(itmc.data) - removed)

    def _repoint(self, rec):
        for s in rec.subrecords:
            d = bytearray(s.data)
            changed = False
            off = 0
            while off + 4 <= len(d):
                v = struct.unpack_from('<I', d, off)[0]
                if v in self.fids:
                    struct.pack_into('<I', d, off, self.fids[v])
                    changed = True
                    off += 4
                else:
                    off += 1
            if changed:
                s.data = bytes(d)


def _case_like(found: str, new: str) -> str:
    if found.isupper():
        return new.upper()
    if found[0].isupper():
        return new[0].upper() + new[1:]
    return new


def _own(plugin):
    own = len(plugin.header.masters)
    return [r for r in plugin if int(r.form_id.value) >> 24 == own]


def _add_race(rec, sig, race: int, insert_before, keep_sorted=True):
    """Add race as a sig subrecord, unless it's there: in sorted position among its kind, or last."""
    current = [_u32(s.data) for s in rec.get_subrecords(sig)]
    if race in current:
        return False
    subs = rec.subrecords
    positions = [i for i, s in enumerate(subs) if s.signature == sig]
    if positions:
        at = positions[-1] + 1
        if keep_sorted:
            at = next((i for i in positions if _u32(subs[i].data) > race), at)
    else:
        at = next((i for i, s in enumerate(subs) if s.signature in insert_before), len(subs))
    subs.insert(at, SubRecord(sig, struct.pack('<I', race)))
    return True


# Where Additional Races go in an ARMA when it has none yet: before what follows them.
_ARMA_AFTER_MODL = ('SNDD', 'ONAM', 'PNAM', 'MNAM', 'TNAM', 'SNAM', 'VNAM', 'BSMP')
_FLST_AFTER_LNAM = ('INAM', 'CITC', 'CTDA', 'ANAM')


def copy_species(main: Plugin, player: Plugin, cfg) -> dict:
    """Add the new species to main (in place) and turn player into the new species' player plugin.

    Returns a report: 'copied' source FormIDs, 'dropped' source FormIDs, 'new' FormIDs, 'shared' and
    'player_changed' EditorIDs."""
    rw = Rewriter(cfg)
    own = _own(main)
    index = len(main.header.masters) << 24
    by_edid = {r.editor_id: r for r in own}

    for fix in cfg.get('fix', []):
        _set_string(by_edid[fix['record']].get_subrecord(fix['sub']), fix['value'])

    drop_names = cfg['copy'].get('drop_records', [])
    for name in drop_names:
        rec = by_edid.get(name)
        if rec is not None:
            rw.dropped.add(int(rec.form_id.value))
        rw.dropped_names.add(name)
    sources = [r for r in own if _matches(r.editor_id, cfg['copy']['records'])
               and r.editor_id not in drop_names]

    # A copy an earlier run made (found by its new EditorID) is rewritten in place under its own
    # FormID, so running again updates the species instead of adding a second one, and other
    # plugins' references to it stay good.
    existing = {r.editor_id: r for r in own if r.editor_id}
    earlier = {}
    for src in sources:
        name = rw.text(src.editor_id)
        prior = existing.get(name) if name != src.editor_id else None
        if prior is not None and prior.signature == src.signature:
            earlier[int(src.form_id.value)] = prior
            rw.fids[int(src.form_id.value)] = int(prior.form_id.value)

    # The header's next ID can be behind the records (FSF.esm's was, 2026-11-16): never reuse one.
    next_id = max([main.header.next_object_id] + [(int(r.form_id.value) & 0xFFFFFF) + 1 for r in own])
    for src in sources:
        if int(src.form_id.value) not in earlier:
            rw.fids[int(src.form_id.value)] = index | next_id
            next_id += 1
    main.header.next_object_id = next_id
    copies = []
    for src in sources:
        rec = src.copy()
        rec.form_id = FormID(rw.fids[int(src.form_id.value)])
        rw.record(rec)
        prior = earlier.get(int(src.form_id.value))
        if prior is not None:
            prior.subrecords[:] = rec.subrecords
            prior.flags = rec.flags
        else:
            copies.append(rec)
    for rec in copies:
        main.add_record(rec)

    races = {int(by_edid[a].form_id.value): rw.fids[int(by_edid[a].form_id.value)]
             for a in cfg['races']}
    shared = []
    renames = cfg['shared'].get('rename', {})
    for rec in own:
        if not _matches(rec.editor_id, cfg['shared']['records']):
            continue
        edid = rec.get_subrecord('EDID')
        name = _string(edid)
        for old, new in renames.items():
            if name.startswith(old):
                _set_string(edid, new + name[len(old):])
        if rec.signature == 'ARMA':
            listed = set(_u32(s.data) for s in rec.subrecords if s.signature in ('RNAM', 'MODL'))
            for src, new in races.items():
                if src in listed:
                    _add_race(rec, 'MODL', new, _ARMA_AFTER_MODL)
        elif rec.signature == 'FLST':
            listed = set(_u32(s.data) for s in rec.get_subrecords('LNAM'))
            for src, new in races.items():
                if src in listed:
                    # The fox's list isn't sorted (the fox before HumanRace): append.
                    _add_race(rec, 'LNAM', new, _FLST_AFTER_LNAM, keep_sorted=False)
        shared.append(_string(edid))

    # The player plugin: overrides of copied records become overrides of their copies; overrides of
    # dropped ones go; the rest (vanilla records) are rewritten but keep their EditorIDs.
    # References are re-pointed by value, so main's records must read the same in both plugins.
    masters = [m.lower() for m in player.header.masters]
    if masters.index(cfg['plugin'].lower()) != len(main.header.masters):
        raise ValueError(f"{cfg['player_from']} doesn't list {cfg['plugin']} after its masters")
    keep = set(cfg.get('player', {}).get('keep', []))
    changed = []
    for rec in list(player):
        fid = int(rec.form_id.value)
        home = fid >> 24
        is_main = home < len(player.header.masters) and \
            player.header.masters[home].lower() == cfg['plugin'].lower()
        local = (index | (fid & 0xFFFFFF)) if is_main else None
        if local is not None and local in rw.dropped:
            player.remove_record(rec)
            continue
        if rec.editor_id in keep:
            continue
        if local is not None and local in rw.fids:
            rw.record(rec)
            rec.form_id = FormID((fid & 0xFF000000) | (rw.fids[local] & 0xFFFFFF))
        else:
            rw.record(rec, rename_edid=False)
        changed.append(rec.editor_id)

    return {'copied': list(rw.fids), 'dropped': sorted(rw.dropped), 'new': set(rw.fids.values()),
            'shared': shared, 'player_changed': set(changed)}


def main(argv=None):
    from fsftools.plugin_loader import discover_data_dir
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('config')
    p.add_argument('--out', required=True, help='folder for the new plugins (not the game Data)')
    p.add_argument('--data', help='game Data folder (default: found from the install)')
    args = p.parse_args(argv)
    cfg = load_config(args.config)
    data = Path(args.data) if args.data else discover_data_dir()
    out = Path(args.out)
    if out.resolve() == data.resolve():
        print("ERROR: --out must not be the game's Data folder; swap the plugins in yourself.")
        return 2
    out.mkdir(parents=True, exist_ok=True)
    main_plugin = Plugin.load(data / cfg['plugin'])
    player = Plugin.load(data / cfg['player_from'])
    report = copy_species(main_plugin, player, cfg)
    main_plugin.save(out / cfg['plugin'])
    player.save(out / cfg['player_to'])
    print(f"{cfg['plugin']}: {len(report['new'])} new records, {len(report['shared'])} shared records "
          f"extended; {len(report['dropped'])} source records not carried over")
    print(f"{cfg['player_to']}: {len(report['player_changed'])} records")
    print(f"Written to {out}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
