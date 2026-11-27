"""The furrifier's output numbers its masters the Starfield way, read from its raw bytes.

Starfield numbers a plugin's masters by kind (fsftools.formids): full masters among themselves,
the plugin's own records at the count of full masters, a small master as FE + its small number +
a 12-bit object, a medium one as FD + its medium number + a 16-bit object. Writing positions
instead (as Skyrim and Fallout 4 do) pointed FSFNPC.esm's hair, in the small FSFHair.esm, at
SFBGS00D's NAVM 0x8B4 (Bad Dog's xEdit, 2026-11-26), and shifted every override of a DLC NPC.

One run makes an output that masters both kinds: CF06_LvlSyndicate_Unaggressive_F01 keeps her
Cropped hair (fitted, in the small FSFHair.esm), SFBGS003_Tank is SFBGS003.esm's own NPC (a
medium plugin), and the crowd test adds the output's own records.
"""
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tests import tt  # noqa: E402
from tests.fsfdata import BUILTIN, game_data  # noqa: E402
from tests.test_crowd_hair import ARMORS, FOX, races_taking  # noqa: E402
from tests.test_crowds import scheme  # noqa: E402

HAIR_NPC = 'CF06_LvlSyndicate_Unaggressive_F01'
DLC_NPC, DLC, DLC_OBJECT = 'SFBGS003_Tank', 'SFBGS003.esm', 0xE99


def header(path):
    """(flags, [masters]) from the raw TES4 record."""
    data = open(path, 'rb').read()
    size, flags = struct.unpack_from('<II', data, 4)
    body, masters, i = data[24:24 + size], [], 0
    while i < len(body):
        s, n = body[i:i + 4], struct.unpack_from('<H', body, i + 4)[0]
        if s == b'MAST':
            masters.append(body[i + 6:i + 6 + n].rstrip(b'\0').decode())
        i += 6 + n
    return flags, masters


def raw_records(path):
    """[(signature, EditorID, header FormID, [(subrecord, 4-byte value)])], from the bytes."""
    import zlib
    data = open(path, 'rb').read()
    out = []

    def walk(p, end):
        while p + 24 <= end:
            sig, size, flags = data[p:p + 4], *struct.unpack_from('<II', data, p + 4)
            if sig == b'GRUP':
                walk(p + 24, p + size)
                p += size
                continue
            fid = struct.unpack_from('<I', data, p + 12)[0]
            body = data[p + 24:p + 24 + size]
            if flags & 0x40000:
                body = zlib.decompress(body[4:])
            q, edid, vals = 0, None, []
            while q + 6 <= len(body):
                s, n = body[q:q + 4].decode(), struct.unpack_from('<H', body, q + 4)[0]
                d = body[q + 6:q + 6 + n]
                if s == 'EDID':
                    edid = d.rstrip(b'\0').decode()
                elif n == 4:
                    vals.append((s, struct.unpack('<I', d)[0]))
                q += 6 + n
            out.append((sig.decode(), edid, fid, vals))
            p += 24 + size
    walk(24 + struct.unpack_from('<I', data, 4)[0], len(data))
    return out


def kind(path):
    flags = header(path)[0]
    return 'small' if flags & 0x100 else 'medium' if flags & 0x400 else 'full'


@pytest.fixture(scope='module')
def output(tmp_path_factory):
    if not Path(tt.SF_ASSETS).is_dir():
        pytest.fail(f'asset folder missing: {tt.SF_ASSETS}')
    work = tmp_path_factory.mktemp('numbering')
    races = races_taking(work, ARMORS)
    (work / 'scheme.toml').write_text(scheme((FOX, 100)), encoding='utf-8')
    # The full load order (no --plugin), for the DLC. Named FSFNPC.esm so the tool leaves any active
    # copy of itself out of the load order.
    out = work / 'mod' / 'FSFNPC.esm'
    cmd = [sys.executable, str(ROOT / 'sf_furrify.py'), '--data', str(game_data()),
           '--out', str(out), '--scheme', str(work / 'scheme.toml'), '--builtin', str(BUILTIN),
           '--races', str(races), '--only', HAIR_NPC, '--only', DLC_NPC, '--crowd-test', '--hair',
           '--assets', tt.SF_ASSETS]
    run = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    assert run.returncode == 0, run.stdout + run.stderr
    _, masters = header(out)
    kinds = {}
    for m in masters:
        here = out.parent / m
        kinds[m] = kind(here if here.is_file() else Path(game_data()) / m)
    return out, masters, kinds, run.stdout


def numbering(masters, kinds):
    """master name lowered -> what its high byte is: ('full', n) / ('small', n) / ('medium', n)."""
    counts, slots = {'full': 0, 'small': 0, 'medium': 0}, {}
    for m in masters:
        k = kinds[m]
        slots[m.lower()] = (k, counts[k])
        counts[k] += 1
    return slots, counts['full']


def encoded(slot, obj):
    k, n = slot
    if k == 'small':
        return 0xFE000000 | n << 12 | obj
    if k == 'medium':
        return 0xFD000000 | n << 16 | obj
    return n << 24 | obj


def test_the_output_masters_a_small_and_a_medium_plugin(output):
    _, masters, kinds, log = output
    assert kinds.get('FSFHair.esm') == 'small', (masters, kinds)
    assert kinds.get(DLC) == 'medium', (masters, kinds)


def test_the_dlc_npc_is_overridden_as_its_medium_master_numbers_it(output):
    out, masters, kinds, _ = output
    slots, _ = numbering(masters, kinds)
    tank = next(r for r in raw_records(out) if r[1] == DLC_NPC)
    assert tank[2] == encoded(slots[DLC.lower()], DLC_OBJECT), f'{tank[2]:08X}'


def test_the_kept_hair_is_referenced_in_the_small_hair_plugin(output):
    out, masters, kinds, _ = output
    slots, _ = numbering(masters, kinds)
    hair_slot = slots['fsfhair.esm']
    hair = {fid & 0xFFF: (sig, edid) for sig, edid, fid, _ in raw_records(out.parent / 'FSFHair.esm')
            if sig == 'HDPT'}
    npc = next(r for r in raw_records(out) if r[1] == HAIR_NPC)
    into_hair = [v for s, v in npc[3] if s == 'PNAM' and v >> 12 == encoded(hair_slot, 0) >> 12]
    assert len(into_hair) == 1, [f'{v:08X}' for s, v in npc[3] if s == 'PNAM']
    assert hair[into_hair[0] & 0xFFF][1].endswith('Hair_Cropped'), hair[into_hair[0] & 0xFFF]


def test_own_records_take_the_count_of_full_masters(output):
    out, masters, kinds, _ = output
    _, n_full = numbering(masters, kinds)
    known = {encoded(s, 0) >> 24 for s in numbering(masters, kinds)[0].values()}
    own = [(sig, edid, fid) for sig, edid, fid, _ in raw_records(out) if fid >> 24 not in known]
    assert own, 'the crowd test makes records of our own'
    assert {fid >> 24 for _, _, fid in own} == {n_full}, sorted({f'{fid >> 24:02X}' for _, _, fid in own})


def test_every_reference_resolves_through_the_load_order(output):
    """Read back by esplib through the load order, every NPC head part is an HDPT and every
    override names its own record: the encoding read as the game reads it."""
    from fsftools.plugin_loader import load_plugins, use_plugin_file
    out, masters, _, _ = output
    order = [m for m in masters if not (out.parent / m).is_file()]
    ps = load_plugins(game_data(), order)
    for m in masters:                               # this run's own plugins, in place of any deployed
        if (out.parent / m).is_file():
            use_plugin_file(ps, order, out.parent / m)
    mine = use_plugin_file(ps, order, out)
    bad = []
    for npc in mine.get_records_by_signature('NPC_'):
        for sr in npc.get_subrecords('PNAM'):
            t = ps.resolve_form_id(sr.get_form_id(), mine)
            if t is None or t.signature != 'HDPT':
                bad.append((npc.editor_id, sr.data.hex(), t and (t.signature, t.editor_id)))
    assert not bad, bad
    tank = mine.get_record_by_editor_id(DLC_NPC)
    chain = ps.get_override_chain(mine.normalize_form_id(tank.form_id))
    assert chain[0].plugin.file_path.name.lower() == DLC.lower(), [r.plugin.file_path.name for r in chain]
