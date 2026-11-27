"""FormIDs in Starfield plugin files: which file one names, and how to write one.

A Starfield plugin numbers its masters by kind, not by position (measured on CK-written plugins,
2026-11-26; esplib Plugin.decode_form_id / encode_form_id do it):

    full master     its number among the full masters
    own records     the count of full masters, also in a small plugin
    small master    FE + 12-bit small-master number + 12-bit object
    medium master   FD + 8-bit medium-master number + 16-bit object

So a FormID's top byte is NOT the master's position once a plugin has a small or medium master
(FSFHair.esm, SFBGS003.esm...). Writing positions pointed FSFNPC.esm's hair at SFBGS00D's records.
Every FSFTools reader and writer goes through here, so there's one encoding.

Appending a master never changes how the earlier ones are written. The plugin's own index does
change, when a full master is appended, so write own references once the masters have settled.
"""
from pathlib import Path
from typing import List, Optional, Tuple


def file_name(plugin) -> str:
    return Path(plugin.file_path).name


def _decoded(value: int, plugin):
    """esplib's decode, its errors as ValueError: the writers refuse one NPC on a ValueError rather
    than stopping the run."""
    from esplib.exceptions import PluginError
    try:
        return plugin.decode_form_id(value)
    except PluginError as e:
        raise ValueError(str(e)) from None


def decode(value: int, plugin) -> Tuple[str, int]:
    """(the file a FormID in `plugin` belongs to, its object ID)."""
    index, obj = _decoded(value, plugin)
    return (plugin.header.masters[index] if index is not None else file_name(plugin)), obj


def home(value: int, plugin) -> str:
    """The file a FormID in `plugin` belongs to."""
    return decode(value, plugin)[0]


def object_id(value: int, plugin) -> int:
    return decode(value, plugin)[1]


def key(value: int, plugin) -> Tuple[str, int]:
    """(home file lowered, object ID): the record a FormID names, whichever file it's read from."""
    name, obj = decode(value, plugin)
    return name.lower(), obj


def is_own(value: int, plugin) -> bool:
    """Does a FormID in `plugin` name one of the plugin's own records?"""
    return _decoded(value, plugin)[0] is None


def own_records(plugin) -> list:
    return [r for r in plugin if is_own(int(r.form_id.value), plugin)]


def could_be_reference(value: int, plugin) -> bool:
    """Could this value be a reference into anything but Starfield.esm (whose index 0 never
    changes)? For telling numbers from references the field tables don't know."""
    hi = value >> 24
    if hi in (0xFE, 0xFD):
        try:
            plugin.decode_form_id(value)
        except Exception:
            return False
        return True
    return 1 <= hi <= plugin.own_file_index() and value & 0xFFFFFF >= 0x800


class Encoder:
    """Writes FormIDs for a plugin whose master list is `masters`: a list the caller keeps, which
    may grow. A master's kind comes from its header, through `plugins` (the PluginSet)."""

    def __init__(self, masters: List[str], plugins):
        from esplib import Plugin
        self.masters = masters
        self._codec = Plugin()
        self._codec.header.version = 0.96
        self._codec.header.masters = masters          # the same list: appends show
        self._codec.plugin_set = plugins

    def index(self, name: str) -> Optional[int]:
        lowered = [m.lower() for m in self.masters]
        return lowered.index(name.lower()) if name.lower() in lowered else None

    def at(self, index: int, obj: int) -> int:
        """A reference to object `obj` of the master at position `index` in the list."""
        from esplib.exceptions import PluginError
        try:
            return self._codec.encode_form_id(index, obj)
        except PluginError as e:
            raise ValueError(str(e)) from None

    def ref(self, name: str, obj: int) -> int:
        """A reference to object `obj` of master `name`, which must be in the list."""
        i = self.index(name)
        if i is None:
            raise ValueError(f"{name} is not a master of the output")
        return self.at(i, obj)

    def own(self, obj: int) -> int:
        """A reference to the plugin's own object `obj`, by the masters as they are now."""
        return self._codec.encode_form_id(None, obj)

    def own_index(self) -> int:
        return self._codec.own_file_index()

    def kind(self, name: str) -> str:
        return self._codec.master_kind(name)

    def reencode(self, value: int, source) -> int:
        """A FormID read from `source`, as this plugin writes it. Its home must be a master."""
        name, obj = decode(value, source)
        return self.ref(name, obj)


_encoders = {}


def encoder_for(masters: List[str], plugins) -> Encoder:
    """The Encoder for this master list (the same list object), made once."""
    found = _encoders.get(id(masters))
    if found is None or found.masters is not masters:
        found = _encoders[id(masters)] = Encoder(masters, plugins)
    return found


def settle(out, plugins) -> None:
    """Tell `out` each master's kind, before it's saved: esplib stamps the plugin's own FormIDs at
    save time, and in Starfield that needs the count of full masters. The masters are in Data,
    not beside an output written somewhere else."""
    enc = Encoder(list(out.header.masters), plugins)
    for name in out.header.masters:
        out.set_master_kind(name, enc.kind(name))
