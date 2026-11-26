"""Load and validate the furrifier's TOML configuration files."""
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


# ── scheme.toml ─────────────────────────────────────────────────────────────

@dataclass
class SchemeConfig:
    """User-editable probability and assignment settings."""
    proportions: Dict[str, int] = field(default_factory=dict)
    # race_editorid or _HUMAN -> relative weight: crowds, and any class with no row of its own
    class_probabilities: Dict[str, Dict[str, int]] = field(default_factory=dict)
    # class_name -> {race_editorid: weight, ...}
    npc_assignments: Dict[str, str] = field(default_factory=dict)
    # npc_editorid -> race_editorid
    families: Dict[str, List[str]] = field(default_factory=dict)
    # family_name -> [npc_editorid, ...] -- share race+breed, different appearance
    aliases: Dict[str, List[str]] = field(default_factory=dict)
    # alias_name -> [npc_editorid, ...] -- same NPC different contexts, share everything
    exclude_npcs: List[str] = field(default_factory=list)


def load_scheme(path: Path) -> SchemeConfig:
    """Load scheme.toml — user-editable probabilities and assignments."""
    with open(path, 'rb') as f:
        raw = tomllib.load(f)

    cfg = SchemeConfig()

    cfg.proportions = {k: int(v) for k, v in raw.get('proportions', {}).items()}

    # class_probabilities: list of tables -> dict keyed by class name
    for entry in raw.get('class_probabilities', []):
        cls = entry.pop('class')
        cfg.class_probabilities[cls] = {k: int(v) for k, v in entry.items()}

    cfg.npc_assignments = dict(raw.get('npc_assignments', {}))
    cfg.families = {k: list(v) for k, v in raw.get('families', {}).items()}
    cfg.aliases = {k: list(v) for k, v in raw.get('aliases', {}).items()}
    cfg.exclude_npcs = list(raw.get('exclude_npcs', []))

    return cfg


# ── builtin.toml ────────────────────────────────────────────────────────────

@dataclass
class ClassRule:
    """One first-match classification rule."""
    class_name: str
    field: str       # RACE, FACTION, KEYWORD, EDITORID, NAME, LOCATION
    pattern: str     # glob pattern

    VALID_FIELDS = {'RACE', 'FACTION', 'KEYWORD', 'EDITORID', 'NAME', 'LOCATION'}

    def __post_init__(self):
        if self.field not in self.VALID_FIELDS:
            raise ValueError(f"Unknown classification field {self.field!r}; "
                             f"valid: {', '.join(sorted(self.VALID_FIELDS))}")


@dataclass
class BuiltinConfig:
    """Classification rules that ship with the tool."""
    rules: List[ClassRule] = field(default_factory=list)


def load_builtin(path: Path) -> BuiltinConfig:
    """Load builtin.toml — classification rules."""
    with open(path, 'rb') as f:
        raw = tomllib.load(f)

    cfg = BuiltinConfig()
    for entry in raw.get('class_match', []):
        cfg.rules.append(ClassRule(
            class_name=entry['class'],
            field=entry['field'].upper(),
            pattern=entry['pattern'],
        ))
    return cfg


# ── races/*.toml ────────────────────────────────────────────────────────────

@dataclass
class TintLayerDef:
    """A tint layer to apply to furrified NPCs."""
    slot: str                    # AVMD slot name (e.g. "Dermaesthetic")
    probability: float = 1.0    # 0.0-1.0, chance this layer is applied
    options: List[str] = field(default_factory=list)  # keys in the slot's Simple group
    intensity: int = 64         # INTV, 1-128
    colors: List[str] = field(default_factory=list)   # narrows the slot's Modulation group; empty = all


SKEWS = ('even', 'low', 'high')    # as FFO's EVEN, SKEW0, SKEW1


@dataclass
class MorphRange:
    """How one morph key is rolled for an NPC."""
    chance: float = 100     # percent; a miss leaves the key unwritten
    min: float = 0.0
    max: float = 1.0
    skew: str = 'even'


@dataclass
class BreedDef:
    """A breed sub-variant within a race (e.g. red_fox, arctic_fox)."""
    name: str
    weight: int = 50
    skin_tone_override: Optional[List[int]] = None
    skin_tone_override_female: Optional[List[int]] = None    # else skin_tone_override serves both
    # Per-sex phenotype lists: [["male_fox_md1", 50], ["male_fox_md2", 50]]
    phenotypes_male: Optional[List[List]] = None
    phenotypes_female: Optional[List[List]] = None
    # {phenotype: {region: range}}. morphs override the race's defaults region by region; blend adds
    # keys from a phenotype other than the NPC's own.
    morphs: Dict[str, Dict[str, MorphRange]] = field(default_factory=dict)
    blend: Dict[str, Dict[str, MorphRange]] = field(default_factory=dict)
    crowd_heads: List[str] = field(default_factory=list)    # globs on crowd variant names


@dataclass
class RaceConfig:
    """Per-race definition loaded from races/<race>.toml."""
    editorid: str
    plugin: str
    crowd_race_editorid: Optional[str] = None
    crowd_manifests: List[str] = field(default_factory=list)    # sf_tintbake's, one per sex
    tint_plugin: Optional[str] = None    # holds the race's tint groups; read, never a master
    skin_tones: List[int] = field(default_factory=lambda: [0])    # breeds may narrow this
    skin_tones_female: Optional[List[int]] = None                 # else skin_tones serves both
    extra_parts_male: List[str] = field(default_factory=list)     # parts not in RACE HEAD
    extra_parts_female: List[str] = field(default_factory=list)
    # Chance (0-1) an NPC gets a facial-hair part. None means unset: always, if the race has any.
    facial_hair_male: Optional[float] = None
    facial_hair_female: Optional[float] = None
    hair_include: List[str] = field(default_factory=list)   # source hair EditorIDs/globs; empty = all
    hair_exclude: List[str] = field(default_factory=list)
    crowd_hair_include: List[str] = field(default_factory=list)   # crowd hair/hat armor EditorIDs/globs
    crowd_hair_exclude: List[str] = field(default_factory=list)
    tint_layers: List[TintLayerDef] = field(default_factory=list)
    morph_defaults: Dict[str, Dict[str, MorphRange]] = field(default_factory=dict)
    breeds: List[BreedDef] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)    # reported at startup by RaceAppearance

    def tones_for(self, sex: str, breed: Optional['BreedDef'] = None) -> List[int]:
        """The skin tones an NPC of this sex and breed can have. Sex in either case."""
        female = sex.upper() == 'FEMALE'
        if breed is not None:
            if female and breed.skin_tone_override_female is not None:
                return breed.skin_tone_override_female
            if breed.skin_tone_override is not None:
                return breed.skin_tone_override
        if female and self.skin_tones_female is not None:
            return self.skin_tones_female
        return self.skin_tones

    def facial_hair_chance(self, sex: str) -> float:
        """The chance an NPC of this sex gets a facial-hair part. Sex in either case."""
        chance = self.facial_hair_female if sex.upper() == 'FEMALE' else self.facial_hair_male
        return 1.0 if chance is None else chance


def _morph_table(raw, where: str, problems: List[str]) -> Dict[str, Dict[str, MorphRange]]:
    """Read {phenotype: {region: {chance, min, max, skew}}}, noting anything out of bounds."""
    table = {}
    for phenotype, regions in raw.items():
        table[phenotype] = {}
        for region, spec in regions.items():
            who = f"{where} {phenotype}_{region}"
            unknown = set(spec) - {'chance', 'min', 'max', 'skew'}
            if unknown:
                problems.append(f"{who}: unknown setting {sorted(unknown)}")
                continue
            rng = MorphRange(**spec)
            if not 0 <= rng.chance <= 100:
                problems.append(f"{who}: chance {rng.chance} is outside 0-100")
            if not (0 <= rng.min <= 1 and 0 <= rng.max <= 1):
                problems.append(f"{who}: min {rng.min} and max {rng.max} must be within 0-1")
            elif rng.min > rng.max:
                problems.append(f"{who}: min {rng.min} is above max {rng.max}")
            if rng.skew not in SKEWS:
                problems.append(f"{who}: skew {rng.skew} is not one of {SKEWS}")
            table[phenotype][region] = rng
    return table


def _load_one_race(path: Path) -> RaceConfig:
    """Load a single race TOML file."""
    with open(path, 'rb') as f:
        raw = tomllib.load(f)

    r = raw['race']
    cfg = RaceConfig(
        editorid=r['editorid'],
        plugin=r['plugin'],
        crowd_race_editorid=r.get('crowd_race_editorid'),
        # Relative to this TOML, so a mod's data folder works wherever it's deployed.
        crowd_manifests=[str((Path(path).parent / m).resolve()) for m in r.get('crowd_manifests', [])],
        tint_plugin=r.get('tint_plugin'),
        skin_tones=list(r.get('skin_tones', [0])),
        skin_tones_female=r.get('skin_tones_female'),
        extra_parts_male=list(r.get('extra_parts_male', [])),
        extra_parts_female=list(r.get('extra_parts_female', [])),
        facial_hair_male=r.get('facial_hair_male'),
        facial_hair_female=r.get('facial_hair_female'),
        hair_include=list(raw.get('hair', {}).get('include', [])),
        hair_exclude=list(raw.get('hair', {}).get('exclude', [])),
        crowd_hair_include=list(raw.get('hair', {}).get('crowd_include', [])),
        crowd_hair_exclude=list(raw.get('hair', {}).get('crowd_exclude', [])),
    )
    for key in ('facial_hair_male', 'facial_hair_female'):
        chance = r.get(key)
        if chance is not None and (isinstance(chance, bool) or not isinstance(chance, (int, float))
                                   or not 0 <= chance <= 1):
            cfg.problems.append(f"[race] {key} = {chance!r}: must be a number from 0 to 1")
    unknown = set(raw.get('hair', {})) - {'include', 'exclude', 'crowd_include', 'crowd_exclude'}
    if unknown:
        cfg.problems.append(f"[hair]: unknown setting {sorted(unknown)}")

    # Tint layers
    for entry in raw.get('tint_layers', []):
        cfg.tint_layers.append(TintLayerDef(
            slot=entry['slot'],
            probability=entry.get('probability', 1.0),
            options=entry.get('options', []),
            intensity=entry.get('intensity', 64),
            colors=entry.get('colors', []),
        ))

    cfg.morph_defaults = _morph_table(raw.get('morph_defaults', {}), 'morph_defaults', cfg.problems)

    for entry in raw.get('breeds', []):
        breed = BreedDef(
            name=entry['name'],
            weight=entry.get('weight', 50),
            skin_tone_override=entry.get('skin_tone_override'),
            skin_tone_override_female=entry.get('skin_tone_override_female'),
            phenotypes_male=entry.get('phenotypes_male'),
            phenotypes_female=entry.get('phenotypes_female'),
            morphs=_morph_table(entry.get('morphs', {}), f"breed {entry['name']}", cfg.problems),
            blend=_morph_table(entry.get('blend', {}), f"breed {entry['name']} blend", cfg.problems),
            crowd_heads=list(entry.get('crowd_heads', [])),
        )
        cfg.breeds.append(breed)

    return cfg


def load_races(directory) -> Dict[str, RaceConfig]:
    """Load all race definitions from a directory of TOML files.
    Returns {race_editorid: RaceConfig}."""
    directory = Path(directory)
    races = {}
    if not directory.is_dir():
        return races
    for path in sorted(directory.glob('*.toml')):
        cfg = _load_one_race(path)
        races[cfg.editorid] = cfg
    return races
