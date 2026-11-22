"""The load order read from Plugins.txt."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fsftools.plugin_loader import load_full_order


def test_disabled_plugins_are_not_in_the_load_order(tmp_path):
    # Plugins.txt lists every plugin it knows; only those marked * are active. A disabled
    # earlier furrifier output must not win over the outfits.
    data = tmp_path / 'Data'
    data.mkdir()
    for name in ('Active.esm', 'Disabled.esm'):
        (data / name).write_bytes(b'')
    plugins_txt = tmp_path / 'Plugins.txt'
    plugins_txt.write_bytes(b'# comment\r\n*Active.esm\r\nDisabled.esm\r\n')

    order = load_full_order(data, plugins_txt)

    assert 'Active.esm' in order
    assert 'Disabled.esm' not in order
