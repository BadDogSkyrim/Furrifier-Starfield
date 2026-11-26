"""What a furry race really offers, read from its plugins and checked against its TOML.

The TOML chooses among these; it never invents them. Anything it names that the plugins don't
define fails at startup, because the game silently drops an unresolvable tint or morph.
"""
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fsftools.config import RaceConfig

KIND_SIMPLE = 1
KIND_COMPLEX = 2
KIND_MODULATION = 3

# HDPT PNAM part types and DATA flags (sf1 HDPT definition)
PART_FACIAL_HAIR = 4
FLAG_PLAYABLE = 0x01
FLAG_MALE = 0x02
FLAG_FEMALE = 0x04
FLAG_EXTRA_PART = 0x08


def _text(sr) -> str:
    return sr.data.rstrip(b'\0').decode('utf-8', 'replace')


def _add_avmds(index, plugin):
    for rec in plugin.get_records_by_signature('AVMD'):
        tnam, mnam = rec.get_subrecord('TNAM'), rec.get_subrecord('MNAM')
        if tnam is not None and mnam is not None and len(mnam.data) == 4:
            index[(struct.unpack('<I', mnam.data)[0], _text(tnam))] = rec


def avm_index(plugins, order: List[str]) -> Dict[Tuple[int, str], object]:
    """Every AVMD group by (kind, TNAM). Groups resolve by name, and a later plugin wins."""
    index = {}
    for name in order:
        plugin = plugins.get_plugin(name)
        if plugin is not None:
            _add_avmds(index, plugin)
    return index


# The player plugins (FSFPlayer_FOX.esm, FSFPlayer_HYENA.esm...) are alternatives: each holds one
# race's tint groups under the GLOBAL names (Dermaesthetic, ComplexionMask1...), so only one is
# ever active, and a mod manager deploys only that one. Furrifying mustn't depend on which: every
# race's tint plugin leaves the load order, and each race reads its own on top of what's left.

def tint_plugin_path(name: str, data_dir) -> Path:
    """A race's tint plugin: a path, or a file name in the data folder. Missing is an error."""
    p = Path(name)
    if not p.is_absolute():
        p = Path(data_dir) / p
    if not p.is_file():
        raise ValueError(f"tint plugin {name} not found ({p}); give its path if it isn't deployed")
    return p


def without_tint_plugins(order: List[str], tint_plugins) -> List[str]:
    """The load order without any race's tint plugin, whichever of them is active."""
    names = {Path(t).name.lower() for t in tint_plugins if t}
    return [n for n in order if n.lower() not in names]


def race_avm(base: Dict, tint_plugin) -> Dict:
    """`base` (the load order's groups) with a race's tint plugin's groups over it."""
    if tint_plugin is None:
        return base
    index = dict(base)
    _add_avmds(index, tint_plugin)
    return index


def group_entries(rec) -> Dict[str, Tuple[Optional[str], bytes]]:
    """A group's entries as {LNAM: (VNAM texture or None, NNAM colour bytes)}."""
    entries, key = {}, None
    for sr in rec.subrecords:
        if sr.signature == 'LNAM':
            key = _text(sr)
            entries[key] = (None, b'\0\0\0\0')
        elif key is None:
            continue
        elif sr.signature == 'VNAM':
            entries[key] = (_text(sr), entries[key][1])
        elif sr.signature == 'NNAM':
            entries[key] = (entries[key][0], sr.data)
    return entries


def sex_flag(sex: str) -> int:
    return FLAG_FEMALE if sex == 'FEMALE' else FLAG_MALE


def _part_flags(hdpt) -> int:
    data = hdpt.get_subrecord('DATA')
    return data.data[0] if data is not None and data.data else 0


def _part_races(hdpt, plugins) -> set:
    """EditorIDs of the races a head part's RNAM allows: a FormList of races, or one race."""
    rnam = hdpt.get_subrecord('RNAM')
    if rnam is None or len(rnam.data) != 4:
        return set()
    target = plugins.resolve_form_id(rnam.get_form_id(0), hdpt.plugin)
    if target is None:
        return set()
    if target.signature == 'RACE':
        return {target.editor_id}
    races = set()
    for sr in target.get_subrecords('LNAM'):
        rec = plugins.resolve_form_id(sr.get_form_id(0), target.plugin)
        if rec is not None and rec.signature == 'RACE':
            races.add(rec.editor_id)
    return races


@dataclass
class TintOption:
    slot: str
    option: str
    texture: str


class RaceAppearance:
    """Head parts, tints and face tables for one race, validated against its config."""

    def __init__(self, cfg: RaceConfig, plugins, avm, data_dir: Path):
        self.cfg = cfg
        self.avm = avm               # this race's view of the AVMD groups: its tint plugin on top
        self.problems: List[str] = list(cfg.problems)
        self.warnings: List[str] = []
        self.race = plugins.get_record_by_edid('RACE', cfg.editorid)
        if self.race is None:
            raise ValueError(f"race {cfg.editorid} not found; is {cfg.plugin} in the load order?")
        self.base_parts = self._load_base_parts(plugins)
        self.facial_hair = self._load_facial_hair(plugins)
        self.beard_colors = self._load_part_colors(avm)
        self.phenotype_ids, self.regions = self._load_face_table()
        self.morph_keys = {_text(sr) for sr in self.race.get_subrecords('MPGM')}
        self.tints = self._load_tints(avm, Path(data_dir))
        self.colors = self._load_tint_colors(avm)
        self._check_phenotypes()
        self._check_tones(avm)
        self._check_morphs()
        if self.problems:
            raise ValueError(f"{cfg.editorid} config doesn't match its plugins:\n  " + '\n  '.join(self.problems))

    def _load_base_parts(self, plugins):
        """RACE HEAD entries plus the TOML's extra parts (a tongue isn't a RACE HEAD entry)."""
        parts = {'MALE': [], 'FEMALE': []}
        for sr in self.race.get_subrecords('HEAD'):
            hdpt = plugins.resolve_form_id(sr.get_form_id(0), self.race.plugin)
            if hdpt is None:
                self.problems.append(f"RACE HEAD {sr.data.hex()} does not resolve")
                continue
            for sex in parts:
                if _part_flags(hdpt) & sex_flag(sex):
                    parts[sex].append(hdpt)
        for sex, edids in (('MALE', self.cfg.extra_parts_male), ('FEMALE', self.cfg.extra_parts_female)):
            for edid in edids:
                hdpt = plugins.get_record_by_edid('HDPT', edid)
                if hdpt is None:
                    self.problems.append(f"extra part {edid} is not an HDPT")
                else:
                    parts[sex].append(hdpt)
        return parts

    def _load_facial_hair(self, plugins):
        """Playable facial-hair parts per sex, from the race's plugin, that list this race (or its
        crowd race) in their RNAM. Extra parts can't stand alone; a part with no RNAM is for no race."""
        out = {'MALE': [], 'FEMALE': []}
        ours = {self.cfg.editorid, self.cfg.crowd_race_editorid} - {None}
        plugin = plugins.get_plugin(self.cfg.plugin)
        for hdpt in plugin.get_records_by_signature('HDPT'):
            kind = hdpt.get_subrecord('PNAM')
            if kind is None or struct.unpack('<I', kind.data)[0] != PART_FACIAL_HAIR:
                continue
            flags = _part_flags(hdpt)
            if flags & FLAG_EXTRA_PART or not flags & FLAG_PLAYABLE:
                continue
            if not ours & _part_races(hdpt, plugins):
                continue
            for sex in out:
                if flags & sex_flag(sex):
                    out[sex].append(hdpt)
        for parts in out.values():
            parts.sort(key=lambda h: h.editor_id)
        for sex, parts in out.items():
            chance = self.cfg.facial_hair_female if sex == 'FEMALE' else self.cfg.facial_hair_male
            if chance and not parts:
                self.problems.append(f"facial_hair_{sex.lower()} = {chance}, but no {sex.lower()} "
                                     f"facial-hair part in {self.cfg.plugin} lists this race in its RNAM")
        return out

    def _load_part_colors(self, avm):
        """A facial-hair part takes its colour from the group its NAM2 names, by key."""
        out = {}
        for parts in self.facial_hair.values():
            for hdpt in parts:
                nam2 = hdpt.get_subrecord('NAM2')
                if nam2 is None:
                    continue
                group = avm.get((KIND_SIMPLE, _text(nam2)))
                out[hdpt.editor_id] = sorted(group_entries(group)) if group is not None else []
        return out

    def _load_face_table(self):
        """FMRI ids per phenotype name, and the region names. Ids are per sex; names carry the sex."""
        ids, regions = {}, []
        seq = list(self.race.subrecords)
        for i, sr in enumerate(seq):
            if sr.signature == 'FMRI' and i + 1 < len(seq) and seq[i + 1].signature == 'FMRU':
                ids[_text(seq[i + 1])] = struct.unpack('<I', sr.data)[0]
            elif sr.signature == 'MPGN' and _text(sr) not in regions:
                regions.append(_text(sr))
        return ids, regions

    def _load_tints(self, avm, data_dir):
        """Each layer's options with the texture stored on the NPC. The bake reads that path literally."""
        out = {}
        for layer in self.cfg.tint_layers:
            group = avm.get((KIND_SIMPLE, layer.slot))
            if group is None:
                self.problems.append(f"no Simple group for tint slot {layer.slot}")
                continue
            entries = group_entries(group)
            options = []
            for name in layer.options:
                if name not in entries or not entries[name][0]:
                    self.problems.append(f"{layer.slot}: no option {name}; "
                                         f"the group has {sorted(entries)[:8]}")
                    continue
                texture = entries[name][0]
                options.append(TintOption(layer.slot, name, texture))
                if not (data_dir / texture.replace('\\', '/')).exists():
                    self.warnings.append(f"{layer.slot} {name}: {texture} is not loose in Data")
            out[layer.slot] = options
        return out

    def _load_tint_colors(self, avm):
        """{slot: [NNAM bytes]} for slots with a Modulation group: mask layers, which paint its colours.

        The whole group is the pool unless the layer's colors narrow it. Full-colour slots have no
        such group and keep a zero NNAM.
        """
        out = {}
        for layer in self.cfg.tint_layers:
            group = avm.get((KIND_MODULATION, layer.slot))
            entries = group_entries(group) if group is not None else {}
            if entries and not layer.colors:
                out[layer.slot] = [color for _, color in entries.values()]
                continue
            if not layer.colors:
                continue
            for name in layer.colors:
                if name not in entries:
                    self.problems.append(f"{layer.slot}: no colour {name} in its Modulation group")
            out[layer.slot] = [entries[n][1] for n in layer.colors if n in entries]
        return out

    def _check_phenotypes(self):
        for breed in self.cfg.breeds:
            for rows in (breed.phenotypes_male, breed.phenotypes_female):
                for name, _ in rows or []:
                    if name not in self.phenotype_ids:
                        self.problems.append(f"breed {breed.name}: phenotype {name} is not on the race; "
                                             f"it has {sorted(self.phenotype_ids)}")

    def _tone_limits(self, avm) -> Dict[str, Tuple[int, str]]:
        """How many skin tones each sex really has, and which list holds it to that. A tone is an
        index into the body and hands lists, which the race repeats per sex, male first."""
        limits = {}
        for at, sex in enumerate(('MALE', 'FEMALE')):
            counts = []
            for sig in ('BSTT', 'HSTT'):
                names = [_text(sr) for sr in self.race.get_subrecords(sig)]
                if names:
                    name = names[min(at, len(names) - 1)]
                    group = avm.get((KIND_SIMPLE, name))
                    if group is None:
                        self.problems.append(f"{sig} group {name} isn't in the load order")
                    else:
                        counts.append((len(group.get_subrecords('LNAM')), name))
            if counts:
                limits[sex] = min(counts)
        return limits

    def _face_tone_count(self, avm, phenotype) -> Optional[int]:
        """The tones in a phenotype's face list, or None if the race's list doesn't have it."""
        fstt = self.race.get_subrecord('FSTT')
        top = avm.get((KIND_COMPLEX, _text(fstt))) if fstt is not None else None
        child = group_entries(top).get(phenotype) if top is not None else None
        group = avm.get((KIND_SIMPLE, child[0])) if child and child[0] else None
        return len(group.get_subrecords('LNAM')) if group is not None else None

    def _check_tones(self, avm):
        """A tone past the end of a list has no texture, which shows only on that NPC in game."""
        limits = self._tone_limits(avm)

        def check(sex, tones, who, phenotypes=()):
            limit = limits.get(sex)
            faces = [(n, p) for p in phenotypes
                     for n in [self._face_tone_count(avm, p)] if n is not None]
            bounds = ([limit] if limit else []) + faces
            for tone in tones:
                for count, name in bounds:
                    if tone >= count:
                        self.problems.append(f"{who}: {sex} tone {tone}, but {name} has only {count} "
                                             f"(tones count from 0)")
                        break

        for sex in ('MALE', 'FEMALE'):
            check(sex, self.cfg.tones_for(sex), 'race')
            for breed in self.cfg.breeds:
                rows = breed.phenotypes_female if sex == 'FEMALE' else breed.phenotypes_male
                if breed.weight > 0 and rows:
                    check(sex, self.cfg.tones_for(sex, breed), f"breed {breed.name}", [p for p, _ in rows])

    def _check_morphs(self):
        """Every morph key the config can write must be one the race declares."""
        tables = [('morph_defaults', self.cfg.morph_defaults)]
        for breed in self.cfg.breeds:
            tables += [(f"breed {breed.name}", breed.morphs), (f"breed {breed.name} blend", breed.blend)]
        for where, table in tables:
            for phenotype, regions in table.items():
                for region in regions:
                    key = f'{phenotype}_{region}'
                    if key not in self.morph_keys:
                        self.problems.append(f"{where}: {key} is not a morph group on the race")
        for breed in self.cfg.breeds:
            used = {name for rows in (breed.phenotypes_male, breed.phenotypes_female)
                    for name, _ in rows or []}
            for phenotype in used:
                if not self.cfg.morph_defaults.get(phenotype) and not breed.morphs.get(phenotype):
                    self.problems.append(f"breed {breed.name}: phenotype {phenotype} has no morph ranges")
            for phenotype in set(breed.morphs) - used:
                self.problems.append(f"breed {breed.name}: overrides morphs for {phenotype}, "
                                     f"which it doesn't use")
