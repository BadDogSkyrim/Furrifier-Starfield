"""Run FSFTools' Blender-side tests headless, with PyNifly's test harness from a PyNifly checkout:

    blender --background --python tests/blender/run_blender_tests.py [-- TEST_NAME ...]

These need PyNifly's source (its tests package and test files), not just the installed
extension, so they're for development. Blender exits 1 if a test failed."""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

# fsftools.deps finds PyNifly; load it alone, since importing the package would also put
# PyNifly's pyn on the path a second time under another name.
spec = importlib.util.spec_from_file_location('fsftools_deps', os.path.join(ROOT, 'fsftools', 'deps.py'))
deps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deps)
addon = deps.pynifly_dir()
pynifly = os.path.dirname(addon) if addon else None
if not pynifly or not os.path.isdir(os.path.join(pynifly, 'tests', 'blender')):
    raise SystemExit("These tests need a PyNifly checkout (set PYNIFLY): its tests folder wasn't found")

os.environ.setdefault('PYNIFLY_DEV_ROOT', os.path.dirname(pynifly))
for p in (pynifly, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import tests.blender_tests as BT  # noqa: E402 -- PyNifly's runner
import test_uv_transfer_blender as M  # noqa: E402

names = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
tests = [getattr(M, n) for n in names] if names else \
    [v for k, v in vars(M).items() if k.startswith('TEST_') and callable(v)]
failed = BT.do_tests(target_tests=tests)
sys.exit(1 if failed else 0)
