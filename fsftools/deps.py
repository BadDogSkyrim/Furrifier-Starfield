"""Find the libraries the tools stand on and put them on sys.path: PyNifly's `pyn` and esplib.

PyNifly is looked for, in order:
  1. the PYNIFLY environment variable: a PyNifly checkout, or its io_scene_nifly folder;
  2. C:\\Modding\\PyNifly, a development checkout;
  3. the PyNifly extension installed in Blender (newest Blender first), which carries pyn and
     its DLL, so a user who has PyNifly needs nothing more.

esplib is used if it imports (pip install). Otherwise the ESPLIB environment variable names a
checkout.
"""
import glob
import os
import re
import sys

DEV_PYNIFLY = r'C:\Modding\PyNifly'


def _has_pyn(folder):
    return os.path.isfile(os.path.join(folder, 'pyn', 'pynifly.py'))


def _blender_version(path):
    m = re.search(r'[\\/]Blender[\\/](\d+)\.(\d+)[\\/]', path)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def pynifly_candidates():
    """Folders that might hold PyNifly's io_scene_nifly, in the order they're tried."""
    out = []
    env = os.environ.get('PYNIFLY')
    if env:
        out += [env, os.path.join(env, 'io_scene_nifly')]
    # A development checkout before Blender's copies: Blender can hold a stale one (the VS Code
    # extension's vscode_development folder does), and only a developer has the checkout.
    out.append(os.path.join(DEV_PYNIFLY, 'io_scene_nifly'))
    appdata = os.environ.get('APPDATA')
    if appdata:
        found = glob.glob(os.path.join(appdata, 'Blender Foundation', 'Blender', '*',
                                       'extensions', '*', '*'))
        out += sorted(found, key=_blender_version, reverse=True)
    return out


def pynifly_dir():
    """The io_scene_nifly folder to use, or None."""
    return next((c for c in pynifly_candidates() if _has_pyn(c)), None)


def setup():
    """Put pyn and esplib on sys.path. Raises ImportError saying what's missing."""
    folder = pynifly_dir()
    if folder is None:
        raise ImportError("PyNifly not found: install the PyNifly extension in Blender, or set "
                          "PYNIFLY to a PyNifly folder")
    if folder not in sys.path:
        sys.path.insert(0, folder)
    try:
        import esplib  # noqa: F401
    except ImportError:
        env = os.environ.get('ESPLIB')
        for c in ([env, os.path.join(env, 'src')] if env else []):
            if os.path.isdir(os.path.join(c, 'esplib')):
                sys.path.insert(0, c)
                break
        else:
            raise ImportError("esplib not found: pip install esplib, or set ESPLIB to its folder") from None
