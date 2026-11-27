"""Rewrite an NPC's FormIDs for our plugin, when its winning record is in a DLC or a mod.

A FormID's top byte names a master of the file holding it, or the file itself, by Starfield's
numbering by kind (fsftools.formids). Starfield.esm is 0 everywhere, so a vanilla reference needs
nothing. Any other has to be decoded through the source file's list and encoded for ours, which
grows to hold it.

There's no sf1 schema in esplib, so the fields come from the sf1 NPC_ and ARMO definitions, checked
against every NPC and outfit in the game. A reference we don't know about would quietly point at something else, so any other
subrecord holding what could be one refuses that NPC, unless the definition says it holds none.
"""
import struct
from pathlib import Path
from typing import List

from fsftools import formids

# Subrecord -> (bytes per entry, offsets of the references in an entry).
_ONE = (4, (0,))
_FIELDS = {sig: _ONE for sig in ('ATKR', 'SPOR', 'OCOR', 'GWOR', 'ECOR', 'FCPL', 'RCLR', 'RPLD', 'RPLI', 'PKID',
                                 'CNAM', 'PNAM', 'ZNAM', 'CSCR', 'QSTA', 'BNAM', 'DOFT', 'SOFT', 'DPLT', 'CRIF',
                                 'HEFA', 'TPLT', 'LTPT', 'LTPC', 'INAM', 'VTCK', 'RNAM', 'WNAM', 'CS3K', 'SPLO',
                                 'KWDA', 'APPR', 'TPTA', 'STCP', 'FTYP')}
_FIELDS.update({'SNAM': (5, (0,)),            # faction, rank
                'PRKR': (5, (0,)),            # perk, rank
                'CNTO': (8, (0,)),            # item, count
                'PRPS': (12, (0, 8)),         # actor value, value, curve table
                'FLEE': (24, (0, 4, 8))})     # three globals, three floats

# Numbers and hashes that can look like references, by the definition.
_NO_REFS = {'ACBS', 'DNAM', 'ONA2', 'CS3S',
            'AIDT'}     # AI data: seven one-byte numbers

# ARMO, for outfits given the race's copy of a piece (race_pieces). Same rules as NPC_.
_ARMO_FIELDS = {sig: _ONE for sig in ('RNAM', 'MODL', 'EITM', 'BAMT', 'BIDS', 'ETYP', 'INRD', 'KWDA',
                                      'APPR')}
_ARMO_FIELDS.update({'PTT2': (32, tuple(range(0, 32, 4))),    # eight transforms
                     'DAMA': (12, (0, 8))})                    # damage type, amount, curve table
_ARMO_NO_REFS = {'OBND', 'ODTY', 'FULL', 'DESC', 'BO64', 'KSIZ', 'INDX', 'DATA', 'FNAM', 'FLLD', 'XFLG',
                 'MO2F', 'MO4F', 'OBTE', 'OBTF', 'STOP', 'AFSG', 'AVSG'}   # FULL/DESC: string IDs
# MLM2/MLM4, the models' material swaps: a u16 count, then the LMSW FormIDs.
_COUNTED_ARRAYS = {'MLM1', 'MLM2', 'MLM3', 'MLM4'}

_TABLES = {'NPC_': (_FIELDS, _NO_REFS), 'ARMO': (_ARMO_FIELDS, _ARMO_NO_REFS)}

# OBTS, the object template's item: include and property counts, levels, parent, default, a one-byte
# keyword count, the keywords, two bytes, then its includes and properties. This adds up on all 6577
# OBTS in the load order (2026-11-13; 1440 with a keyword, every one a KYWD), with every include an
# OMOD and every FormID property value a record.
_OBTS_KEYWORD_COUNT = 15
_OBTS_INCLUDES = 18
_OBTS_INCLUDE = 7
_OBTS_PROPERTY = 24
_OBTS_VALUE_1 = 12              # within a property
_OBTS_FORM_TYPES = (4, 6)       # the property's value type: FormID,Int and FormID,Float


def _name(plugin) -> str:
    return Path(plugin.file_path).name


def _home_name(value: int, plugin) -> str:
    return formids.home(value, plugin)


def _loaded(plugins, name):
    """The loaded plugin by name. Master lists spell names in any case, and asking a PluginSet for a
    different spelling reads the file again as a separate plugin."""
    order = getattr(getattr(plugins, 'load_order', None), 'plugins', None) or []
    for candidate in order:
        if candidate.lower() == name.lower():
            return plugins.get_plugin(candidate)
    return plugins.get_plugin(name)


def defining_plugin(rec, plugins):
    """The file a record's FormID belongs to, which an override's winner isn't."""
    home = _home_name(int(rec.form_id.value), rec.plugin)
    found = _loaded(plugins, home)
    if found is None:
        raise ValueError(f"{home} isn't loaded")
    return found


class Remapper:
    """Translates references into the output's master list, adding masters as they're needed."""

    def __init__(self, masters: List[str], plugins):
        self.masters = masters       # the caller's list, which this extends
        self.plugins = plugins
        self.encoder = formids.encoder_for(masters, plugins)

    def _index(self, home: str) -> int:
        lowered = [m.lower() for m in self.masters]
        if home.lower() in lowered:
            return lowered.index(home.lower())
        found = _loaded(self.plugins, home)
        if found is None:
            raise ValueError(f"a reference needs {home}, which isn't loaded")
        self.masters.append(_name(found))
        return len(self.masters) - 1

    def remap(self, value: int, source) -> int:
        if value == 0:
            return 0
        home, obj = formids.decode(value, source)
        return self.encoder.at(self._index(home), obj)


def _could_be_reference(value: int, source) -> bool:
    """Would this value change if it were a reference? A vanilla one is right as it stands."""
    return formids.could_be_reference(value, source)


def _remap_at(new: bytearray, off: int, remapper, source):
    struct.pack_into('<I', new, off, remapper.remap(struct.unpack_from('<I', new, off)[0], source))


def _remap_obts(data: bytes, remapper, source) -> bytes:
    """The includes' mods and the properties' FormID values."""
    if len(data) < _OBTS_INCLUDES:
        raise ValueError(f"OBTS is {len(data)} bytes")
    keywords = data[_OBTS_KEYWORD_COUNT]
    at_includes = _OBTS_INCLUDES + 4 * keywords
    includes, properties = struct.unpack_from('<II', data, 0)
    at_properties = at_includes + _OBTS_INCLUDE * includes
    if at_properties + _OBTS_PROPERTY * properties != len(data):
        raise ValueError(f"OBTS doesn't add up: {keywords} keywords, {includes} includes, "
                         f"{properties} properties in {len(data)} bytes")
    new = bytearray(data)
    for i in range(keywords):
        _remap_at(new, _OBTS_KEYWORD_COUNT + 1 + 4 * i, remapper, source)
    for i in range(includes):
        _remap_at(new, at_includes + _OBTS_INCLUDE * i, remapper, source)
    for i in range(properties):
        at = at_properties + _OBTS_PROPERTY * i
        if data[at] in _OBTS_FORM_TYPES:
            _remap_at(new, at + _OBTS_VALUE_1, remapper, source)
    return bytes(new)


def _remap_vmad(data: bytes, remapper, source, record_sig='NPC_') -> bytes:
    from esplib.vmad import VmadData
    vmad = VmadData.parse(data, record_sig)
    if vmad.to_bytes(record_sig) != data:
        raise ValueError("its scripts (VMAD) don't read back the same")
    vmad.remap_form_ids(lambda v: remapper.remap(v, source))
    return vmad.to_bytes(record_sig)


def _remap_counted(data: bytes, remapper, source) -> bytes:
    count = struct.unpack_from('<H', data, 0)[0] if len(data) >= 2 else -1
    if len(data) != 2 + 4 * count:
        raise ValueError(f"a {len(data)}-byte material swap list doesn't hold its count")
    new = bytearray(data)
    for i in range(count):
        _remap_at(new, 2 + 4 * i, remapper, source)
    return bytes(new)


def _remap_sub(sub, remapper, source, record_sig='NPC_'):
    """The subrecord's new bytes, or None if it holds no references."""
    fields, no_refs = _TABLES[record_sig]
    data = bytes(sub.data)
    if sub.signature == 'VMAD':
        return _remap_vmad(data, remapper, source, record_sig)
    if sub.signature == 'OBTS':
        return _remap_obts(data, remapper, source)
    if record_sig == 'ARMO' and sub.signature in _COUNTED_ARRAYS:
        return _remap_counted(data, remapper, source)
    field = fields.get(sub.signature)
    if field is None:
        if sub.signature not in no_refs:
            for off in range(0, len(data) - 3, 4):
                if _could_be_reference(struct.unpack_from('<I', data, off)[0], source):
                    raise ValueError(f"{sub.signature} holds what may be a reference, which this tool can't rewrite")
        return None
    size, offsets = field
    if not data or len(data) % size:
        raise ValueError(f"{sub.signature} is {len(data)} bytes, not a multiple of {size}")
    new = bytearray(data)
    for entry in range(0, len(data), size):
        for off in offsets:
            _remap_at(new, entry + off, remapper, source)
    return bytes(new)


def remap_record(rec, remapper, record_sig):
    """Rewrite the record's own FormID and every reference in it, in place. Nothing changes unless the
    whole record is accepted; masters a refused record added are harmless, and it is left out."""
    source = rec.plugin
    edits = [(sub, _remap_sub(sub, remapper, source, record_sig)) for sub in rec.subrecords]
    for sub, data in edits:
        if data is not None:
            sub.data = data
    own = remapper.remap(int(rec.form_id.value), source)
    if hasattr(rec, 'normalize_form_id'):
        from esplib.utils import FormID
        rec.form_id = FormID(own)
    else:
        rec.form_id = own


def remap_npc(npc, remapper):
    remap_record(npc, remapper, 'NPC_')
