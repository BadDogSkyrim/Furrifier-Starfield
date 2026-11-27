"""NPCs whose winning record is in a DLC or a mod: their FormIDs have to be rewritten for our plugin.

A FormID's top byte indexes the master list of the file it's in, and those lists differ. The real
ones run the CLI on the active load order, so they need the DLCs they name to be active.
"""
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
from fsfdata import BUILTIN, RACES, SCHEME, game_data  # noqa: E402
sys.path.insert(0, str(ROOT))
from fsftools.formid_remap import Remapper, defining_plugin, remap_npc  # noqa: E402
from fsftools.plugin_loader import load_full_order  # noqa: E402
from fsftools.string_table import load_all_string_tables  # noqa: E402

NPCS = ['UC_NA_Muria', 'UC_CY_TrackersAllianceAgent', 'SFBGS001_LvlVaruun_BECrew_Crew',
        'SFBGS001_CREW_Elite_SahimaKadic', 'SFBGS001_Crew_LvlCrew_Any', 'SFTER_LvlTerran_BECrew_Captain',
        'SFTER_INC_CaptiveF01', 'SFBGS001_HV_AnaskoVaruun', 'FC_Neon_GenericCustomerM01']
EXPECT_DLC = {'UC_NA_Muria': 'SFBGS00D.esm', 'SFBGS001_LvlVaruun_BECrew_Crew': 'ShatteredSpace.esm',
              'SFTER_LvlTerran_BECrew_Captain': 'SFBGS050.esm'}


def FakePlugin(name, masters, kind='full'):
    """A Starfield plugin with no records: its name, masters and kind are all the remapper reads
    (FormIDs decode by Starfield's numbering, which needs each master's kind)."""
    from esplib import Plugin
    p = Plugin()
    p.file_path = Path(name)
    p.header.version = 0.96
    p.header.masters = list(masters)
    p.header.is_esl = kind == 'small'
    p.header.is_medium = kind == 'medium'
    return p


class FakeSet:
    def __init__(self, *plugins):
        self.by_name = {p.file_path.name.lower(): p for p in plugins}
        self._plugins = {p.file_path.name: p for p in plugins}
        for p in plugins:
            p.plugin_set = self

    def get_plugin(self, name):
        return self.by_name.get(name.lower())

    def _resolve_plugin_path(self, name):
        return None


VANILLA = FakePlugin('Starfield.esm', [])
FSF = FakePlugin('FSF.esm', ['Starfield.esm'])
DLC = FakePlugin('SFBGS00D.esm', ['starfield.esm'])
LATE = FakePlugin('SFBGS050.esm', ['starfield.esm', 'sfbgs00d.esm'])


def remapper():
    return Remapper(['Starfield.esm', 'FSF.esm'], FakeSet(VANILLA, FSF, DLC, LATE))


def test_a_vanilla_reference_is_unchanged_whatever_the_case_of_the_name():
    r = remapper()
    assert r.remap(0x00123456, DLC) == 0x00123456
    assert r.masters == ['Starfield.esm', 'FSF.esm']


def test_a_null_reference_stays_null():
    assert remapper().remap(0, LATE) == 0


def test_a_dlc_s_own_record_adds_it_as_a_master():
    r = remapper()
    assert r.remap(0x01000900, DLC) == 0x02000900
    assert r.masters == ['Starfield.esm', 'FSF.esm', 'SFBGS00D.esm']


def test_a_reference_through_a_dlc_s_masters_finds_the_right_file():
    r = remapper()
    assert r.remap(0x02000900, LATE) == 0x02000900, "index 2 is SFBGS050 itself"
    assert r.masters == ['Starfield.esm', 'FSF.esm', 'SFBGS050.esm']
    assert r.remap(0x01000901, LATE) == 0x03000901, "index 1 is SFBGS00D"
    assert r.masters == ['Starfield.esm', 'FSF.esm', 'SFBGS050.esm', 'SFBGS00D.esm']


def test_a_reference_to_a_file_not_loaded_is_refused():
    with pytest.raises(ValueError, match='nothing.esm'):
        remapper().remap(0x01000900, FakePlugin('x.esm', ['Starfield.esm', 'nothing.esm']))


class FakeForm:
    def __init__(self, value):
        self.value = value


class FakeRecord:
    def __init__(self, plugin, value):
        self.plugin = plugin
        self.form_id = FakeForm(value)


def test_a_differently_spelled_master_is_not_read_again():
    class Order:
        plugins = ['Starfield.esm']

    class Strict(FakeSet):
        load_order = Order

        def get_plugin(self, name):
            assert name == 'Starfield.esm', name
            return VANILLA

    assert defining_plugin(FakeRecord(DLC, 0x00001234), Strict()).file_path.name == 'Starfield.esm'


def test_the_defining_plugin_is_the_records_home_not_the_winner():
    assert defining_plugin(FakeRecord(DLC, 0x00001234), FakeSet(VANILLA, DLC)).file_path.name == 'Starfield.esm'
    assert defining_plugin(FakeRecord(DLC, 0x01001234), FakeSet(VANILLA, DLC)).file_path.name == 'SFBGS00D.esm'


class FakeSub:
    def __init__(self, signature, data):
        self.signature, self.data = signature, data
        self.size = len(data)


class FakeNpc:
    def __init__(self, plugin, form, subs):
        self.plugin, self.form_id, self.subrecords = plugin, FakeForm(form), subs
        self.editor_id = 'X'


def fields(value):
    return struct.pack('<I', value)


def test_each_kind_of_field_is_rewritten():
    r = Remapper(['Starfield.esm', 'FSF.esm'], FakeSet(VANILLA, FSF, DLC))
    npc = FakeNpc(DLC, 0x01000A00, [
        FakeSub('DOFT', fields(0x01000A01)),
        FakeSub('KWDA', fields(0x01000A02) + fields(0x00000005)),
        FakeSub('SNAM', fields(0x01000A03) + b'\x01'),
        FakeSub('CNTO', fields(0x01000A04) + fields(0x01000000)),
        FakeSub('TPTA', fields(0x01000A05) + bytes(4) + fields(0x00000006)),
        FakeSub('EDID', b'Hello\0'),
    ])
    remap_npc(npc, r)
    got = {s.signature: s.data for s in npc.subrecords}
    assert npc.form_id == 0x02000A00
    assert got['DOFT'] == fields(0x02000A01)
    assert got['KWDA'] == fields(0x02000A02) + fields(0x00000005)
    assert got['SNAM'] == fields(0x02000A03) + b'\x01', 'the rank is not a reference'
    assert got['CNTO'] == fields(0x02000A04) + fields(0x01000000), 'the count is not a reference'
    assert got['TPTA'] == fields(0x02000A05) + bytes(4) + fields(0x00000006)
    assert got['EDID'] == b'Hello\0'


def obts(includes, properties, keywords=()):
    body = struct.pack('<IIHHhBB', len(includes), len(properties), 0, 0xFFFF, -1, 1, len(keywords))
    body += b''.join(fields(k) for k in keywords) + bytes(2)
    body += b''.join(fields(i) + b'\x01\0\0' for i in includes)
    for kind, value in properties:
        body += bytes([kind]) + bytes(3) + bytes(4) + fields(7) + fields(value) + bytes(8)
    return body


def test_an_object_template_s_references_are_rewritten():
    r = Remapper(['Starfield.esm', 'FSF.esm'], FakeSet(VANILLA, FSF, DLC))
    npc = FakeNpc(DLC, 0x01000A00, [FakeSub('OBTS', obts([0x01000B02, 0x00000005],
                                                         [(4, 0x01000B03), (6, 0x01000B04), (1, 0x01000B05)]))])
    remap_npc(npc, r)
    assert npc.subrecords[0].data == obts([0x02000B02, 0x00000005],
                                          [(4, 0x02000B03), (6, 0x02000B04), (1, 0x01000B05)]), 'a float stays'


def test_an_object_template_s_keywords_are_rewritten():
    """A one-byte keyword count, the keywords, then two bytes before the includes (6577 OBTS in the
    load order add up this way, 1440 with a keyword, every one a KYWD)."""
    r = Remapper(['Starfield.esm', 'FSF.esm'], FakeSet(VANILLA, FSF, DLC))
    npc = FakeNpc(DLC, 0x01000A00, [FakeSub('OBTS', obts([0x01000B02], [(4, 0x01000B03)],
                                                         keywords=[0x01000B06, 0x00000008]))])
    remap_npc(npc, r)
    assert npc.subrecords[0].data == obts([0x02000B02], [(4, 0x02000B03)],
                                          keywords=[0x02000B06, 0x00000008])


def test_an_object_template_that_does_not_add_up_stops_that_npc():
    r = Remapper(['Starfield.esm', 'FSF.esm'], FakeSet(VANILLA, FSF, DLC))
    wrong_count = bytearray(obts([], []))
    wrong_count[15] = 1
    for data in (obts([1], []) + b'\0', bytes(wrong_count)):
        npc = FakeNpc(DLC, 0x01000A00, [FakeSub('OBTS', data)])
        with pytest.raises(ValueError, match='OBTS'):
            remap_npc(npc, r)


def test_properties_hold_an_actor_value_and_a_curve_table():
    r = Remapper(['Starfield.esm', 'FSF.esm'], FakeSet(VANILLA, FSF, DLC))
    value = struct.pack('<f', 5.0)
    npc = FakeNpc(DLC, 0x01000A00, [FakeSub('PRPS', fields(0x01000C01) + value + fields(0x01000C02))])
    remap_npc(npc, r)
    assert npc.subrecords[0].data == fields(0x02000C01) + value + fields(0x02000C02)


def test_a_number_the_definition_says_is_a_number_is_left_alone():
    r = Remapper(['Starfield.esm', 'FSF.esm'], FakeSet(VANILLA, FSF, DLC))
    npc = FakeNpc(DLC, 0x01000A00, [FakeSub('ACBS', fields(0x01010023))])
    remap_npc(npc, r)
    assert npc.subrecords[0].data == fields(0x01010023)


def test_ai_data_is_bytes_not_references():
    """AIDT is seven one-byte numbers (aggression, confidence, energy, morality, mood,
    assistance, a flag). Read as a word, energy 50 and morality 1 look like a DLC reference;
    25 companions and crew were refused for it."""
    r = Remapper(['Starfield.esm', 'FSF.esm'], FakeSet(VANILLA, FSF, DLC))
    aidt = bytes([1, 2, 50, 1, 4, 3, 0])
    npc = FakeNpc(DLC, 0x01000A00, [FakeSub('AIDT', aidt)])
    remap_npc(npc, r)
    assert npc.subrecords[0].data == aidt


def test_a_reference_in_a_subrecord_we_do_not_know_stops_that_npc():
    """A missed reference would quietly point at something else in the game."""
    r = Remapper(['Starfield.esm', 'FSF.esm'], FakeSet(VANILLA, FSF, DLC))
    npc = FakeNpc(DLC, 0x01000A00, [FakeSub('XXXX', fields(0x01000A01))])
    with pytest.raises(ValueError, match='XXXX'):
        remap_npc(npc, r)


def test_a_wrong_sized_field_stops_that_npc():
    r = Remapper(['Starfield.esm', 'FSF.esm'], FakeSet(VANILLA, FSF, DLC))
    npc = FakeNpc(DLC, 0x01000A00, [FakeSub('CNTO', b'\0' * 7)])
    with pytest.raises(ValueError, match='CNTO'):
        remap_npc(npc, r)


# ---------------------------------------------------------------- real data

class FullGame:
    """Each plugin read whole: a PluginSet only reads some record types, so its lookups miss."""

    def __init__(self, data, names):
        from esplib.plugin import Plugin
        self.names = names
        self.by_name = {n.lower(): Plugin.load(str(data / n)) for n in names}

    def get_plugin(self, name):
        return self.by_name.get(name.lower())


@pytest.fixture(scope='module')
def game():
    data = game_data()
    return FullGame(data, [n for n in load_full_order(data) if n.lower() != 'fsfnpc.esm'])


@pytest.fixture(scope='module')
def built(tmp_path_factory):
    """Named FSFNPC.esm so the tool leaves any active copy of itself out of the load order."""
    out = tmp_path_factory.mktemp('remap') / 'FSFNPC.esm'
    cmd = [sys.executable, str(ROOT / 'sf_furrify.py'), '--data', str(game_data()), '--out', str(out), '--scheme', str(SCHEME),
           '--builtin', str(BUILTIN), '--races', str(RACES)]
    for name in NPCS:
        cmd += ['--only', name]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    from esplib import Plugin
    return Plugin.load(str(out)), proc


def winner(game, edid):
    found = None
    for name in game.names:
        plugin = game.get_plugin(name)
        rec = plugin.get_record_by_editor_id(edid)
        if rec is not None and rec.signature == 'NPC_':
            found = rec
    return found


def resolve_edid(game, value, masters, own):
    """The EditorID a raw reference means, seen from a file with this master list."""
    index = value >> 24
    home = masters[index] if index < len(masters) else own
    target = game.get_plugin(home)
    if target is None:
        return f'<{home} not loaded>'
    local = (len(target.header.masters) << 24) | (value & 0xFFFFFF)
    rec = target.get_record_by_form_id(local)
    return rec.editor_id if rec is not None else None


def test_the_dlc_npcs_build_without_errors(built):
    _, proc = built
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert 'ERROR' not in proc.stdout, proc.stdout


def test_the_winners_really_are_in_the_dlcs(game):
    for edid, plugin in EXPECT_DLC.items():
        assert winner(game, edid).plugin.file_path.name.lower() == plugin.lower()


def test_masters_are_only_those_needed_and_starfield_and_fsf_stay_first(built):
    plugin, _ = built
    masters = list(plugin.header.masters)
    assert masters[:2] == ['Starfield.esm', 'FSF.esm']
    assert {'ShatteredSpace.esm', 'SFBGS00D.esm', 'SFBGS050.esm'} <= set(masters), masters
    assert 'SFBGS007.esm' not in masters
    assert len(set(m.lower() for m in masters)) == len(masters)


def test_every_reference_means_what_it_meant_in_the_winner(built, game):
    """Compared by EditorID through each file's own master list, field by field."""
    plugin, _ = built
    masters = list(plugin.header.masters)
    checked = 0
    for npc in plugin.get_records_by_signature('NPC_'):
        source = winner(game, npc.editor_id)
        src_masters = list(source.plugin.header.masters)
        src_name = source.plugin.file_path.name
        assert resolve_edid(game, int(npc.form_id.value), masters, 'FSFNPC.esm') == npc.editor_id
        for sig, step in (('DOFT', 4), ('SOFT', 4), ('TPLT', 4), ('CRIF', 4), ('VTCK', 4), ('KWDA', 4), ('CNAM', 4),
                          ('INAM', 4), ('LTPT', 4), ('SNAM', 5), ('CNTO', 8), ('TPTA', 4)):
            old, new = source.get_subrecords(sig), npc.get_subrecords(sig)
            assert len(old) == len(new), (npc.editor_id, sig)
            for a, b in zip(old, new):
                for off in range(0, len(a.data), step):
                    va = struct.unpack_from('<I', a.data, off)[0]
                    vb = struct.unpack_from('<I', b.data, off)[0]
                    if va:
                        assert resolve_edid(game, vb, masters, 'FSFNPC.esm') == resolve_edid(game, va, src_masters, src_name), \
                            (npc.editor_id, sig, off)
                        checked += 1
    assert checked > 50


def test_a_dlc_npc_keeps_its_own_name(built, game):
    """String IDs belong to the plugin that holds the record, and they repeat across plugins."""
    plugin, _ = built
    data = game_data()
    tested = 0
    for npc in plugin.get_records_by_signature('NPC_'):
        source = winner(game, npc.editor_id)
        full = source.get_subrecord('FULL')
        if full is None or len(full.data) != 4:
            continue
        table = load_all_string_tables(data, source.plugin.file_path.stem)
        expected = table.get(struct.unpack('<I', full.data)[0])
        assert expected, (npc.editor_id, source.plugin.file_path.name, 'no string')
        assert npc.get_subrecord('FULL').data.rstrip(b'\0').decode('utf-8') == expected
        tested += 1
    assert tested


def test_a_script_reference_on_a_dlc_npc_is_rewritten(built, game):
    plugin, _ = built
    from esplib.vmad import VmadData
    npc = next(n for n in plugin.get_records_by_signature('NPC_') if n.editor_id == 'SFBGS001_Crew_LvlCrew_Any')
    source = winner(game, npc.editor_id)
    masters, src_masters = list(plugin.header.masters), list(source.plugin.header.masters)

    def objects(data):
        found = []
        VmadData.parse(bytes(data.get_subrecord('VMAD').data), 'NPC_').remap_form_ids(lambda v: found.append(v) or v)
        return found

    old, new = objects(source), objects(npc)
    assert old and len(old) == len(new)
    assert [resolve_edid(game, v, masters, 'FSFNPC.esm') for v in new] == \
        [resolve_edid(game, v, src_masters, source.plugin.file_path.name) for v in old]
    assert any(v >> 24 for v in old)
