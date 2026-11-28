"""Which NPCs the furrifier counts as human, read from vanilla."""
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
from fsfdata import game_data  # noqa: E402
sys.path.insert(0, str(ROOT))
from fsftools.plugin_loader import enumerate_human_npcs, load_plugins  # noqa: E402

PEOPLE = {'Companion_SarahMorgan', 'Companion_SamCoe', 'LvlMarine_SysDef_Sniper_BECrew_Security'}
CREATURES = {'Biome_Predator', 'Biome_Prey_Swimmer_Herd', 'Biome_Critter_Corpse',
             'RL012_Biome_Predator_NoFlier', 'UCR04_Biome_Predator_Apex'}


@pytest.fixture(scope='module')
def vanilla():
    order = ['Starfield.esm']
    plugins = load_plugins(game_data(), order)
    return plugins, {npc.editor_id for npc, _ in enumerate_human_npcs(plugins, order)}


def test_wildlife_templates_are_not_human(vanilla):
    # Bethesda gives the planets' wildlife templates HumanRace as a placeholder; their traits come
    # from a biome marker (BMMO), which the planet fills with its own creature.
    _, human = vanilla
    assert PEOPLE <= human
    assert not CREATURES & human


def test_every_npc_with_traits_from_a_biome_marker_is_left_out(vanilla):
    plugins, human = vanilla
    from_marker = set()
    for npc in plugins.get_plugin('Starfield.esm').get_records_by_signature('NPC_'):
        tpta = npc.get_subrecord('TPTA')
        if tpta is None or not struct.unpack_from('<H', npc.get_subrecord('ACBS').data, 14)[0] & 1:
            continue
        target = plugins.resolve_form_id(tpta.get_form_id(0), npc.plugin)
        if target is not None and target.signature == 'BMMO':
            from_marker.add(npc.editor_id)
    assert CREATURES <= from_marker
    assert not from_marker & human
