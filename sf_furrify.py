"""Starfield Furrifier — make the NPC population furry.

Usage:
    python sf_furrify.py [--out FOLDER | FOLDER\\Plugin.esm] [--hair] [--facegen] [--keep-hair] ...

--out is the output folder, or a plugin file in it (a folder gets FSFNPC.esm; no --out is the game's
Data folder). Everything the run writes goes there: the plugin, the fitted hair and its plugin
(--hair), the FaceGen (--facegen), the crowd skeleton (--crowd-skeleton). The scheme and the race
definitions come from Data\\FSFTools\\furrify, where a mod ships them, unless --scheme/--races say.

Reads the active load order (or a specific plugin tree), classifies every HumanRace NPC, assigns
furry races by weighted probability, and writes one ESM with the NPC overrides, the crowd outfits
and heads, and the outfits holding a piece the race has its own copy of (race_pieces: bare-skin
arms, helmets). Crowd actors themselves aren't changed: see crowd_builder.
"""
import argparse
import fnmatch
import sys
import time
from pathlib import Path

from fsftools.classify import Classifier, npc_attributes
from fsftools.probability import RaceAssigner
from fsftools.config import load_scheme, load_builtin, load_races
from fsftools.plugin_loader import (discover_data_dir, load_order_for_plugin,
                           load_full_order, load_plugins, enumerate_human_npcs,
                           npc_sex)
from fsftools.crowd_builder import (CROWD_RACE, CrowdError, RETIRED_PLUGIN, add_crowd, copy_skeleton, crowd_plan,
                           crowd_skeleton_paths, write_test_batch)
from fsftools.furrify_npc import plan_individual_furrification, NpcChange
from fsftools.progress import Progress
from fsftools.race_pieces import add_race_pieces
from esplib import Plugin
from fsftools.race_data import RaceAppearance, avm_index, race_avm, tint_plugin_path, without_tint_plugins


PLUGIN_EXTENSIONS = ('.esm', '.esp', '.esl')
DEFAULT_PLUGIN = 'FSFNPC.esm'


def resolve_out(out, data_dir: Path):
    """(output folder, plugin name) from --out: a path ending in a plugin extension is the plugin
    (a bare name goes in Data), anything else a folder that gets the default plugin; none is Data."""
    if out is None:
        return Path(data_dir), DEFAULT_PLUGIN
    out = Path(out)
    if out.suffix.lower() in PLUGIN_EXTENSIONS:
        return (Path(data_dir) if out.parent == Path('.') else out.parent), out.name
    return out, DEFAULT_PLUGIN


HERE = Path(__file__).resolve().parent
# Where a mod ships its furrifier data, under the game's Data folder.
TOOLS_DATA = Path('FSFTools') / 'furrify'


def parse_args():
    p = argparse.ArgumentParser(description="Starfield Furrifier")
    p.add_argument('--scheme', type=Path, default=None,
                   help=f'Scheme TOML (probabilities, pins, excludes). Default: Data\\{TOOLS_DATA}\\scheme.toml')
    p.add_argument('--builtin', type=Path, default=HERE / 'fsftools' / 'builtin.toml',
                   help='Classification rules TOML (default: the one shipped with the tools)')
    p.add_argument('--races', type=Path, default=None,
                   help=f'Directory of per-race TOML definitions. Default: Data\\{TOOLS_DATA}\\races')
    p.add_argument('--plugin', type=str, default=None,
                   help='Load order from this plugin + masters (default: full active order)')
    p.add_argument('--data', type=Path, default=None,
                   help='Game Data directory (default: auto-discover)')
    p.add_argument('--overlay', type=Path, metavar='DIR',
                   help='A folder laid out like Data whose files win over Data\'s, like a mod installed '
                        'but not deployed (an overlay.toml there can hide the mods it replaces)')
    p.add_argument('--out', type=Path, default=None,
                   help=f'Output folder, or a plugin in it (a folder gets {DEFAULT_PLUGIN}; a name alone '
                        f'goes in Data). Default: Data\\{DEFAULT_PLUGIN}')
    p.add_argument('--only', action='append', default=[], metavar='GLOB',
                   help='Only furrify NPCs whose EditorID matches (repeatable), and leave crowds '
                        'alone unless --crowd-test; for test plugins')
    p.add_argument('--crowd-test', action='store_true',
                   help='Also write test NPCs, one per sex and body type, and a console batch that '
                        'places them: bat fsfnpc_crowd')
    p.add_argument('--crowd-skeleton', action='store_true',
                   help='Copy the crowd skeleton with tail bones over vanilla\'s, in the output folder')
    p.add_argument('--facegen', action='store_true',
                   help='Also bake each NPC\'s FaceGen, in the output folder')
    p.add_argument('--hair', action='store_true',
                   help='Fit the human hair to each race\'s head first, into the output folder and its '
                        'hair plugin (only the hairs whose sources changed are fitted again)')
    p.add_argument('--hair-only', action='store_true', help='Fit the hair and stop')
    p.add_argument('--ears-fixed', action='store_true',
                   help='The fitted hair doesn\'t follow the ears (default: it does)')
    p.add_argument('--keep-hair', action='store_true',
                   help='Furrified NPCs keep their own hair, fitted to the race\'s head where the load '
                        'order has a fitted copy (--hair makes them), and crowds their outfit\'s hair list')
    p.add_argument('--assets', type=Path, metavar='DIR',
                   help='Unpacked vanilla assets, laid out like Data: the FaceGen bake reads vanilla '
                        'parts (a kept hair) from here when they aren\'t loose in Data')
    p.add_argument('--dry-run', action='store_true',
                   help='Classify and assign but do not write the plugin')
    p.add_argument('--verbose', '-v', action='store_true')
    p.add_argument('--log', type=Path, metavar='FILE',
                   help='Also write everything printed, errors included, to this file')
    return p.parse_args()


def main():
    args = parse_args()
    if args.log:
        from fsftools import tee
        tee.start(args.log)

    # Discover data directory: the scheme and race definitions default to the copies a mod
    # deploys there.
    data_dir = args.data or discover_data_dir()
    print(f"Data: {data_dir}")
    if args.overlay:
        from fsftools.overlay import overlay_roots
        data_dir = Path(overlay_roots([data_dir], args.overlay)[0][0])
    out_dir, out_name = resolve_out(args.out, data_dir)
    print(f"Output: {out_dir / out_name}")
    if args.scheme is None:
        args.scheme = Path(data_dir) / TOOLS_DATA / 'scheme.toml'
    if args.races is None:
        args.races = Path(data_dir) / TOOLS_DATA / 'races'
    for what, path, test in (('scheme', args.scheme, Path.is_file), ('races folder', args.races, Path.is_dir)):
        if not test(path):
            print(f"ERROR: no {what} at {path}")
            return 2

    # Load configuration
    scheme = load_scheme(args.scheme)
    builtin = load_builtin(args.builtin)
    races = load_races(args.races)

    print(f"Scheme: {len(scheme.class_probabilities)} classes, "
          f"{len(scheme.npc_assignments)} pinned NPCs")
    print(f"Rules: {len(builtin.rules)} classification rules")
    print(f"Races: {', '.join(r.editorid for r in races.values())}")

    # What crowds will get; a bad configuration stops here.
    crowds = None
    if not args.only or args.crowd_test:
        try:
            crowds = crowd_plan(races, scheme)
        except CrowdError as e:
            print(f"ERROR: {e}")
            return 2
        for line in crowds.warnings:
            print(f"  WARNING: {line}")

    classifier = Classifier(builtin.rules)
    assigner = RaceAssigner(scheme, races)

    # Build load order
    t0 = time.time()
    if args.plugin:
        order = load_order_for_plugin(data_dir, args.plugin)
    else:
        order = load_full_order(data_dir)
    # Our own previous output must not count as an override: its NPCs are no longer human.
    order = [n for n in order if n.lower() != out_name.lower()]
    if crowds and crowds.races and RETIRED_PLUGIN.lower() in (n.lower() for n in order):
        print(f"  WARNING: {RETIRED_PLUGIN} is in the load order. This plugin replaces it: disable it.")
    # The player plugins are alternatives; whichever is active must not change the result.
    order = without_tint_plugins(order, [r.tint_plugin for r in races.values()])
    plugins = load_plugins(data_dir, order, verbose=args.verbose)
    print(f"Loaded {len(order)} plugins in {time.time()-t0:.1f}s")

    # What each race offers; a config naming something its plugins lack stops here.
    base_avm = avm_index(plugins, order)
    appearances = {}
    try:
        for edid, r in races.items():
            tint = None
            if r.tint_plugin:
                path = tint_plugin_path(r.tint_plugin, data_dir)
                tint = Plugin.load(str(path), only_signatures={'AVMD'})
                print(f"  {edid}: tints from {path}")
            appearances[edid] = RaceAppearance(r, plugins, race_avm(base_avm, tint), data_dir)
    except ValueError as e:
        print(f"ERROR: {e}")
        return 2
    for appearance in appearances.values():
        for line in appearance.warnings:
            print(f"  WARNING: {line}")

    # Hair first: --keep-hair takes the fitted copies, so they must be in the load order.
    if args.hair or args.hair_only:
        from fsftools import hair_stage
        from fsftools.plugin_loader import use_plugin_file
        t_hair = time.time()
        print("\nFitting hair:")
        try:
            hair_plugin = hair_stage.run(plugins, data_dir, list(races.values()), out_dir, assets=args.assets,
                                         ears_move_hair=not args.ears_fixed, dry_run=args.dry_run)
        except ValueError as e:
            print(f"ERROR: {e}")
            return 2
        print(f"  ({time.time() - t_hair:.0f}s)")
        if args.hair_only:
            return 0
        if hair_plugin is not None:
            use_plugin_file(plugins, order, hair_plugin)

    # Classify and assign all human NPCs
    t1 = time.time()
    individual_changes: list[NpcChange] = []
    class_counts: dict[str, int] = {}
    race_counts: dict[str, int] = {}
    no_appearance = human = no_config = 0

    bar = Progress('Classifying NPCs')
    for npc, vanilla_race_edid in enumerate_human_npcs(plugins, order):
        bar.update()
        if vanilla_race_edid == CROWD_RACE:  # crowds change through their outfits
            continue
        if args.only and not any(fnmatch.fnmatch((npc.editor_id or '').lower(), g.lower()) for g in args.only):
            continue
        attrs = npc_attributes(npc, plugins)
        cls = classifier.classify(attrs)
        class_counts[cls] = class_counts.get(cls, 0) + 1

        edid = attrs['EDITORID']
        if cls == 'CLASS_SKIP':
            no_appearance += 1
            continue

        result = assigner.assign(edid, cls)

        if result is None:
            race_counts['HUMAN'] = race_counts.get('HUMAN', 0) + 1
            human += 1
            continue

        race_edid, breed = result
        race_counts[race_edid] = race_counts.get(race_edid, 0) + 1

        appearance = appearances.get(race_edid)
        if appearance is None:
            print(f"  WARNING: no race config for {race_edid}, skipping {edid}")
            no_config += 1
            continue

        skin_tone = assigner.assign_skin_tone(edid, race_edid, breed, npc_sex(npc))
        phenotype = assigner.assign_phenotype(edid, race_edid, breed, npc_sex(npc))

        change = plan_individual_furrification(
            npc, appearance, breed, skin_tone, phenotype, assigner,
            keep_hair_from=plugins if args.keep_hair else None)
        individual_changes.append(change)

    bar.close()
    elapsed = time.time() - t1
    total = sum(class_counts.values())
    print(f"\nClassified {total} NPCs in {elapsed:.1f}s:")
    for cls, n in sorted(class_counts.items(), key=lambda x: -x[1]):
        print(f"  {cls}: {n}")

    print("\nAssignment:")
    for r, n in sorted(race_counts.items(), key=lambda x: -x[1]):
        print(f"  {r}: {n}")

    print(f"\n{len(individual_changes)} individual NPCs to furrify")
    if crowds:
        print(f"Crowd shares: {crowds.shares or 'none'}; heads per race and breed: "
              f"{ {r: {b: len(p) for b, p in plan.heads.items()} for r, plan in crowds.races.items()} }")
    print(f"{no_appearance} have no appearance data and are not furrified")
    if human:
        print(f"{human} stay human (the odds gave them no furry race)")
    if no_config:
        print(f"{no_config} skipped: their race has no config")

    # Show samples
    print("\nSample individual changes:")
    for c in individual_changes[:10]:
        print(f"  {c.npc_editorid} -> {c.new_race_edid}/{c.breed_name} tone={c.new_ston} "
              f"{c.phenotype} parts={[h.editor_id for h in c.head_parts]} "
              f"tints={[t.option for t in c.tints]}")

    if args.dry_run:
        return 0

    # Write the plugin
    from fsftools.plugin_writer import write_output

    # Masters: Starfield.esm + any race plugins
    masters = ['Starfield.esm']
    for r in races.values():
        if r.plugin not in masters:
            masters.append(r.plugin)
    # Kept hair fitted to a race's head comes from the hair plugin (hair_stage).
    kept_from = {Path(h.plugin.file_path).name for c in individual_changes for h in c.kept_hair}
    for name in [n for n in order if n in kept_from]:
        if name.lower() not in (m.lower() for m in masters):
            masters.append(name)
    if args.keep_hair:
        kept = sum(len(c.kept_hair) for c in individual_changes)
        unfitted = sorted({e for c in individual_changes for e in c.unfitted_hair})
        print(f"  Kept hair: {kept - sum(len(c.unfitted_hair) for c in individual_changes)} fitted to "
              f"the race's head; {len(unfitted)} hairs have no fitted copy and stay human")
        if unfitted and args.verbose:
            print('    ' + ', '.join(unfitted))

    out_path = out_dir / out_name
    out_dir.mkdir(parents=True, exist_ok=True)
    test_npcs, crowd_counts, crowd_notes = [], {}, []
    piece_counts, piece_notes = {}, []

    def extend(out):
        nonlocal test_npcs, crowd_counts, crowd_notes, piece_counts, piece_notes
        # First: it can add masters, and the crowd records refer to each other by this plugin's
        # index, which is the length of the master list when they're built.
        piece_counts, piece_notes = add_race_pieces(out, plugins, order, masters, data_dir, list(races))
        if crowds:
            test_npcs, crowd_counts, crowd_notes = add_crowd(
                out, plugins, order, masters, data_dir, crowds, test_npcs=args.crowd_test,
                keep_hair=args.keep_hair)

    try:
        written, errors = write_output(
            out_path, individual_changes, plugins, masters,
            data_dir=data_dir, verbose=args.verbose, extend=extend)
        skeleton = copy_skeleton(plugins, crowds, data_dir, out_dir) \
            if crowds and args.crowd_skeleton else []
    except CrowdError as e:
        print(f"ERROR: {e}")
        return 2

    print(f"\nOutfits given the race's own pieces: {piece_counts.get('outfits', 0)} "
          f"(skin {piece_counts.get('skin', 0)}, other {piece_counts.get('other', 0)}). "
          f"Rerun after adding or reordering mods that change outfits.")
    for line in piece_notes:
        print(f"  ISSUE: {line}")

    if crowds and crowds.races:
        print(f"\nCrowds: {crowd_counts}")
        for line in crowd_notes:
            print(f"  ISSUE: {line}")
        if skeleton:
            print(f"Crowd skeleton: {len(skeleton)} files under {out_dir}")
        else:
            # Vanilla's crowd skeleton is only in a BA2: a loose one at its path is the copy with tails.
            missing = [p for p in crowd_skeleton_paths(plugins, data_dir) if not p.exists()]
            if missing:
                print(f"  WARNING: no crowd skeleton with tail bones in Data ({missing[0]}); "
                      f"copy it with --crowd-skeleton")
    if test_npcs:
        # The game reads bat files from its own folder; a plugin written elsewhere is a test.
        folder = data_dir.parent if out_path.parent == data_dir else out_path.parent
        lines = write_test_batch(folder / 'fsfnpc_crowd.txt', out_path.name, test_npcs, data_dir,
                                 load_full_order(data_dir))
        print(f"Test NPCs: bat fsfnpc_crowd ({folder / 'fsfnpc_crowd.txt'}): {lines[0]} ...")

    if args.facegen:
        from fsftools.facegen import bake_all
        bakeable = [c for c in individual_changes if c.written]
        t2 = time.time()
        baked, problems = bake_all(bakeable, appearances, plugins, data_dir, out_dir,
                                   assets=args.assets)
        print(f"\nFaceGen: baked {baked} of {len(individual_changes)} NPCs in {time.time()-t2:.1f}s under {out_dir}")
        for line in problems:
            print(f"  WARNING: {line}")

    return 1 if errors else 0


if __name__ == '__main__':
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        # Every file is written whole or not at all (safe_write), so what's on disk is usable:
        # the files finished before the stop, and the previous run's for the rest.
        print('\nStopped. Files finished before the stop are kept; nothing is half-written.')
        sys.exit(130)
