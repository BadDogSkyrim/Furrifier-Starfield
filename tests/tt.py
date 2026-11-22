"""The few test helpers the script tests (moved from PyNifly's pynifly_tests) use, with PyNifly's
own semantics: is_* log a failure and return falsy, for use as `assert TT.is_eq(...)`."""
import functools
import logging
import os

import pytest

import fsftools  # noqa: F401 -- puts pyn on the path
from pyn import niflytools as NT

log = logging.getLogger("fsftools.tests")

# Unpacked vanilla assets, and the installed game's Data folder (the vanilla plugins).
SF_ASSETS = os.path.join('C:' + os.sep, 'Modding', 'Starfield', '00StarfieldAssets')
SF_DATA = os.path.join('C:' + os.sep, 'Steam', 'steamapps', 'common', 'Starfield', 'Data')
ASSET_ROOTS = {'SF': SF_ASSETS, 'SF_DATA': SF_DATA}


def requires_assets(*roots):
    """The test reads these asset roots; a missing one fails it, as a broken setup."""
    unknown = [r for r in roots if r not in ASSET_ROOTS]
    if unknown:
        raise ValueError(f"Unknown asset root {unknown}. Known: {sorted(ASSET_ROOTS)}")

    def wrap(fn):
        @functools.wraps(fn)
        def run():
            missing = [ASSET_ROOTS[r] for r in roots if not os.path.isdir(ASSET_ROOTS[r])]
            if missing:
                pytest.fail(f"asset folders missing: {missing}")
            return fn()
        return run
    return wrap


def is_equiv(actual, expected, msg=None, e=0.0001):
    """Nearly equal: scalars, vectors or matrices."""
    if hasattr(actual, '__getitem__'):
        if hasattr(actual[0], '__getitem__'):
            ok = NT.MatNearEqual(actual, expected, epsilon=e)
        else:
            ok = NT.VNearEqual(actual[:], expected, epsilon=e)
    else:
        ok = NT.NearEqual(actual, expected, epsilon=e)
    if not ok:
        log.error(f"ASSERT FAIL: {msg + ': ' if msg else ''}{actual} != {expected}")
    return ok


def is_true(value, msg=""):
    if value:
        return True
    log.error(f"ASSERT FAIL: {msg} (got {value!r})")


def is_eq(*args):
    """All but the last equal; the last is the message (when there are more than two)."""
    if len(args) > 2:
        msg, values = args[-1] + " are equal ", args[0:-1]
    else:
        msg, values = "", args
    if values[0:-1] == values[1:]:
        return True
    log.error(f"ASSERT FAIL: {msg}{values}")


def is_ge(actual, expected, msg, e=0.0001):
    if actual >= expected:
        return True
    log.error(f"ASSERT FAIL: {msg}: {actual} >= {expected}")
    return False
