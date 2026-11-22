"""Shared modules for the FSF tools. Importing the package finds PyNifly and esplib (see deps),
and makes the tools beside it (sf_tintbake, sf_racecheck...) importable by the modules that use them."""
import os
import sys

from . import deps

deps.setup()

_TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TOOLS not in sys.path:
    sys.path.append(_TOOLS)
