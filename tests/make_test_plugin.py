"""Write tests/fixtures/fsftest/FSFTest.esm: the furry test NPCs the FaceGen tests bake.

    python tests/make_test_plugin.py [--force]

Each NPC below is spelled out (race, parts, tints, tone, phenotype, sliders) and written by the
furrifier's own plugin writer, from a template NPC of the same race and sex in the FSF snapshot, as
a new record of FSFTest.esm (masters Starfield.esm and FSF.esm). The plugin is a fixture: rebuild
it only when the snapshot is refreshed, and then re-bake it in the CK
(tests/fixtures/ck_bake/README.txt).
"""
import argparse
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from fsfdata import RACES, game_data  # noqa: E402
from esplib import Plugin  # noqa: E402
from esplib.utils import FormID  # noqa: E402
from fsftools.config import load_races  # noqa: E402
from fsftools.furrify_npc import NpcChange, TintEntry  # noqa: E402
from fsftools.formid_remap import Remapper  # noqa: E402
from fsftools.plugin_loader import load_order_for_plugin, load_plugins  # noqa: E402
from fsftools.plugin_writer import _build_override, _output_form_id, _patch_sf_light_flag  # noqa: E402
from fsftools.race_data import RaceAppearance, avm_index, group_entries, race_avm, tint_plugin_path  # noqa: E402

OUT = HERE / 'fixtures' / 'fsftest' / 'FSFTest.esm'
MASTERS = ['Starfield.esm', 'FSF.esm']
FIRST_ID = 0x800

# A template per race and sex: any NPC of FSF's will do, its face is replaced wholesale.
TEMPLATES = {('FSFFoxRace', 'MALE'): '_FSFFoxChargenPresetMale02',
             ('FSFFoxRace', 'FEMALE'): '_FSFFoxChargenPresetFemale02',
             ('FSFHyenaRace', 'MALE'): '_FSFHyenaChargenPresetMale02',
             ('FSFHyenaRace', 'FEMALE'): '_FSFHyenaChargenPresetFemale01'}
MALE_PARTS = ['FSFCanine_Male_Head', 'FSFCanine_Male_LeftEye', 'FSFCanine_Male_RightEye', 'FSFCanine_Male_Teeth']
FEMALE_PARTS = ['FSFCanine_Female_Head', 'FSFCanine_Female_LeftEye', 'FSFCanine_Female_RightEye',
                'FSFCanine_Female_Teeth']
NO_COLOUR = b'\0\0\0\0'

# (EDID, race, sex, extra parts, FHCL, tone, phenotype, sliders, tints [(slot, option, NNAM, INTV)], covers)
NPCS = [
    ('FSFTest_FoxMale', 'FSFFoxRace', 'MALE', [], None, 0, 'male_fox_md1',
     {'male_fox_md1_Chin': 0.8, 'male_fox_md1_Ears': 1.0, 'male_fox_md1_Nose': 0.5},
     [('Dermaesthetic', 'male_fox_derm03', NO_COLOUR, 64)],
     "own-phenotype sliders, one derm at full strength, no facial hair; the tongue through HNAM"),
    ('FSFTest_FoxMale_Beard', 'FSFFoxRace', 'MALE', ['FSFFox_Male_Beard01'], 'White', 0, 'male_fox_md1',
     {'male_fox_md1_Chin': 1.0},
     [],
     "a beard with no NAM3: no follicle paint"),
    ('FSFTest_FoxFemale_NoMorph', 'FSFFoxRace', 'FEMALE', [], None, 2, 'female_fox_md1',
     {},
     [('Dermaesthetic', 'male_fox_derm01', NO_COLOUR, 64)],      # the fox's derms serve both sexes
     "no sliders at all: the base mesh and the phenotype's maps everywhere"),
    ('FSFTest_FoxFemale_Fennec', 'FSFFoxRace', 'FEMALE', ['FSFFox_Fem_Ruff02'], 'White', 2, 'female_fennec_md1',
     {'female_fennec_md1_Chin': 1.0, 'female_fennec_md1_Ears': 1.0},
     [('ComplexionMask1', 'Complexion_EyeSpots', bytes.fromhex('ff263c69'), 64)],
     "the fennec phenotype; a coloured mask; a female ruff"),
    ('FSFTest_HyenaMale_Ruff', 'FSFHyenaRace', 'MALE', ['FSFFox_Male_Ruff02'], 'White', 6, 'male_hyena_md2',
     {'male_hyena_md2_Chin': 1.0, 'male_hyena_md2_Nose': 1.0, 'male_hyena_md2_Mouth': 1.0},
     [('Dermaesthetic', 'male_hyena_derm03', NO_COLOUR, 64)],
     "a ruff with a NAM3 follicle mask in White (as the snapshot has it); teeth following the snout"),
    ('FSFTest_HyenaMale_RuffNoColour', 'FSFHyenaRace', 'MALE', ['FSFFox_Male_Ruff02'], None, 6, 'male_hyena_md2',
     {'male_hyena_md2_Chin': 1.0},
     [],
     "the same follicle mask with no FHCL: black, roughness untouched"),
    ('FSFTest_HyenaFemale_Tints', 'FSFHyenaRace', 'FEMALE', [], None, 1, 'female_hyena_md1',
     {'female_hyena_md1_Chin': 1.0, 'female_hyena_md1_Ears': 1.0},
     [('Dermaesthetic', 'male_hyena_derm01', NO_COLOUR, 40), ('ComplexionMask1', 'Complexion_Ears', NO_COLOUR, 64)],
     "a derm at partial strength (INTV 40); a mask with no colour (black)"),
    ('FSFTest_HyenaFemale_Cross', 'FSFHyenaRace', 'FEMALE', [], None, 1, 'female_hyena_md1',
     {'female_hyena_md1_Chin': 1.0, 'female_hyena_md2_Eyes': 0.5},
     [],
     "another phenotype's slider: the CK's Null region (not copied, see test_facegen_npcs)"),
]


# Vanilla humans, copied verbatim (face and all) under our own FormIDs: their CK bake lands under
# FSFTest.esm and can't collide with anything deployed for Starfield.esm. Human phenotype maps differ
# from each other, unlike FSF's, so these show how the CK blends phenotypes.
HUMANS = [
    ('FSFTest_Human_ScanMale', 'male_as_md1_scan', "one phenotype, no tints; hair cap mask with no HCOL"),
    ('FSFTest_Human_ScanFemale', 'female_eu_md2_scan', "the same, female"),
    ('FSFTest_Human_TwoPhenotypes', 'Crew_Elite_Heller',
     "two FMRI phenotypes, one (male_eu_md3) with no maps; tints; hair in Brown"),
    ('FSFTest_Human_Beard', 'EncSecurityFaceM01_Neon',
     "a beard follicle mask (ChinCurtain, Brown); a coloured mask; a mask with no colour"),
]


def tint_entry(avm, slot, option, colour, intensity):
    group = avm.get((1, slot))
    if group is None:
        raise ValueError(f"no Simple group {slot}")
    entries = group_entries(group)
    if option not in entries or not entries[option][0]:
        raise ValueError(f"{slot} has no option {option}; it has {sorted(entries)[:12]}")
    return TintEntry(slot, option, entries[option][0], colour, intensity)


def build(plugins, appearances):
    changes = []
    for i, (edid, race, sex, extra, fhcl, tone, phenotype, sliders, tints, _covers) in enumerate(NPCS):
        app = appearances[race]
        parts = [plugins.get_record_by_edid('HDPT', e) for e in (MALE_PARTS if sex == 'MALE' else FEMALE_PARTS) + extra]
        missing = [e for e, p in zip((MALE_PARTS if sex == 'MALE' else FEMALE_PARTS) + extra, parts) if p is None]
        if missing:
            raise ValueError(f"{edid}: no head part {missing}")
        template = plugins.get_record_by_edid('NPC_', TEMPLATES[(race, sex)])
        change = NpcChange(npc_editorid=edid, source=template, sex=sex, new_race_edid=race, new_ston=tone,
                           head_parts=parts, facial_hair_color=fhcl,
                           tints=[tint_entry(app.avm, *t) for t in tints], phenotype=phenotype,
                           phenotype_id=app.phenotype_ids[phenotype], face_regions=list(app.regions),
                           morph_groups=dict(sliders))
        changes.append((FIRST_ID + i, change))
    return changes


def copy_human(plugins, source_edid, edid, object_id, remapper):
    """A vanilla NPC as a new record of ours: the record as it stands, references remapped, the
    Traits template flag cleared (so its own face is the one used), scripts dropped."""
    from fsftools.formid_remap import remap_npc
    from fsftools.plugin_writer import _clear_traits_template
    source = plugins.get_record_by_edid('NPC_', source_edid)
    if source is None:
        raise ValueError(f"no NPC {source_edid}")
    npc = source.copy()
    npc.plugin = source.plugin
    remap_npc(npc, remapper)
    _clear_traits_template(npc)
    npc.subrecords[:] = [s for s in npc.subrecords if s.signature not in ('VMAD', 'TPLT', 'TPTA')]
    npc.form_id = FormID((len(MASTERS) << 24) | object_id)
    npc.get_subrecord('EDID').data = edid.encode() + b'\0'
    full = npc.get_subrecord('FULL')
    if full is not None:
        full.data = edid.encode() + b'\0'
    assert not npc.modified, edid
    return npc


def write(changes, plugins, path):
    out = Plugin()
    out.file_path = Path(path)
    out.header.version = 0.96
    out.header.masters = list(MASTERS)
    out.header.master_sizes = [0] * len(MASTERS)
    out.header.is_esl = True
    out.header.is_esm = True
    out.header.author = 'FSFTools tests'
    out.header.next_object_id = FIRST_ID + len(changes)
    race_ids = {c.new_race_edid: _output_form_id(plugins.get_record_by_edid('RACE', c.new_race_edid), MASTERS)
                for _, c in changes}
    remapper = Remapper(MASTERS, plugins)
    for object_id, change in changes:
        npc = _build_override(change, race_ids, lambda p: {}, MASTERS, remapper)
        npc.form_id = FormID((len(MASTERS) << 24) | object_id)
        npc.get_subrecord('EDID').data = change.npc_editorid.encode() + b'\0'
        full = npc.get_subrecord('FULL')
        if full is not None:
            full.data = change.npc_editorid.encode() + b'\0'
        if change.facial_hair_color is None:     # the template's FHCL would otherwise stay
            npc.subrecords[:] = [s for s in npc.subrecords if s.signature != 'FHCL']
        out.add_record(npc)
    for i, (edid, source_edid, _covers) in enumerate(HUMANS):
        out.add_record(copy_human(plugins, source_edid, edid, FIRST_ID + len(changes) + i, remapper))
    out.header.next_object_id = FIRST_ID + len(changes) + len(HUMANS)
    assert out.header.masters == MASTERS, out.header.masters
    path.parent.mkdir(parents=True, exist_ok=True)
    out.save(path)
    _patch_sf_light_flag(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--force', action='store_true', help="replace an existing FSFTest.esm")
    args = ap.parse_args(argv)
    if OUT.exists() and not args.force:
        sys.exit(f"{OUT} exists; --force replaces it (and the CK bake must be redone)")
    data = game_data()
    order = load_order_for_plugin(data, 'FSF.esm')
    plugins = load_plugins(data, order)
    base = avm_index(plugins, order)
    appearances = {}
    for edid, cfg in load_races(RACES).items():
        tint = Plugin.load(str(tint_plugin_path(cfg.tint_plugin, data)), only_signatures={'AVMD'})
        appearances[edid] = RaceAppearance(cfg, plugins, race_avm(base, tint), data)
    changes = build(plugins, appearances)
    write(changes, plugins, OUT)
    print(f"{len(changes) + len(HUMANS)} NPCs -> {OUT}")
    for object_id, change in changes:
        print(f"   {(len(MASTERS) << 24) | object_id:08X} {change.npc_editorid}")
    for i, (edid, source, _) in enumerate(HUMANS):
        print(f"   {(len(MASTERS) << 24) | (FIRST_ID + len(changes) + i):08X} {edid} (from {source})")
    _ = struct


if __name__ == '__main__':
    main()
