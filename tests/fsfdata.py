"""The data the tests use: frozen copies in tests/fixtures, never the mod's live files.

The race and scheme files are the tests' own. The FSF mods are a snapshot (tests/fixtures/fsf, made
by make_snapshot.py), read through an --overlay view of the game's Data that hides the live mods it
stands in for; game_data() is that view. Vanilla is still read live: it doesn't change under us."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILTIN = ROOT / 'fsftools' / 'builtin.toml'
DATA = ROOT / 'tests' / 'fixtures'
SCHEME = DATA / 'furrify' / 'scheme.toml'
RACES = DATA / 'furrify' / 'races'
RACE_COPIES = DATA / 'furrify' / 'race_copies'
SNAPSHOT = DATA / 'fsf'
# The tests' own plugin of test NPCs (make_test_plugin.py), linked into the view beside the snapshot.
TEST_PLUGIN = DATA / 'fsftest' / 'FSFTest.esm'
VIEW = ROOT / 'tests' / 'out' / 'data_view'

_view = []


def game_data() -> Path:
    """The game's Data folder with the FSF snapshot over it. Built once per test session: the first
    process builds it and says so in FSF_TEST_VIEW, so the subprocesses it starts reuse it."""
    if not _view:
        if os.environ.get('FSF_TEST_VIEW') == str(VIEW) and VIEW.is_dir():
            _view.append(VIEW)
        else:
            from fsftools.overlay import merged_view
            from fsftools.plugin_loader import discover_data_dir
            _view.append(merged_view(discover_data_dir(), SNAPSHOT, where=VIEW))
            if TEST_PLUGIN.is_file():
                linked = VIEW / TEST_PLUGIN.name
                if linked.exists():           # a copy in Data for a CK bake: the fixture's wins
                    linked.unlink()
                os.link(TEST_PLUGIN, linked)
            os.environ['FSF_TEST_VIEW'] = str(VIEW)
    return _view[0]
