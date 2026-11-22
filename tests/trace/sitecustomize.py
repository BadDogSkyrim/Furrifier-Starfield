"""Records the files a test run reads, for make_snapshot.py. Loaded by every Python process when
tests/trace is on PYTHONPATH; does nothing unless FSF_TRACE names a log file.

Python's own reads come from the audit hook (open, listdir, scandir, glob). PyNifly reads nifs in
its DLL, out of the hook's sight, so NifFile is wrapped to log its path as well."""
import os
import sys

_LOG = os.environ.get('FSF_TRACE')

if _LOG:
    import atexit
    import importlib.abc
    import importlib.util

    _seen = set()
    _busy = [False]

    def _add(kind, path):
        try:
            p = os.fsdecode(path)
        except TypeError:
            return
        _seen.add(f"{kind}\t{os.path.abspath(p)}")

    def _hook(event, args):
        if _busy[0] or not args:
            return
        if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
            _add('open', args[0])
        elif event in ('os.listdir', 'os.scandir') and isinstance(args[0], (str, bytes, os.PathLike)):
            _add('list', args[0])
        elif event == 'glob.glob' and isinstance(args[0], (str, bytes)):
            _add('glob', args[0])

    def _write():
        _busy[0] = True
        with open(_LOG, 'a', encoding='utf-8') as f:
            for line in sorted(_seen):
                f.write(line + '\n')

    class _WrapNifFile(importlib.abc.MetaPathFinder):
        """After pyn.blocks.niffile loads, log every path NifFile is opened with."""
        def find_spec(self, name, path, target=None):
            if name != 'pyn.blocks.niffile':
                return None
            sys.meta_path.remove(self)
            spec = importlib.util.find_spec(name)
            sys.meta_path.insert(0, self)
            if spec is None:
                return None
            run = spec.loader.exec_module

            def exec_module(module):
                run(module)
                init = module.NifFile.__init__

                def logged(self, filepath=None, *a, **k):
                    if filepath:
                        _add('open', filepath)
                    return init(self, filepath, *a, **k)
                module.NifFile.__init__ = logged
            spec.loader.exec_module = exec_module
            return spec

    # Existence checks (os.path.exists/isfile/isdir, Path.exists) go through os.stat and raise no
    # audit event: log them too, so a file a run only looks for still lands in the snapshot.
    _stat = os.stat

    def _logged_stat(path, *a, **k):
        if not _busy[0] and isinstance(path, (str, bytes, os.PathLike)):
            _add('stat', path)
        return _stat(path, *a, **k)
    os.stat = _logged_stat

    sys.addaudithook(_hook)
    sys.meta_path.insert(0, _WrapNifFile())
    atexit.register(_write)
