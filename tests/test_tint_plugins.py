"""Each race reads its tint groups from its own tint plugin, whichever FSFPlayer_* is active.

The player plugins are alternatives -- one per race, never together -- and each defines the
global AVMD groups (Dermaesthetic, ComplexionMask1...) under the same names. A mod manager
deploys only the active one, so another race's tint plugin may exist only in its mod folder."""
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fsftools.race_data import (
    KIND_SIMPLE,
    avm_index,
    race_avm,
    tint_plugin_path,
    without_tint_plugins,
)


class Sub:
    def __init__(self, data):
        self.data = data


class Rec:
    def __init__(self, kind, tnam, label):
        self.editor_id = f"{kind}_{tnam}"
        self.subs = {'TNAM': Sub(tnam.encode() + b'\0'), 'MNAM': Sub(struct.pack('<I', kind))}
        self.label = label

    def get_subrecord(self, sig):
        return self.subs.get(sig)


class FakePlugin:
    def __init__(self, *recs):
        self.recs = list(recs)

    def get_records_by_signature(self, sig):
        return self.recs if sig == 'AVMD' else []


class FakeSet:
    def __init__(self, by_name):
        self.by_name = {k.lower(): v for k, v in by_name.items()}

    def get_plugin(self, name):
        return self.by_name.get(name.lower())


def test_each_race_sees_its_own_tint_plugin():
    vanilla = FakePlugin(Rec(KIND_SIMPLE, 'Dermaesthetic', 'vanilla'), Rec(KIND_SIMPLE, 'EyeColor', 'vanilla'))
    fox = FakePlugin(Rec(KIND_SIMPLE, 'Dermaesthetic', 'fox'))
    hyena = FakePlugin(Rec(KIND_SIMPLE, 'Dermaesthetic', 'hyena'))
    order = ['Starfield.esm', 'FSF.esm', 'FSFPlayer_HYENA.esm']          # hyena is the active option
    base_order = without_tint_plugins(order, ['FSFPlayer_FOX.esm', 'C:/Mods/Hyena/FSFPlayer_HYENA.esm'])
    assert base_order == ['Starfield.esm', 'FSF.esm'], "every race's tint plugin leaves the order"

    base = avm_index(FakeSet({'Starfield.esm': vanilla, 'FSFPlayer_HYENA.esm': hyena}), base_order)
    assert base[(KIND_SIMPLE, 'Dermaesthetic')].label == 'vanilla', "the active option doesn't leak in"
    for plugin, want in ((fox, 'fox'), (hyena, 'hyena')):
        avm = race_avm(base, plugin)
        assert avm[(KIND_SIMPLE, 'Dermaesthetic')].label == want
        assert avm[(KIND_SIMPLE, 'EyeColor')].label == 'vanilla', "the rest still comes from the order"
    assert base[(KIND_SIMPLE, 'Dermaesthetic')].label == 'vanilla', "the base index isn't changed"
    assert race_avm(base, None) == base, "no tint plugin: the load order's groups"


def test_tint_plugin_found_by_path_or_in_data(tmp_path):
    data = tmp_path / 'Data'
    data.mkdir()
    (data / 'FSFPlayer_FOX.esm').write_bytes(b'')
    mods = tmp_path / 'Mods' / 'FSFPlayer_Hyena'
    mods.mkdir(parents=True)
    (mods / 'FSFPlayer_HYENA.esm').write_bytes(b'')
    assert tint_plugin_path('FSFPlayer_FOX.esm', data) == data / 'FSFPlayer_FOX.esm'
    assert tint_plugin_path(str(mods / 'FSFPlayer_HYENA.esm'), data) == mods / 'FSFPlayer_HYENA.esm'
    with pytest.raises(ValueError, match='FSFPlayer_WOLF.esm'):
        tint_plugin_path('FSFPlayer_WOLF.esm', data)
