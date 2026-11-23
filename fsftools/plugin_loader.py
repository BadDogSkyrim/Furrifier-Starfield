"""Load Starfield plugins via esplib and enumerate NPCs."""
from pathlib import Path
from typing import List

from esplib import LoadOrder, Plugin, PluginSet

# Disable string table loading immediately — Starfield BA2 format mismatch
Plugin._load_string_tables = lambda self: None

# Signatures we need loaded for classification + furrification
GROUPS = {
    'RACE', 'NPC_', 'ARMO', 'ARMA', 'MRPH', 'HDPT',
    'AVMD', 'FLST', 'OTFT', 'LVLI',
    'FACT', 'KYWD',  # for classification
    'GBFM',          # crowd regions
}

# Bethesda's own plugins (always present, assets in BA2)
IMPLICIT_MASTERS = ['Starfield.esm']
OFFICIAL_MASTERS = [
    'ShatteredSpace.esm', 'Constellation.esm', 'OldMars.esm', 'SFBGS003.esm',
    'SFBGS004.esm', 'SFBGS006.esm', 'SFBGS007.esm', 'SFBGS008.esm',
    'SFBGS00D.esm', 'SFBGS047.esm', 'SFBGS050.esm',
    'BlueprintShips-Starfield.esm', 'BlueprintShips-SFBGS050.esm',
]


def discover_data_dir() -> Path:
    """Find Starfield's Data directory."""
    try:
        from esplib.game_discovery import find_game
        info = find_game('sf1')
        if info and info.get('data_dir'):
            return Path(info['data_dir'])
    except Exception:
        pass
    # Fallback: common Steam path
    candidate = Path(r'C:\steam\steamapps\common\Starfield\Data')
    if candidate.is_dir():
        return candidate
    raise FileNotFoundError("Cannot find Starfield Data directory")


def load_order_for_plugin(data_dir: Path, plugin_name: str) -> List[str]:
    """Build a load order for a specific plugin + its masters (recursive)."""
    seen = set()
    order = []

    def _gather(name):
        key = name.lower()
        if key in seen:
            return
        seen.add(key)
        path = data_dir / name
        if not path.exists():
            return
        p = Plugin.load(str(path), only_signatures=set())
        for master in p.header.masters:
            _gather(master)
        order.append(name)

    for m in IMPLICIT_MASTERS:
        _gather(m)
    _gather(plugin_name)
    return order


def load_full_order(data_dir: Path, plugins_txt: Path = None) -> List[str]:
    """Build the full active load order from Plugins.txt (the user's, unless given). Plugins.txt
    lists every plugin it knows; only those marked * are active."""
    order = list(IMPLICIT_MASTERS)

    # Official masters (if present)
    for m in OFFICIAL_MASTERS:
        if (data_dir / m).exists():
            order.append(m)

    # CCC file
    ccc = data_dir / 'Starfield.ccc'
    if ccc.exists():
        for line in ccc.read_text().splitlines():
            line = line.strip()
            if line and (data_dir / line).exists() and line not in order:
                order.append(line)

    # Plugins.txt
    if plugins_txt is None:
        plugins_txt = Path.home() / 'AppData' / 'Local' / 'Starfield' / 'Plugins.txt'
    if plugins_txt.exists():
        for line in plugins_txt.read_text().splitlines():
            line = line.strip()
            if not line.startswith('*'):
                continue
            line = line[1:]
            if line and (data_dir / line).exists() and line not in order:
                order.append(line)

    return order


def load_plugins(data_dir: Path, order: List[str], verbose: bool = False) -> PluginSet:
    """Load all plugins in order into a PluginSet."""
    plugins = PluginSet(LoadOrder.from_list(order, data_dir=str(data_dir),
                                            game_id='sf1'))
    from fsftools.progress import Progress
    with Progress('Loading plugins', len(order)) as bar:
        for name in order:
            if verbose:
                print(f'  Loading {name}...')
            bar.update(0, name)
            plugins.load_plugin(name, only_signatures=GROUPS)
            bar.update(1, name)
    return plugins


def use_plugin_file(plugins: PluginSet, order: List[str], path: Path):
    """Load the plugin at `path` into the set, last in the load order, in place of any loaded copy
    of the same name (a deployed copy older than the one just written). `order` is updated too."""
    path = Path(path)
    plugin = Plugin.load(str(path), only_signatures=GROUPS)
    plugin.plugin_set = plugins
    names = plugins.load_order.plugins
    for i in reversed(range(len(names))):
        if names[i].lower() == path.name.lower():
            plugins._plugins.pop(names[i], None)
            del names[i]
    order[:] = [n for n in order if n.lower() != path.name.lower()] + [path.name]
    names.append(path.name)
    plugins._plugins[path.name] = plugin
    plugins._loaded_full[path.name] = True
    plugins.invalidate()
    return plugin


def winning_records(plugins: PluginSet, sig: str, order: List[str] = None):
    """Yield all winning-override records of a given signature, deduplicated.
    order should be the list of plugin names in load order."""
    if order is None:
        order = [plugins.load_order[i] for i in range(len(plugins.load_order))]
    seen = set()
    for name in order:
        plugin = plugins.get_plugin(name)
        if plugin is None:
            continue
        for rec in plugin.get_records_by_signature(sig):
            resolved = plugins.resolve_form_id(rec.form_id, plugin)
            if resolved is None:
                continue
            rid = id(resolved)
            if rid in seen:
                continue
            seen.add(rid)
            yield resolved


def find_race(plugins: PluginSet, edid: str, order: List[str] = None):
    """Find a RACE record by EditorID."""
    for rec in winning_records(plugins, 'RACE', order):
        if rec.editor_id == edid:
            return rec
    # Try get_record_by_edid as fallback
    return plugins.get_record_by_edid(edid)


def npc_sex(npc) -> str:
    """'MALE' or 'FEMALE' from the ACBS subrecord bit 0."""
    acbs = npc.get_subrecord('ACBS')
    if acbs is None:
        return 'MALE'
    return 'FEMALE' if (acbs.get_uint32() & 1) else 'MALE'


def enumerate_human_npcs(plugins: PluginSet, order: List[str] = None, verbose: bool = False):
    """Yield (npc_record, race_edid) for all HumanRace and HumanCrowdRace NPCs."""
    human = find_race(plugins, 'HumanRace', order)
    crowd = find_race(plugins, 'HumanCrowdRace', order)

    target_races = {}
    if human:
        target_races[id(human)] = 'HumanRace'
    if crowd:
        target_races[id(crowd)] = 'HumanCrowdRace'

    count = 0
    for npc in winning_records(plugins, 'NPC_', order):
        race = plugins.resolve_reference(npc, 'RNAM')
        if race is None:
            continue
        race_edid = target_races.get(id(race))
        if race_edid:
            count += 1
            yield npc, race_edid

    if verbose:
        print(f'  Found {count} human/crowd NPCs')
