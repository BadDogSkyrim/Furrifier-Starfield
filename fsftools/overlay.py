"""A folder that reads as the game's Data with another folder's files laid over it: --overlay.

Like a mod that's installed but not deployed. The view is built from links, so nothing is copied:
a file is a hard link (or, across volumes, a symlink), a folder no file of the overlay touches is a
directory junction to the real one. Only folders on the overlay's paths are real.

An overlay can also *replace* mods: files present in those mod folders (a mod manager's staging
folders) are hidden from Data, so the view sees the overlay's version of the mod and never the
deployed one. A test snapshot of a mod uses this so a file missing from the snapshot fails loudly
instead of being read live.

The overlay folder may hold `overlay.toml` with `replaces = ["C:/.../Mods/FSF", ...]`, and
`hide = ["FSFNPC.esm", ...]`: Data paths hidden by name, whichever mod deploys them.

Clearing a view unlinks its links; it never follows one, so Data and the overlay are untouched.
"""
import hashlib
import os
import shutil
import tempfile
import tomllib
from pathlib import Path

CONFIG = 'overlay.toml'


def _is_link(entry) -> bool:
    return entry.is_symlink() or (hasattr(entry, 'is_junction') and entry.is_junction())


def clear_view(view):
    """Remove a view: unlink every link, recurse only into real folders."""
    view = Path(view)
    if not view.exists() and not view.is_symlink():
        return
    with os.scandir(view) as it:
        for e in it:
            if _is_link(e):
                try:
                    os.unlink(e.path)         # a file link, or a symlink
                except OSError:
                    os.rmdir(e.path)          # a junction or directory symlink: the link only
            elif e.is_dir(follow_symlinks=False):
                clear_view(e.path)
            else:
                os.unlink(e.path)             # a hard link: the original keeps its data
    os.rmdir(view)


def _junction(target: Path, link: Path):
    try:
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    except (ImportError, OSError):
        os.symlink(target, link, target_is_directory=True)


def _link_file(target: Path, link: Path):
    try:
        os.link(target, link)
    except OSError:
        try:
            os.symlink(target, link)
        except OSError:
            shutil.copy2(target, link)


def _listing(folder: Path) -> dict:
    """{lowercase name: name} of a folder's entries, {} if it isn't one."""
    try:
        return {n.lower(): n for n in os.listdir(folder)}
    except (FileNotFoundError, NotADirectoryError):
        return {}


def _name_tree(paths) -> dict:
    """{'fsfnpc.esm': None, 'meshes': {'actors': {...}}}: the named paths, lowercase, as a tree."""
    tree = {}
    for p in paths:
        parts = [x.lower() for x in str(p).replace('\\', '/').split('/') if x]
        node = tree
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if node is None:
                break
        else:
            node[parts[-1]] = None
    return tree


def _build(base: Path, over: Path, hidden: list, dest: Path, named=None):
    """dest = base with over laid on top, minus what any hidden folder holds and the named paths
    (a _name_tree) -- all case-blind. Only Data's own files are hidden; the overlay's always show."""
    dest.mkdir(parents=True)
    named = named or {}
    live = _listing(base) if base else {}
    mine = _listing(over) if over else {}
    hide = [_listing(h) for h in hidden]
    for key in sorted(set(live) | set(mine)):
        if key in mine:
            o = over / mine[key]
            b = base / live[key] if key in live else None
            name = mine[key]
            if o.is_dir():
                sub_hidden = [h / hl[key] for h, hl in zip(hidden, hide) if key in hl and (h / hl[key]).is_dir()]
                if b is not None and b.is_dir():
                    _build(b, o, sub_hidden, dest / name, named.get(key))
                else:
                    _junction(o, dest / name)
            else:
                _link_file(o, dest / name)
            continue
        b, name = base / live[key], live[key]
        if key in named and named[key] is None:
            continue                                # a named file (or folder): hidden
        holders = [h / hl[key] for h, hl in zip(hidden, hide) if key in hl]
        below = named.get(key)
        if not holders and not below:
            (_junction if b.is_dir() else _link_file)(b, dest / name)
        elif b.is_dir():
            _build(b, None, [h for h in holders if h.is_dir()], dest / name, below)
        # else: a file a replaced mod holds -- hidden


def load_config(overlay):
    """(mod folders the overlay replaces, Data paths it hides), from its overlay.toml."""
    path = Path(overlay) / CONFIG
    if not path.is_file():
        return [], []
    with open(path, 'rb') as f:
        cfg = tomllib.load(f)
    return [Path(p) for p in cfg.get('replaces', [])], list(cfg.get('hide', []))


def overlay_roots(roots, overlay, log=print):
    """For a tool's --overlay: `roots` (data folders, Data first) with the first that exists
    swapped for its merged view. Returns (roots, rebase), where rebase(path) moves a path under
    that Data folder into the view and leaves any other path alone."""
    roots = [str(r) for r in roots]
    i = next((n for n, r in enumerate(roots) if os.path.isdir(r)), None)
    if i is None:
        raise FileNotFoundError(f"no data folder to overlay among {roots}")
    data = os.path.normcase(os.path.abspath(roots[i]))
    view = merged_view(roots[i], overlay)
    log(f"Overlay: {overlay} over {roots[i]}, read through {view}")
    roots[i] = str(view)

    def rebase(path):
        p = os.path.abspath(str(path))
        if os.path.normcase(p).startswith(data + os.sep):
            return os.path.join(str(view), p[len(data) + 1:])
        return str(path)
    return roots, rebase


def merged_view(data, overlay, replaces=None, hide=None, where=None) -> Path:
    """Build (or rebuild) the view of `data` with `overlay` over it, and return its folder.

    replaces: mod folders whose files are hidden from data; default from overlay.toml.
    hide: paths relative to Data hidden by name, whichever mod deploys them (a furrifier output
        plugin, say); default from overlay.toml. Cheap: unlike a replaced mod, nothing is walked.
    where: the view's folder; default a temp folder named for data and overlay."""
    data, overlay = Path(data).resolve(), Path(overlay).resolve()
    if not overlay.is_dir():
        raise FileNotFoundError(f"overlay {overlay} isn't a folder")
    cfg_replaces, cfg_hide = load_config(overlay)
    replaces = [Path(r) for r in (cfg_replaces if replaces is None else replaces)]
    hide = cfg_hide if hide is None else hide
    if where is None:
        key = hashlib.sha1(f"{data}|{overlay}".lower().encode()).hexdigest()[:12]
        where = Path(tempfile.gettempdir()) / 'fsftools_overlay' / key
    where = Path(where)
    clear_view(where)
    _build(data, overlay, [r for r in replaces if r.is_dir()], where, _name_tree(hide))
    return where
