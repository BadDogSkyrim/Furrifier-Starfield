"""Command-line arguments."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sf_furrify import plugin_path


def test_a_name_without_an_extension_gets_esm():
    """The plugin is written flagged master and light, which is a .esm."""
    assert plugin_path(Path('FSFNPC_Test')) == Path('FSFNPC_Test.esm')


def test_a_plugin_extension_is_kept_whatever_its_case():
    for name in ('FSFNPC.esm', 'FSFNPC.esp', 'FSFNPC.esl', 'FSFNPC.ESM'):
        assert plugin_path(Path(name)) == Path(name)


def test_a_dot_in_the_name_is_not_an_extension():
    assert plugin_path(Path('FSFNPC.v2')) == Path('FSFNPC.v2.esm')


def test_a_folder_is_kept():
    assert plugin_path(Path('C:/tmp/out/FSFNPC')) == Path('C:/tmp/out/FSFNPC.esm')
