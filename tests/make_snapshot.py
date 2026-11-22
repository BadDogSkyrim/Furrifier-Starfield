"""Take a snapshot of the mods the tests read, as tests/fixtures/fsf: an --overlay that replaces them.

    1. Trace a test run (records every file it reads):
         set FSF_TRACE=C:\\tmp\\trace.log
         set PYTHONPATH=<FSFTools>\\tests\\trace
         python -m pytest
    2. python tests/make_snapshot.py C:\\tmp\\trace.log [--force]

Every traced file that one of MODS holds is copied from that mod's folder (its staging folder, not
Data), keeping its path; a folder the run listed brings the mod's files in that folder, a glob the
files it matches. The plugins always come along. overlay.toml says which mods the snapshot replaces,
so their deployed files are hidden from the tests and a file the snapshot lacks fails loudly.

Refreshing the snapshot is expected to break tests: triage each as too specific or a real bug. The
CK's FaceGen references must be re-baked from the same mods: see tests/fixtures/ck_bake/README.txt.
"""
import argparse
import datetime
import fnmatch
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT = os.path.join(HERE, 'fixtures', 'fsf')
DATA = r'C:\Steam\steamapps\common\Starfield\Data'
MODS = [r'C:\Modding\Starfield\Mods\FSF', r'C:\Modding\Starfield\Mods\FSFPlayer_Fox',
        r'C:\Modding\Starfield\Mods\FSFPlayer_Hyena']
PLUGINS = ['FSF.esm', 'FSFPlayer_FOX.esm', 'FSFPlayer_HYENA.esm']
# Hidden by name, whichever profile deploys them: the furrifier's own output (FSF_test, FSF_Gameplay),
# whose tens of thousands of FaceGen files would be too slow to hide as a replaced mod.
HIDE = ['FSFNPC.esm', 'FSFNPC_test.esm']
LIST_LIMIT = 400
# Read as a set, stopping at the first missing one, so a trace finds them one per run: take them whole.
ALWAYS = ['Textures/Actors/*/faces/chargen/FCT_*_mask.dds']


VIEW = os.path.join(os.path.dirname(HERE), 'tests', 'out', 'data_view')


def relative(path):
    """(path relative to Data, the tests' view of it, or one of MODS) or None."""
    p = os.path.normcase(os.path.abspath(path))
    for root in [DATA, VIEW] + MODS:
        r = os.path.normcase(os.path.abspath(root)) + os.sep
        if p.startswith(r):
            return os.path.abspath(path)[len(r):]
    return None


def in_mods(rel):
    """[(mod, rel)] for each mod that holds rel."""
    return [(m, rel) for m in MODS if os.path.exists(os.path.join(m, rel))]


def collect(trace_lines, warn):
    files = {}                              # rel (lowercase) -> (mod, rel)
    for line in trace_lines:
        kind, _, path = line.rstrip('\n').partition('\t')
        rel = relative(path) if kind != 'glob' else relative(os.path.dirname(path))
        if rel is None:
            continue
        if kind in ('open', 'stat'):
            for mod, r in in_mods(rel):
                if os.path.isfile(os.path.join(mod, r)):
                    files[r.lower()] = (mod, r)
        elif kind == 'list':
            for mod, r in in_mods(rel):
                folder = os.path.join(mod, r)
                if not os.path.isdir(folder):
                    continue
                names = [n for n in os.listdir(folder) if os.path.isfile(os.path.join(folder, n))]
                if len(names) > LIST_LIMIT:
                    warn(f"skipped listing {folder}: {len(names)} files")
                    continue
                for n in names:
                    files[os.path.join(r, n).lower()] = (mod, os.path.join(r, n))
        elif kind == 'glob':
            pattern = os.path.basename(path)
            for mod, r in in_mods(rel):
                folder = os.path.join(mod, r)
                for n in os.listdir(folder):
                    if fnmatch.fnmatch(n.lower(), pattern.lower()) and os.path.isfile(os.path.join(folder, n)):
                        files[os.path.join(r, n).lower()] = (mod, os.path.join(r, n))
    for name in PLUGINS:
        for mod, r in in_mods(name):
            files[name.lower()] = (mod, r)
    # A phenotype's face maps are read one after another, stopping at the first missing: take the set.
    import re
    for key, (mod, r) in list(files.items()):
        m = re.match(r'(.*)_(ao|rough|normal)\.dds$', r, re.I)
        if m:
            for suffix in ('ao', 'rough', 'normal'):
                sib = f"{m.group(1)}_{suffix}.dds"
                if os.path.isfile(os.path.join(mod, sib)):
                    files[sib.lower()] = (mod, sib)
    import glob
    for pattern in ALWAYS:
        for mod in MODS:
            for path in glob.glob(os.path.join(mod, *pattern.split('/'))):
                r = os.path.relpath(path, mod)
                files[r.lower()] = (mod, r)
    return files


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('trace', nargs='+', help="trace logs from FSF_TRACE runs")
    ap.add_argument('--force', action='store_true', help="replace an existing snapshot")
    args = ap.parse_args(argv)
    if os.path.exists(SNAPSHOT):
        if not args.force:
            sys.exit(f"{SNAPSHOT} exists; --force replaces it")
        shutil.rmtree(SNAPSHOT)
    lines = []
    for t in args.trace:
        with open(t, encoding='utf-8') as f:
            lines += f.readlines()
    warnings = []
    files = collect(lines, warnings.append)
    total = 0
    for mod, rel in sorted(files.values(), key=lambda x: x[1].lower()):
        dest = os.path.join(SNAPSHOT, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(os.path.join(mod, rel), dest)
        total += os.path.getsize(dest)
    with open(os.path.join(SNAPSHOT, 'overlay.toml'), 'w', encoding='utf-8', newline='\n') as f:
        f.write("# The mods this snapshot stands in for: their deployed files are hidden.\n")
        f.write("replaces = [\n" + "".join(f'    "{m.replace(os.sep, "/")}",\n' for m in MODS) + "]\n")
        f.write("# Data paths hidden by name, whichever mod deploys them.\n")
        f.write("hide = [" + ", ".join(f'"{h}"' for h in HIDE) + "]\n")
    with open(os.path.join(SNAPSHOT, 'MANIFEST.txt'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(f"Snapshot taken {datetime.datetime.now():%Y-%m-%d %H:%M} by tests/make_snapshot.py\n")
        f.write(f"{len(files)} files, {total / 1e6:.1f} MB\n\n")
        for mod, rel in sorted(files.values(), key=lambda x: x[1].lower()):
            f.write(f"{os.path.basename(mod)}\t{rel}\n")
    for w in warnings:
        print("WARNING:", w)
    print(f"{len(files)} files, {total / 1e6:.1f} MB -> {SNAPSHOT}")


if __name__ == '__main__':
    main()
