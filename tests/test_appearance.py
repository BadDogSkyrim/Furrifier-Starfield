"""Functional test: run the furrifier on real game data and read the plugin back.

Checks what the game and the CK actually read, against the shipped fox presets and the
sf1 NPC_ definition: head parts in PNAM, tints in the array before MRSV with real textures,
phenotype tables that exist on the race.
"""
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
from fsfdata import BUILTIN, RACES, SCHEME, game_data  # noqa: E402
sys.path.insert(0, str(ROOT))
from fsftools.config import load_races  # noqa: E402
from fsftools.plugin_loader import load_order_for_plugin, load_plugins  # noqa: E402

NPCS = ['Companion_SarahMorgan', 'Companion_SamCoe', 'FC_Neon_GenericCustomerF0*',
        'FC_Neon_GenericCustomerM0*', 'CF06_LvlSyndicate_Unaggressive_F01']
TAIL_ORDER = ['EDCT', 'MRSV', 'FMRI', 'BMPN', 'STON', 'FHCL', 'ECOL', 'PRON']
FOX_SIMPLE_SLOTS = ('Dermaesthetic', 'Complexion1', 'ComplexionMask1')


def text(sr):
    return sr.data.rstrip(b'\0').decode('utf-8')


def u32(sr):
    return struct.unpack('<I', sr.data)[0]


@pytest.fixture(scope='module')
def world():
    data = game_data()
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / 'test_furrify.esm'
        cmd = [sys.executable, str(ROOT / 'sf_furrify.py'), '--data', str(game_data()), '--plugin', 'FSF.esm', '--out', str(out),
               '--scheme', str(SCHEME), '--builtin', str(BUILTIN),
               '--races', str(RACES)]
        for n in NPCS:
            cmd += ['--only', n]
        run = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        assert run.returncode == 0, run.stdout + run.stderr
        from esplib import Plugin
        result = Plugin.load(str(out))
        records = list(result.get_records_by_signature('NPC_'))
        result_masters = list(result.header.masters)
        order = load_order_for_plugin(data, 'FSFPlayer_FOX.esm')
        refs = load_plugins(data, order)
        yield dict(data=data, npcs=records, masters=result_masters, refs=refs, log=run.stdout)


def female(npc):
    return bool(npc.get_subrecord('ACBS').data[0] & 1)


def hdpts(world):
    fsf = world['refs'].get_plugin('FSF.esm')
    return {int(h.form_id.value) & 0xFFFFFF: h for h in fsf.get_records_by_signature('HDPT')}


def test_picks_up_the_named_npcs(world):
    names = {n.editor_id for n in world['npcs']}
    assert {'Companion_SarahMorgan', 'Companion_SamCoe', 'CF06_LvlSyndicate_Unaggressive_F01'} <= names
    assert world['masters'] == ['Starfield.esm', 'FSF.esm']


def test_head_parts_are_fox_pnams(world):
    table = hdpts(world)
    for npc in world['npcs']:
        assert not npc.get_subrecords('HEAD'), npc.editor_id
        pnams = [u32(s) for s in npc.get_subrecords('PNAM')]
        assert all(p >> 24 == 1 and (p & 0xFFFFFF) in table for p in pnams), (npc.editor_id, [hex(p) for p in pnams])
        assert pnams == sorted(pnams)
        parts = [table[p & 0xFFFFFF] for p in pnams]
        sex = 'Female' if female(npc) else 'Male'
        names = {p.editor_id for p in parts}
        for base in ('Head', 'LeftEye', 'RightEye', 'Teeth', 'Tongue'):
            assert f'FSFCanine_{sex}_{base}' in names, (npc.editor_id, names)
        extras = [p.editor_id for p in parts if u32(p.get_subrecord('PNAM')) == 4]
        assert len(extras) <= 1, (npc.editor_id, names)     # a ruff, or none; either sex
        assert not any(n.endswith('XP') for n in names), names


def test_subrecord_order_matches_the_spec(world):
    for npc in world['npcs']:
        sigs = [s.signature for s in npc.subrecords]
        at = [sigs.index(t) for t in TAIL_ORDER if t in sigs]
        assert at == sorted(at), (npc.editor_id, sigs)
        assert sigs.index('EDCT') < sigs.index('STON')
        assert max(i for i, s in enumerate(sigs) if s == 'PNAM') < sigs.index('NAM5')
        assert sigs.index('ODTY') < sigs.index('ACBS')


def test_tints_are_real_fox_options(world):
    avm = {}
    for plugin_name in ('Starfield.esm', 'FSF.esm', 'FSFPlayer_FOX.esm'):
        for a in world['refs'].get_plugin(plugin_name).get_records_by_signature('AVMD'):
            t, m = a.get_subrecord('TNAM'), a.get_subrecord('MNAM')
            if t and m and m.data[0] == 1:
                avm[text(t)] = a
    sf = world['refs'].get_plugin('Starfield.esm')
    mod = next(a for a in sf.get_records_by_signature('AVMD') if a.editor_id == 'Modulation_ComplexionMask1')
    modulation = {s.data for s in mod.subrecords if s.signature == 'NNAM'}
    for npc in world['npcs']:
        seq = list(npc.subrecords)
        tints = [(seq[i], seq[i + 1], seq[i + 2], seq[i + 3], seq[i + 4], seq[i - 1])
                 for i, s in enumerate(seq) if s.signature == 'TNAM']
        slots = [text(t[0]) for t in tints]
        assert npc.get_subrecord('EDCT').data[0] == len(tints)
        assert slots[:2] == ['Dermaesthetic', 'Complexion1'], (npc.editor_id, slots)
        assert set(slots) <= set(FOX_SIMPLE_SLOTS) and len(set(slots)) == len(slots)
        for tn, qn, vn, nn, iv, mn in tints:
            assert u32(mn) == 1
            group = avm[text(tn)]
            rows = list(group.subrecords)
            pairs = {text(rows[i]): text(rows[i + 1]) for i, s in enumerate(rows) if s.signature == 'LNAM'}
            assert text(qn) in pairs, (text(tn), text(qn), list(pairs)[:6])
            assert text(vn) == pairs[text(qn)]
            assert (Path(world['data']) / text(vn)).exists(), text(vn)
            assert 1 <= u32(iv) <= 128
            if text(tn) == 'ComplexionMask1':
                assert nn.data in modulation, 'a mask paints a colour from its Modulation group'


def test_face_tables_match_the_race(world):
    race = world['refs'].get_record_by_edid('RACE', 'FSFFoxRace')
    seq = list(race.subrecords)
    table = {text(seq[i + 1]): u32(s) for i, s in enumerate(seq)
             if s.signature == 'FMRI' and seq[i + 1].signature == 'FMRU'}
    fox = load_races(RACES)['FSFFoxRace']
    tones = set()
    for npc in world['npcs']:
        sigs = [s.signature for s in npc.subrecords]
        assert sigs.count('FMRI') == 1, npc.editor_id
        assert sigs.count('FMSI') == 0
        fmri = u32(npc.get_subrecord('FMRI'))
        keys = [text(s) for s in npc.get_subrecords('BMPN')]
        assert keys, npc.editor_id
        pheno = keys[0].rsplit('_', 1)[0]
        assert table[pheno] == fmri, (npc.editor_id, pheno, fmri)
        assert pheno.startswith('female_' if female(npc) else 'male_')
        assert all(k.startswith(pheno + '_') for k in keys)
        assert sigs.count('FMRG') == 9
        ston = npc.get_subrecord('STON').data[0]
        allowed = fox.skin_tones_female if female(npc) else fox.skin_tones
        assert ston in allowed, (npc.editor_id, ston, 'fennec is off, so only the race\'s tones')
        tones.add(ston)
    assert len(tones) > 1, 'every NPC got the same skin tone'


def test_facial_hair_colour_is_in_the_parts_group(world):
    table = hdpts(world)
    for npc in world['npcs']:
        for s in npc.get_subrecords('PNAM'):
            h = table[u32(s) & 0xFFFFFF]
            if u32(h.get_subrecord('PNAM')) == 4:
                group = text(h.get_subrecord('NAM2'))
                entries = next(a for a in world['refs'].get_plugin('FSF.esm').get_records_by_signature('AVMD')
                               if a.get_subrecord('TNAM') and text(a.get_subrecord('TNAM')) == group
                               and a.get_subrecord('MNAM').data[0] == 1)
                keys = {text(s) for s in entries.subrecords if s.signature == 'LNAM'}
                assert text(npc.get_subrecord('FHCL')) in keys, npc.editor_id
