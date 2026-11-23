"""Command-line arguments: --out is the output folder, or a plugin file in it."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sf_furrify import DEFAULT_PLUGIN, resolve_out  # noqa: E402

DATA = Path('C:/Game/Data')


def test_no_out_is_data_and_the_default_plugin():
    assert resolve_out(None, DATA) == (DATA, DEFAULT_PLUGIN)


def test_a_plugin_file_names_the_folder_and_the_plugin():
    for name in ('My.esm', 'My.esp', 'My.esl', 'My.ESM'):
        assert resolve_out(Path('C:/Mods/FSF_test') / name, DATA) == (Path('C:/Mods/FSF_test'), name)


def test_a_folder_gets_the_default_plugin():
    assert resolve_out(Path('C:/Mods/FSF_test'), DATA) == (Path('C:/Mods/FSF_test'), DEFAULT_PLUGIN)


def test_a_dot_in_a_folder_name_is_not_an_extension():
    assert resolve_out(Path('C:/Mods/FSF.v2'), DATA) == (Path('C:/Mods/FSF.v2'), DEFAULT_PLUGIN)


def test_a_plugin_name_alone_goes_in_data():
    """As before: --out FSFNPC_test.esm writes the plugin into the game's Data folder."""
    assert resolve_out(Path('FSFNPC_test.esm'), DATA) == (DATA, 'FSFNPC_test.esm')
