"""Write the output plugin — apply NpcChange records to produce an ESM.

Records are edited by rebuilding their subrecord lists in place. esplib's add/remove methods mark
a record modified, and a modified record is re-sorted into esplib's schema order on save, which
moves NPC_ ODTY and EDCT to the wrong place.
"""
import struct
from pathlib import Path
from typing import Callable, Dict, List, Optional

from fsftools.formid_remap import Remapper, remap_npc
from fsftools.furrify_npc import NpcChange

_FLOAT_ONE = struct.pack('<f', 1.0)

# NPC_ subrecords that follow the head parts, and those that follow FHCL (sf1 NPC_ definition).
_AFTER_PNAM = ('ZNAM', 'NAM5')
_AFTER_FHCL = ('BCOL', 'ECOL', 'JCOL', 'TETC', 'PRON', 'ONA2')


def _z(s: str) -> bytes:
    return s.encode('utf-8') + b'\x00'


def _plugin_name(plugin) -> str:
    return Path(plugin.file_path).name


def _output_form_id(rec, masters: List[str]) -> int:
    """rec's FormID as the output plugin writes it: its home file's index in our master list."""
    plugin = rec.plugin
    value = int(rec.form_id.value)
    index = value >> 24
    source_masters = list(plugin.header.masters)
    home = source_masters[index] if index < len(source_masters) else _plugin_name(plugin)
    lowered = [m.lower() for m in masters]
    if home.lower() not in lowered:
        raise ValueError(f"{rec.editor_id} lives in {home}, which is not a master of the output")
    return (lowered.index(home.lower()) << 24) | (value & 0xFFFFFF)


def write_output(out_path: Path, changes: List[NpcChange], plugins, masters: List[str],
                 data_dir: Path = None, verbose: bool = False, extend: Optional[Callable] = None):
    """Create the output ESM with NPC_ overrides.

    plugins: the loaded PluginSet (for resolving race FormIDs)
    masters: master list for the output plugin; grows if a winning record needs another file
    data_dir: game Data directory (for loading string tables)
    extend: called with the plugin before it's saved, to add other records
    """
    from esplib.plugin import Plugin
    from fsftools.string_table import load_all_string_tables

    # String IDs belong to the plugin holding the record, so each has its own table.
    tables: Dict[str, Dict[int, str]] = {}

    def strings_for(plugin) -> Dict[int, str]:
        stem = Path(plugin.file_path).stem
        if stem not in tables:
            tables[stem] = load_all_string_tables(data_dir, stem) if data_dir else {}
            print(f"  Loaded {len(tables[stem])} strings from {stem}")
            if not tables[stem]:
                print(f"  WARNING: no string table for {stem}: its FULL/SHRT will use the EditorID")
        return tables[stem]

    # Create output plugin (manual construction — esplib has no sf1 schema)
    out = Plugin()
    out.file_path = Path(out_path)
    out.header.version = 0.96  # Starfield
    out.header.masters = list(masters)
    out.header.master_sizes = [0] * len(masters)
    out.header.is_esl = True
    out.header.is_esm = True
    # NOT localized — we delocalize FULL/SHRT to inline strings per NPC
    out.header.author = 'Bad Dog (SF Furrifier)'
    out.header.next_object_id = 0x800

    # Resolve race FormIDs once
    race_ids: Dict[str, int] = {}
    for change in changes:
        if change.new_race_edid not in race_ids:
            race_rec = plugins.get_record_by_edid('RACE', change.new_race_edid)
            if race_rec is None:
                raise ValueError(f"race {change.new_race_edid} not found in load order")
            race_ids[change.new_race_edid] = _output_form_id(race_rec, masters)

    remapper = Remapper(masters, plugins)
    written = 0
    errors = []
    for change in changes:
        try:
            out.add_record(_build_override(change, race_ids, strings_for, masters, remapper))
            written += 1
            change.written = True
            if verbose:
                print(f"  {change.npc_editorid} -> {change.new_race_edid}/{change.breed_name}")
        except ValueError as e:
            errors.append(f"{change.npc_editorid}: {e}")

    out.header.masters = list(masters)
    out.header.master_sizes = [0] * len(masters)
    if extend:
        extend(out)
    # Saved whole or not at all: a stopped run leaves the last plugin, never half of one.
    from fsftools import safe_write
    with safe_write.replacing(out_path) as scratch:
        out.save(scratch)
        # Post-save: patch the light flag for Starfield (0x200 -> 0x100)
        _patch_sf_light_flag(scratch)

    print(f"Wrote {out_path}: {written} NPC overrides, {len(errors)} errors")
    for line in errors[:20]:
        print(f"  ERROR {line}")
    if len(errors) > 20:
        print(f"  ... and {len(errors) - 20} more")
    return written, len(errors)


def _build_override(change: NpcChange, race_ids, strings_for, masters: List[str], remapper):
    """The override for one NPC, from its winning record wherever that is."""
    source = change.source
    npc = source.copy()
    npc.plugin = source.plugin        # the copy's references still read through its master list
    remap_npc(npc, remapper)
    subs = npc.subrecords

    rnam = npc.get_subrecord('RNAM')
    if rnam is None:
        raise ValueError("no RNAM")
    rnam.data = struct.pack('<I', race_ids[change.new_race_edid])

    # A localized source holds 4-byte string IDs; output doesn't. Fall back to the EditorID.
    if source.plugin.header.is_localized:
        for sig in ('FULL', 'SHRT'):
            sr = npc.get_subrecord(sig)
            if sr is not None and len(sr.data) == 4:
                string_id = struct.unpack_from('<I', sr.data, 0)[0]
                sr.data = _z(strings_for(source.plugin).get(string_id, change.npc_editorid))

    _clear_traits_template(npc)

    # Drop WNAM so the race skin applies
    subs[:] = [s for s in subs if s.signature != 'WNAM']

    _write_head_parts(npc, change, masters)
    _write_appearance_block(npc, change)
    _write_tail(npc, change)
    assert not npc.modified, change.npc_editorid  # see the module docstring
    return npc


def _new_sub(sig: str, data: bytes):
    from esplib.record import SubRecord
    return SubRecord(sig, data)


def _write_head_parts(npc, change, masters):
    """Head parts are PNAMs on an NPC_ (HEAD is the RACE's signature). A sorted array in the spec."""
    subs = npc.subrecords
    sigs = [s.signature for s in subs]
    if 'PNAM' in sigs:
        at = sigs.index('PNAM')
    else:
        at = next((i for i, s in enumerate(sigs) if s in _AFTER_PNAM), None)
        if at is None:
            raise ValueError("no place for head parts: no ZNAM or NAM5")
    ids = sorted({_output_form_id(h, masters) for h in change.head_parts})
    kept_before = [s for s in subs[:at] if s.signature != 'PNAM']
    kept_after = [s for s in subs[at:] if s.signature != 'PNAM']
    subs[:] = kept_before + [_new_sub('PNAM', struct.pack('<I', i)) for i in ids] + kept_after


def _write_appearance_block(npc, change):
    """Everything from EDCT up to STON, in spec order: tints, MRSV, FMRI, BMPN, ATTX.

    All 7131 vanilla NPCs have EDCT and STON, and the vanilla face arrays are replaced wholesale.
    Scoping the edit to this span keeps MNAM/QNAM/etc. elsewhere in the record safe.
    """
    subs = npc.subrecords
    sigs = [s.signature for s in subs]
    if 'EDCT' not in sigs or 'STON' not in sigs:
        raise ValueError("no EDCT/STON")
    start, stop = sigs.index('EDCT'), sigs.index('STON')
    kept = {s.signature: s for s in subs[start:stop] if s.signature in ('MRSV', 'ATTX')}

    block = [_new_sub('EDCT', bytes([len(change.tints)]))]
    for tint in change.tints:
        block += [_new_sub('MNAM', struct.pack('<I', 1)),  # Simple group
                  _new_sub('TNAM', _z(tint.slot)),
                  _new_sub('QNAM', _z(tint.option)),
                  _new_sub('VNAM', _z(tint.texture)),
                  _new_sub('NNAM', tint.color),
                  _new_sub('INTV', struct.pack('<I', tint.intensity))]
    if 'MRSV' in kept:
        block.append(kept['MRSV'])
    if change.phenotype_id is not None:
        block.append(_new_sub('FMRI', struct.pack('<I', change.phenotype_id)))
        for region in change.face_regions:
            block += [_new_sub('FMRG', _z(region)), _new_sub('FMRS', _FLOAT_ONE)]
    for key in sorted(change.morph_groups):
        block += [_new_sub('BMPN', _z(key)), _new_sub('BMPV', struct.pack('<f', change.morph_groups[key]))]
    if 'ATTX' in kept:
        block.append(kept['ATTX'])
    subs[start:stop] = block


def _write_tail(npc, change):
    """STON, and the facial-hair colour if a part was picked."""
    npc.get_subrecord('STON').data = bytes([change.new_ston])
    if change.facial_hair_color is None:
        return
    fhcl = npc.get_subrecord('FHCL')
    if fhcl is not None:
        fhcl.data = _z(change.facial_hair_color)
        return
    subs = npc.subrecords
    at = next((i for i, s in enumerate(subs) if s.signature in _AFTER_FHCL), len(subs))
    subs.insert(at, _new_sub('FHCL', _z(change.facial_hair_color)))


def _clear_traits_template(npc):
    """Clear the Traits bit in the ACBS template flags.

    ACBS is a packed struct; the template flags are a u16 at offset 14.
    Traits is bit 0 of that u16 (per sf1.pas TPTA order).
    """
    acbs = npc.get_subrecord('ACBS')
    if acbs is None:
        return
    data = bytearray(acbs.data)
    if len(data) >= 16:
        flags = struct.unpack_from('<H', data, 14)[0]
        flags &= ~0x0001  # clear Traits bit
        struct.pack_into('<H', data, 14, flags)
        acbs.data = bytes(data)


def _patch_sf_light_flag(path: Path):
    """Post-save: replace esplib's FO4 light flag (0x200) with SF's (0x100)."""
    with open(path, 'r+b') as f:
        head = f.read(12)
        flags = struct.unpack_from('<I', head, 8)[0]
        # Clear FO4 ESL (0x200), set SF master (0x01) + light (0x100)
        new_flags = (flags & ~0x200) | 0x101
        f.seek(8)
        f.write(struct.pack('<I', new_flags))
