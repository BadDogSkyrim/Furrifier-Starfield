"""Individual NPC furrification — the per-record transformation logic.

Given an NPC and its assigned race/breed, produces the appearance it should have. The actual
record writes are in plugin_writer.py; this module is pure logic + data.
"""
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from fsftools.config import MorphRange
from fsftools.probability import _stable_hash
from fsftools.race_data import RaceAppearance


@dataclass
class TintEntry:
    slot: str        # TNAM
    option: str      # QNAM
    texture: str     # VNAM — the bake uses this path literally
    color: bytes     # NNAM — zero for full-colour textures
    intensity: int   # INTV


@dataclass
class NpcChange:
    """Everything the plugin writer needs to transform one NPC record."""
    npc_editorid: str
    source: object               # the winning NPC_ record to copy
    sex: str                     # 'MALE' or 'FEMALE'
    new_race_edid: str
    breed_name: Optional[str] = None
    new_ston: int = 0
    head_parts: List[object] = field(default_factory=list)   # HDPT records
    facial_hair_color: Optional[str] = None                  # FHCL key, when a part needs one
    tints: List[TintEntry] = field(default_factory=list)
    phenotype: Optional[str] = None
    phenotype_id: Optional[int] = None    # FMRI id
    face_regions: List[str] = field(default_factory=list)    # FMRG names, all at full weight
    morph_groups: Dict[str, float] = field(default_factory=dict)    # BMPN key -> BMPV
    written: bool = False                # its override made it into the plugin
    kept_hair: List[object] = field(default_factory=list)    # the NPC's own hair parts (--keep-hair)
    unfitted_hair: List[str] = field(default_factory=list)   # kept hairs with no copy fitted to the head


def plan_individual_furrification(npc_rec, appearance: RaceAppearance, breed_name: Optional[str],
                                  skin_tone: int, phenotype: Optional[str], assigner,
                                  keep_hair_from=None) -> NpcChange:
    """keep_hair_from: the plugins, to keep the NPC's own hair part (--keep-hair); None drops it."""
    """Plan the changes for one individual (HumanRace) NPC. Writes nothing."""
    from fsftools.plugin_loader import npc_sex

    edid = npc_rec.editor_id or ''
    sex = npc_sex(npc_rec)
    signature = assigner.appearance_signature_for(edid)

    change = NpcChange(npc_editorid=edid, source=npc_rec, sex=sex,
                       new_race_edid=appearance.cfg.editorid, breed_name=breed_name, new_ston=skin_tone)
    _plan_head_parts(change, appearance, signature)
    if keep_hair_from is not None:
        change.kept_hair = npc_hair_parts(npc_rec, keep_hair_from, race_head_prefix(appearance, sex))
        own = npc_hair_parts(npc_rec, keep_hair_from)
        change.unfitted_hair = [h.editor_id for h, o in zip(change.kept_hair, own)
                                if h is o and h.get_subrecord('MODL') is not None]   # no model: nothing to fit
        change.head_parts += change.kept_hair
    _plan_tints(change, appearance, signature)
    _plan_face(change, appearance, phenotype, signature)
    return change


HDPT_HAIR = 3     # HDPT PNAM part type
HDPT_FACE = 1


def race_head_prefix(appearance, sex: str) -> Optional[str]:
    """The prefix of the race's head for this sex (FSFCanine_Female_Head -> FSFCanine), which
    names the hair fitted to it; None if the race has no face part or it isn't named that way."""
    from fsftools.hair_stage import head_prefix
    for part in appearance.base_parts.get(sex, []):
        kind = part.get_subrecord('PNAM')
        if kind is not None and len(kind.data) == 4 and struct.unpack('<I', bytes(kind.data))[0] == HDPT_FACE:
            try:
                return head_prefix(part)
            except ValueError:
                return None
    return None


def npc_hair_parts(npc_rec, plugins, fitted_prefix: Optional[str] = None) -> List[object]:
    """The NPC's own hair parts (HDPT type 3). Its eyebrows and beard sit on a human face; only
    the hair is kept. With `fitted_prefix` (the race head's, e.g. FSFCanine), a hair is swapped for
    its copy fitted to that head (hair_stage), when the load order has one; a hair without one keeps
    its human shape."""
    from fsftools.hair_stage import fitted_edid
    out = []
    for s in npc_rec.get_subrecords('PNAM'):
        part = plugins.resolve_form_id(s.get_form_id(0), npc_rec.plugin)
        kind = part.get_subrecord('PNAM') if part is not None else None
        if kind is not None and len(kind.data) == 4 and struct.unpack('<I', bytes(kind.data))[0] == HDPT_HAIR:
            if fitted_prefix:
                part = plugins.get_record_by_edid('HDPT', fitted_edid(part.editor_id, fitted_prefix)) or part
            out.append(part)
    return out


def _pick(options, signature: str, salt: str):
    return options[_stable_hash(f'{signature}:{salt}') % len(options)]


def _plan_head_parts(change, appearance, signature):
    """The race's parts for this sex, plus one random facial-hair part if the sex has any and the
    NPC passes the race's facial-hair chance. Every PNAM is rewritten, so a miss drops any beard."""
    change.head_parts = list(appearance.base_parts[change.sex])
    candidates = appearance.facial_hair[change.sex]
    if not candidates:
        return
    chance = appearance.cfg.facial_hair_chance(change.sex)
    if chance < 1.0 and (_stable_hash(f'{signature}:facial_hair_chance') % 1000) / 1000.0 >= chance:
        return
    part = _pick(candidates, signature, 'hair')
    change.head_parts.append(part)
    colors = appearance.beard_colors.get(part.editor_id)
    if colors:
        change.facial_hair_color = _pick(colors, signature, 'hair_color')


def _plan_tints(change, appearance, signature):
    """One entry per configured layer that passes its probability; one layer per slot is all a slot holds."""
    for i, layer in enumerate(appearance.cfg.tint_layers):
        if layer.probability < 1.0:
            if (_stable_hash(f'{signature}:tint_prob:{i}') % 1000) / 1000.0 >= layer.probability:
                continue
        option = _pick(appearance.tints[layer.slot], signature, f'tint:{i}')
        colors = appearance.colors.get(layer.slot)
        color = _pick(colors, signature, f'tint_color:{i}') if colors else b'\0\0\0\0'
        change.tints.append(TintEntry(layer.slot, option.option, option.texture, color, layer.intensity))


def roll_morph(rng: MorphRange, signature: str, key: str) -> Optional[float]:
    """One NPC's value for one key, or None if it misses its chance. Same model as FFO's morphs.

    Each key hashes on its own, so changing one range leaves every other value alone.
    """
    if _stable_hash(f'{signature}:morph_chance:{key}') % 100 >= rng.chance:
        return None
    v = (_stable_hash(f'{signature}:morph_value:{key}') % 1000000) / 1000000.0
    if rng.skew == 'low':
        v = v * v
    elif rng.skew == 'high':
        v = 1 - (1 - v) * (1 - v)
    return round(rng.min + v * (rng.max - rng.min), 3)


def _plan_face(change, appearance, phenotype, signature):
    """The phenotype at full weight in every region, plus its rolled morph groups.

    FMRI stays at 1.0 as on the fox presets; only the vertex morphs vary. A blend adds keys from
    another phenotype of the same sex, scaled so a region's total never passes 1.0. The NPC's own
    phenotype is never scaled.
    """
    if phenotype is None:
        return
    change.phenotype = phenotype
    change.phenotype_id = appearance.phenotype_ids[phenotype]
    change.face_regions = list(appearance.regions)

    cfg = appearance.cfg
    breed = next((b for b in cfg.breeds if b.name == change.breed_name), None)
    ranges = dict(cfg.morph_defaults.get(phenotype, {}))
    if breed is not None:
        ranges.update(breed.morphs.get(phenotype, {}))

    own = {}
    for region, rng in ranges.items():
        value = roll_morph(rng, signature, f'{phenotype}_{region}')
        if value is not None:
            own[region] = value
    change.morph_groups = {f'{phenotype}_{region}': value for region, value in own.items()}

    prefix = 'female_' if change.sex == 'FEMALE' else 'male_'
    blends = {}
    for other, regions in (breed.blend if breed is not None else {}).items():
        if other == phenotype or not other.startswith(prefix):
            continue
        for region, rng in regions.items():
            value = roll_morph(rng, signature, f'{other}_{region}')
            if value is not None:
                blends.setdefault(region, []).append((f'{other}_{region}', value))
    for region, rows in blends.items():
        room = 1.0 - own.get(region, 0.0)
        total = sum(value for _, value in rows)
        scale = room / total if total > room else 1.0
        for key, value in rows:
            scaled = round(value * scale, 3)
            if scaled > 0:
                change.morph_groups[key] = scaled


def _z(sub) -> str:
    return bytes(sub.data).rstrip(b'\0').decode('utf-8', 'replace')


def change_from_npc(npc, plugins) -> NpcChange:
    """The appearance an NPC's record already has, as an NpcChange: what the FaceGen bake needs to
    bake it as it stands (a chargen preset, say). Reads the race, tone, head parts, the Simple tint
    layers, the phenotype and the morph groups, in the layout plugin_writer writes."""
    from fsftools.plugin_loader import npc_sex
    race = plugins.resolve_reference(npc, 'RNAM')
    if race is None:
        raise ValueError(f"{npc.editor_id}: its race doesn't resolve")
    parts = [plugins.resolve_form_id(s.get_form_id(0), npc.plugin) for s in npc.get_subrecords('PNAM')]
    subs = list(npc.subrecords)
    tints, groups, regions = [], {}, []
    for i, s in enumerate(subs):
        if s.signature == 'TNAM' and i + 4 < len(subs) and i > 0 and subs[i - 1].signature == 'MNAM' \
                and [x.signature for x in subs[i + 1:i + 5]] == ['QNAM', 'VNAM', 'NNAM', 'INTV']:
            if struct.unpack('<I', subs[i - 1].data)[0] == 1:          # Simple: VNAM is a texture
                tints.append(TintEntry(_z(s), _z(subs[i + 1]), _z(subs[i + 2]), bytes(subs[i + 3].data),
                                       struct.unpack('<I', subs[i + 4].data)[0]))
        elif s.signature == 'BMPN' and i + 1 < len(subs) and subs[i + 1].signature == 'BMPV':
            groups[_z(s)] = struct.unpack('<f', subs[i + 1].data)[0]
        elif s.signature == 'FMRG':
            regions.append(_z(s))
    fmri = npc.get_subrecord('FMRI')
    phenotype_id = struct.unpack('<I', fmri.data)[0] if fmri is not None else None
    sex = npc_sex(npc)
    # The male and female phenotype tables share their ids: read the one in the NPC's sex's section
    # (after the race's last MNAM or FNAM marker).
    rsubs = list(race.subrecords)
    table, section = {}, None
    for i, s in enumerate(rsubs):
        if s.signature in ('MNAM', 'FNAM'):
            section = 'FEMALE' if s.signature == 'FNAM' else 'MALE'
        elif s.signature == 'FMRI' and section == sex and i + 1 < len(rsubs) and rsubs[i + 1].signature == 'FMRU':
            table[struct.unpack('<I', s.data)[0]] = _z(rsubs[i + 1])
    phenotype = table.get(phenotype_id)
    if phenotype is None and groups:
        phenotype = next(iter(groups)).rsplit('_', 1)[0]
    ston = npc.get_subrecord('STON')
    return NpcChange(npc_editorid=npc.editor_id, source=npc, sex=sex, new_race_edid=race.editor_id,
                     new_ston=ston.data[0] if ston is not None else 0, head_parts=[p for p in parts if p],
                     tints=tints, phenotype=phenotype, phenotype_id=phenotype_id, face_regions=regions,
                     morph_groups=groups)
