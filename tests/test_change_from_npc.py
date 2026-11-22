"""change_from_npc: the bake input for an NPC as its record stands.

Round trip on the tests' own NPCs: FSFTest.esm is written by make_test_plugin.py from the spec in
its NPCS list, through the furrifier's plugin writer; reading each back gives the spec again.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fsfdata import game_data  # noqa: E402
from fsftools.furrify_npc import change_from_npc  # noqa: E402
from fsftools.plugin_loader import load_order_for_plugin, load_plugins  # noqa: E402
from make_test_plugin import FEMALE_PARTS, HUMANS, MALE_PARTS, NPCS  # noqa: E402


@pytest.fixture(scope='module')
def plugins():
    data = game_data()
    return load_plugins(data, load_order_for_plugin(data, 'FSFTest.esm'))


@pytest.mark.parametrize('spec', NPCS, ids=[n[0] for n in NPCS])
def test_a_test_npc_reads_back_as_written(plugins, spec):
    edid, race, sex, extra, fhcl, tone, phenotype, sliders, tints, _covers = spec
    npc = plugins.get_record_by_edid('NPC_', edid)
    change = change_from_npc(npc, plugins)
    assert change.npc_editorid == edid and change.source is npc
    assert (change.sex, change.new_race_edid, change.new_ston) == (sex, race, tone)
    assert sorted(h.editor_id for h in change.head_parts) == sorted((MALE_PARTS if sex == 'MALE' else FEMALE_PARTS) + extra)
    assert [(t.slot, t.option, t.color, t.intensity) for t in change.tints] == list(tints)
    assert change.phenotype == phenotype, "looked up in the table for the NPC's sex"
    assert change.morph_groups == pytest.approx(sliders)
    assert len(change.face_regions) == 9
    got = npc.get_subrecord('FHCL')
    assert (bytes(got.data).rstrip(b'\0').decode() if got is not None else None) == fhcl


FACE = ('PNAM', 'EDCT', 'MNAM', 'TNAM', 'QNAM', 'VNAM', 'NNAM', 'INTV', 'MRSV', 'FMSI', 'FMRI', 'FMRG',
        'FMRS', 'BMPN', 'BMPV', 'STON', 'HCOL', 'FHCL', 'BCOL', 'JCOL', 'ECOL', 'MWGT')


@pytest.mark.parametrize('spec', HUMANS, ids=[h[0] for h in HUMANS])
def test_a_human_copy_keeps_its_face(plugins, spec):
    """The vanilla NPC's face subrecords come across byte for byte (FormIDs in PNAM aside, which
    are remapped to our master list -- Starfield.esm stays index 0, so they're equal too)."""
    edid, source_edid, _covers = spec
    ours, theirs = (plugins.get_record_by_edid('NPC_', e) for e in (edid, source_edid))
    face = [(s.signature, bytes(s.data)) for s in ours.subrecords if s.signature in FACE]
    assert face == [(s.signature, bytes(s.data)) for s in theirs.subrecords if s.signature in FACE]
    assert change_from_npc(ours, plugins).new_race_edid == 'HumanRace'


def test_the_race_tables_share_ids_across_sexes(plugins):
    """Why the phenotype lookup needs the NPC's sex: the male and female tables reuse their ids."""
    import struct
    race = plugins.get_record_by_edid('RACE', 'FSFHyenaRace')
    ids = [struct.unpack('<I', s.data)[0] for s in race.subrecords if s.signature == 'FMRI']
    assert len(ids) > len(set(ids))
