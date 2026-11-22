"""Copy the vanilla assets the human test NPCs' bake reads into tests/fixtures/vanilla.

    python tests/make_vanilla_fixture.py [--assets C:\\Modding\\Starfield\\00StarfieldAssets] [--force]

Bakes FSFTest.esm's human copies (make_test_plugin.HUMANS) from the unpacked vanilla assets,
recording every file the bake opens or looks for under them, then copies those files, keeping their
paths. The FCT masks are read as a set, so all of a folder's are taken. Vanilla doesn't change, so
this is redone only when the human test NPCs change.
"""
import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
OUT = HERE / 'fixtures' / 'vanilla'
RACES = HERE / 'fixtures' / 'vanilla_races'


def human_changes(plugins):
    from fsftools.furrify_npc import change_from_npc
    from make_test_plugin import HUMANS
    return [change_from_npc(plugins.get_record_by_edid('NPC_', edid), plugins) for edid, _, _ in HUMANS]


def bake_humans(assets: Path, out: Path):
    """Bake the human test NPCs from `assets`; returns (count, problems)."""
    from fsfdata import game_data
    from fsftools import facegen
    from fsftools.config import load_races
    from fsftools.plugin_loader import load_order_for_plugin, load_plugins
    from fsftools.race_data import RaceAppearance, avm_index
    data = game_data()
    order = load_order_for_plugin(data, 'FSFTest.esm')
    plugins = load_plugins(data, order)
    base = avm_index(plugins, order)
    appearances = {e: RaceAppearance(c, plugins, base, assets) for e, c in load_races(RACES).items()}
    return facegen.bake_all(human_changes(plugins), appearances, plugins, assets, out, log=lambda *a: None,
                            assets=assets), plugins


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--assets', default=r'C:\Modding\Starfield\00StarfieldAssets')
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args(argv)
    assets = Path(args.assets).resolve()
    if OUT.exists() and not args.force:
        sys.exit(f"{OUT} exists; --force replaces it")
    root = os.path.normcase(str(assets)) + os.sep
    seen = set()

    def hook(event, a):
        if event in ('open', 'os.listdir', 'os.scandir') and a and isinstance(a[0], (str, os.PathLike)):
            p = os.path.normcase(os.path.abspath(os.fspath(a[0])))
            if p.startswith(root):
                seen.add(p[len(root):])
    real_stat = os.stat

    def stat(path, *x, **k):
        p = os.path.normcase(os.path.abspath(os.fspath(path))) if isinstance(path, (str, os.PathLike)) else ''
        if p.startswith(root):
            seen.add(p[len(root):])
        return real_stat(path, *x, **k)
    sys.addaudithook(hook)
    os.stat = stat
    # Gathering only: a phenotype with no maps (Heller's male_eu_md3) reads as black so the bake goes
    # on. What the bake itself should do there is for the CK's bake to settle.
    from fsftools import facegen
    import numpy as np
    real_read = facegen.FaceMaps._read

    def read(self, name):
        try:
            return real_read(self, name)
        except FileNotFoundError:
            return np.zeros(self.masks['null'].shape + (3,), np.float32)
    facegen.FaceMaps._read = read
    with tempfile.TemporaryDirectory() as td:
        (count, problems), _ = bake_humans(assets, Path(td))
    os.stat = real_stat
    print(f"baked {count}, problems {problems}")
    files = {r for r in seen if (assets / r).is_file()}
    for r in list(files):                     # the FCT masks are read as a set
        if os.path.basename(r).startswith('fct_'):
            files |= {os.path.join(os.path.dirname(r), n.lower()) for n in os.listdir(assets / os.path.dirname(r))
                      if n.lower().startswith('fct_') and n.lower().endswith('.dds')}
    if OUT.exists():
        shutil.rmtree(OUT)
    total = 0
    for r in sorted(files):
        dest = OUT / r
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(assets / r, dest)
        total += dest.stat().st_size
    print(f"{len(files)} files, {total / 1e6:.1f} MB -> {OUT}")


if __name__ == '__main__':
    main()
