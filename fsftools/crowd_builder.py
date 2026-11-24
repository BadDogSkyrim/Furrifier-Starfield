"""Crowd NPCs: make the crowd outfits pick furry heads at the scheme's proportions.

A crowd actor's head, hands and tail are an armor in its outfit, so crowds change in one place. Every
outfit holding a crowd head list and hair list keeps its clothes, and those two lists are replaced by
one list that picks a race:

    Outfit_Crowds_Akila_Male (override)
      LL_Crowd_Clothes_Akila                               unchanged
      FSF_LL_Crowd_Mix_Heads_Hairs_Hats_Akila              pick one, entries in the scheme's ratio
        FSF_LL_Crowd_Heads_FSFFoxRace                      pick one, entries in the breeds' ratio
          FSF_LL_Crowd_Heads_FSFFoxRace_red_fox            the breed's head armors
        FSF_LL_Crowd_Human_Heads_Hairs_Hats_Akila          Use All: vanilla's head list and hair list

Crowd actors, their race and the crowd regions aren't touched. The pick happens per spawn, so every
population gets the configured share, however few actors it lists.

A head armor holds a head addon, a tail addon and any beard addon. A head addon names a male and a
female model, as vanilla's do, so the sexes share lists; each is paired with a variant of the other
sex in the same breed, whatever its tone, since an actor only ever shows its own sex's. The tail addon
likewise has each sex's tail in that sex's tone. Everything is on HumanCrowdRace. The textures and nifs come
from sf_tintbake's manifests, one per sex, named in the race's TOML.

With --keep-hair, furry heads wear the outfit's hair list too. When the crowd hair was fitted
(crowd_hair.fit, sf_furrify --hair), each breed wears its own copy of that list, of copies of the hair
and hat armors whose addons name the nifs fitted to the breed's heads:

        FSF_LL_Crowd_FSFFoxRace_Heads_Hairs_Hats_Akila      pick one, entries in the breeds' ratio
          FSF_LL_Crowd_FSFFoxRace_red_fox_Heads_Hairs_Hats_Akila    Use All:
            FSF_LL_Crowd_Heads_FSFFoxRace_red_fox                     the breed's heads
            FSF_LL_Crowd_Hairs_Hats_Akila_<heads>                     its fitted hair list
"""
import fnmatch
import json
import math
import os
import shutil
import struct
from dataclasses import dataclass, field
from functools import reduce
from pathlib import Path
from typing import Dict, List, Optional

from esplib.record import SubRecord, _make_flags
from esplib.utils import FormID

from fsftools.plugin_loader import winning_records

CROWD_RACE = 'HumanCrowdRace'
HUMAN = '_HUMAN'
MAX_ENTRIES = 255                    # a leveled list's entry count is one byte
BODIES = ('average', 'thin', 'overweight')
BODY_EDID = {'average': '', 'thin': '_Thin', 'overweight': '_Overweight'}   # vanilla's EDID style
HEAD_LISTS = {'LL_Crowd_Heads' + suffix: body for body, suffix in BODY_EDID.items()}
HAIR_LIST_PREFIX = 'LL_Crowd_Hairs'
LVLF_USE_ALL = 4
MODEL = {'male': 'MOD2', 'female': 'MOD3'}
MORPH_SIG = {'male': 'NAM4', 'female': 'NAM6'}
HEAD_TEMPLATE = 'FSF_AA_CrowdHead_fox_md1_NOTPLAYABLE'
TAIL_SLOT_BIT = 1 << 15
BEARD_SLOT_BIT = 1 << 9     # Head (Vis Only). The Beard slot, 17, hides the tail on the same armor.
ARMA_IS_SKIN, ARMA_IS_SKIN_HANDS = 0x80, 0x100        # ARMA record-header flags
TEST_ACTORS = {'male': 'CrowdActor_Akila_Male_01', 'female': 'CrowdActor_Akila_Female_01'}
TEST_SUFFIX = {'male': 'M', 'female': 'F'}
RETIRED_PLUGIN = 'FSFNPC_Fox.esm'


class CrowdError(ValueError):
    pass


def z(s: str) -> bytes:
    return s.encode('cp1252') + b'\0'


def u32(v: int) -> bytes:
    return struct.pack('<I', v)


# ---------------------------------------------------------------- the plan: no records yet

def whole_shares(weights: Dict[str, int], what: str) -> Dict[str, int]:
    """Relative weights as the fewest list entries that keep the ratio: 40/60 gives 2 and 3."""
    live = {k: w for k, w in sorted(weights.items()) if w > 0}
    if not live:
        return {}
    divisor = reduce(math.gcd, live.values())
    shares = {k: w // divisor for k, w in live.items()}
    if sum(shares.values()) > MAX_ENTRIES:
        raise CrowdError(f"{what}: {weights} takes {sum(shares.values())} list entries, more than "
                         f"a leveled list's {MAX_ENTRIES}. Use rounder numbers.")
    return shares


def variant_nifs(variant: dict) -> dict:
    """{body type: nif} for a manifest variant."""
    return variant.get('nifs') or {'average': variant['nif']}


@dataclass
class HeadPair:
    """One head armor's worth: a male and a female variant, the same breed."""
    name: str
    male: dict
    female: dict

    @property
    def tail(self):
        """The tail addon it wears: (male tone, female tone)."""
        return self.male['tone'], self.female['tone']


@dataclass
class RacePlan:
    config: object
    manifests: Dict[str, dict]
    breed_shares: Dict[str, int]
    heads: Dict[str, List[HeadPair]]          # by breed
    tail_addon: str
    tail_nifs: Dict[tuple, Dict[str, str]]    # {(male tone, female tone): {sex: nif}}
    beard_colors: Optional[str] = None        # the Simple AVM group every ruff addon names


@dataclass
class CrowdPlan:
    shares: Dict[str, int]
    races: Dict[str, RacePlan] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


def _read_manifests(cfg) -> Dict[str, dict]:
    if not cfg.crowd_manifests:
        raise CrowdError(f"{cfg.editorid}: has a crowd proportion but no crowd_manifests in its TOML")
    found = {}
    for path in cfg.crowd_manifests:
        if not Path(path).exists():
            raise CrowdError(f"{cfg.editorid}: crowd manifest {path} doesn't exist; bake with sf_tintbake")
        with open(path, encoding='utf-8') as f:
            manifest = json.load(f)
        sex = manifest.get('sex', 'male')
        if sex in found:
            raise CrowdError(f"{cfg.editorid}: two {sex} crowd manifests")
        found[sex] = manifest
    missing = [s for s in MODEL if s not in found]
    if missing:
        raise CrowdError(f"{cfg.editorid}: no {' or '.join(missing)} crowd manifest; a head addon "
                         f"names both sexes' models")
    return found


def _pair_breed(cfg, breed, manifests, warnings) -> List[HeadPair]:
    """A breed's heads: those its crowd_heads globs name, in each sex's tones. Every head of either
    sex is used, the sex with fewer repeating."""
    heads = {'male': [], 'female': []}
    for sex, manifest in manifests.items():
        tones = cfg.tones_for(sex, breed)
        for v in manifest['variants']:
            if v['tone'] in tones and any(fnmatch.fnmatch(v['name'].lower(), g.lower()) for g in breed.crowd_heads):
                absent = [b for b in BODIES if b not in variant_nifs(v)]
                if absent:
                    raise CrowdError(f"{v['name']}: no {', '.join(absent)} nif, and crowd outfits need "
                                     f"every body type")
                heads[sex].append(v)
    males, females = [sorted(heads[sex], key=lambda v: (v['tone'], v['name'])) for sex in ('male', 'female')]
    if not males or not females:
        lonely = 'male' if males else 'female'
        if males or females:
            warnings.append(f"{cfg.editorid} {breed.name}: only {lonely} heads; a head armor needs both sexes")
        return []
    pairs = []
    for i in range(max(len(males), len(females))):
        male, female = males[i % len(males)], females[i % len(females)]
        pairs.append(HeadPair(f"{breed.name}_m{male['tone']}f{female['tone']}_{i + 1:02d}", male, female))
    return pairs


def crowd_plan(races, scheme) -> CrowdPlan:
    """What the scheme asks of the crowds. A bad configuration stops here, before any work."""
    shares = whole_shares(scheme.proportions, '[proportions]')
    plan = CrowdPlan(shares)
    for race_edid in shares:
        if race_edid == HUMAN:
            continue
        cfg = races.get(race_edid)
        if cfg is None:
            raise CrowdError(f"[proportions] names {race_edid}, which has no race definition")
        manifests = _read_manifests(cfg)
        breed_shares = whole_shares({b.name: b.weight for b in cfg.breeds}, f"{race_edid} breeds")
        if not breed_shares:
            raise CrowdError(f"{race_edid}: no breed has a weight above 0")
        heads = {}
        for breed in cfg.breeds:
            if breed.name not in breed_shares:
                continue
            if not breed.crowd_heads:
                raise CrowdError(f"{race_edid} breed {breed.name}: weight {breed.weight} but no crowd_heads")
            heads[breed.name] = _pair_breed(cfg, breed, manifests, plan.warnings)
            if not heads[breed.name]:
                raise CrowdError(f"{race_edid} breed {breed.name}: no crowd head in the manifests "
                                 f"matches {breed.crowd_heads} in its tones")
        addons = {m['tail']['addon'] for m in manifests.values() if 'tail' in m}
        if len(addons) != 1:
            raise CrowdError(f"{race_edid}: the crowd manifests name tail addons {sorted(addons)}, not one")
        baked = {sex: {int(tone): nif for tone, nif in manifest['tail'].get('nifs', {}).items()}
                 for sex, manifest in manifests.items()}
        used = sorted({pair.tail for pairs in heads.values() for pair in pairs})
        tail_nifs = {}
        for tones in used:
            tail_nifs[tones] = {}
            for sex, tone in zip(('male', 'female'), tones):
                if tone not in baked[sex]:
                    raise CrowdError(f"{race_edid}: no tail baked for {sex} tone {tone}")
                tail_nifs[tones][sex] = baked[sex][tone]
        plan.races[race_edid] = RacePlan(cfg, manifests, breed_shares, heads, addons.pop(), tail_nifs,
                                         _beard_colors(race_edid, manifests))
    return plan


def _beard_colors(race_edid, manifests) -> Optional[str]:
    """The colour list the race's ruffs name. One ruff addon carries both sexes' ruffs, so the
    manifests that have beards must name the same list."""
    named = {}
    for sex, manifest in manifests.items():
        if any(v.get('beard') for v in manifest['variants']):
            if not manifest.get('beard_colors'):
                raise CrowdError(f"{race_edid}: the {sex} manifest has beards but no beard_colors")
            named[sex] = manifest['beard_colors']
    if len(set(named.values())) > 1:
        raise CrowdError(f"{race_edid}: the manifests' beards name different colour lists, "
                         f"{', '.join(f'{s} {c}' for s, c in sorted(named.items()))}; one ruff addon "
                         f"carries both sexes, so give both recipes' [beards] the same colors")
    return next(iter(named.values()), None)


def crowd_outfits(plugins, order) -> list:
    """Every winning outfit holding a crowd head list: [(outfit, head list, hair list)]."""
    found = []
    for outfit in winning_records(plugins, 'OTFT', order):
        items = [plugins.resolve_form_id(sr.get_form_id(i), outfit.plugin)
                 for sr in outfit.get_subrecords('INAM') for i in range(0, sr.size, 4)]
        lists = [r for r in items if r is not None and r.signature == 'LVLI']
        heads = [r for r in lists if r.editor_id in HEAD_LISTS]
        hairs = [r for r in lists if (r.editor_id or '').startswith(HAIR_LIST_PREFIX)]
        if not heads:
            continue
        if len(heads) != 1 or len(hairs) != 1:
            raise CrowdError(f"{outfit.editor_id}: expected one crowd head list and one hair list, found "
                             f"{[r.editor_id for r in heads + hairs]}")
        found.append((outfit, heads[0], hairs[0]))
    return found


# ---------------------------------------------------------------- the records

class CrowdBuilder:
    def __init__(self, out, plugins, order, masters, data_dir, plan: CrowdPlan, keep_hair=False,
                 crowd_hair=None):
        self.out, self.plugins, self.order, self.masters = out, plugins, order, masters
        self.keep_hair = keep_hair
        self.crowd_hair = crowd_hair if keep_hair else None
        self.breed_lists = {}        # race -> body type -> breed -> the breed's head list
        self.fitted = {}             # (kind, heads, EditorID) -> a fitted hair record
        self.data_dir, self.plan = Path(data_dir), plan
        self.vanilla = plugins.get_plugin(masters[0])
        self.crowd_race = self.vanilla.get_record_by_editor_id(CROWD_RACE)
        if self.crowd_race is None:
            raise CrowdError(f"{CROWD_RACE} isn't in {masters[0]}")
        self.notes: List[str] = []
        self.beards = {}             # beard nif, lowered -> ARMA
        self.counts = {}
        self._morphs_checked = set()

    # -- small parts

    def _count(self, kind, n=1):
        self.counts[kind] = self.counts.get(kind, 0) + n

    def _local_ref(self, rec) -> int:
        """A record of this plugin as a reference is written: esplib only finalizes the record's own
        formID at save, not raw reference bytes."""
        return (len(self.masters) << 24) | (int(rec.form_id.value) & 0xFFFFFF)

    def _new_copy(self, source, new_edid, name=None):
        """A new record from a source record. A vanilla FULL is a string-table ID, meaningless here."""
        rec = source.copy()
        rec.form_id = FormID(0)      # add_record assigns a fresh local one
        rec.get_subrecord('EDID').data = z(new_edid)
        for sr in rec.get_subrecords('FULL') + rec.get_subrecords('SHRT'):
            sr.data = z(name or new_edid)
        self.out.add_record(rec)
        return rec

    def _vanilla_record(self, edid):
        rec = self.vanilla.get_record_by_editor_id(edid)
        if rec is None:
            raise CrowdError(f"{edid} isn't in {self.masters[0]}")
        return rec

    @staticmethod
    def _set(rec, sig, data):
        subs = rec.get_subrecords(sig)
        if len(subs) != 1:
            raise CrowdError(f"{rec.editor_id}: {len(subs)} {sig}, expected 1")
        subs[0].data = data

    @staticmethod
    def _drop(rec, sig):
        """Without esplib's remove_subrecords, which would re-sort the record on save."""
        rec.subrecords[:] = [s for s in rec.subrecords if s.signature != sig]

    def _new_list(self, edid, refs, use_all=False):
        """A leveled list copied from vanilla's: level 1, count 1 each. Past 255 it holds sub-lists."""
        source = self._vanilla_record('LL_Crowd_Heads')
        if len(refs) > MAX_ENTRIES:
            parts = [self._new_list(f'{edid}_{i // MAX_ENTRIES + 1}', refs[i:i + MAX_ENTRIES])
                     for i in range(0, len(refs), MAX_ENTRIES)]
            refs = [self._local_ref(p) for p in parts]
        rec = self._new_copy(source, edid)
        subs = [s for s in rec.subrecords if s.signature != 'LVLO']
        at = next(i for i, s in enumerate(subs) if s.signature == 'LLCT') + 1
        subs[at - 1].data = bytes([len(refs)])
        subs[at:at] = [SubRecord('LVLO', u32(1) + u32(ref) + u32(1)) for ref in refs]
        rec.subrecords[:] = subs
        if use_all:
            flags = bytearray(rec.get_subrecord('LVLF').data)
            flags[0] |= LVLF_USE_ALL
            rec.get_subrecord('LVLF').data = bytes(flags)
        self._count('LVLI')
        return rec

    # -- addons and armors

    def _head_name(self, nif):
        import sf_tintbake
        return sf_tintbake.split_body(os.path.splitext(os.path.basename(nif))[0])[0].lower()

    def _source_addon(self, plugin, nif, sex, need_morph=False):
        """The race plugin's addon whose model for `sex` is this head or beard, any body type."""
        for arma in plugin.get_records_by_signature('ARMA'):
            model = arma.get_subrecord(MODEL[sex])
            if model is None or self._head_name(model.get_string()) != self._head_name(nif):
                continue
            if need_morph and arma.get_subrecord(MORPH_SIG[sex]) is None:
                continue
            return arma
        return None

    def _check_morph(self, plugin, addon, sex, nif, who):
        """Note anything that would stop `addon`'s morph moving `nif`. Reported, not fatal."""
        link = addon.get_subrecord(MORPH_SIG[sex])
        if link is None:
            self.notes.append(f"{who}: {addon.editor_id} has no {MORPH_SIG[sex]} morph; it won't animate")
            return
        target = int.from_bytes(bytes(link.data), 'little')
        key = (target, self._head_name(nif))
        if key in self._morphs_checked:
            return
        self._morphs_checked.add(key)
        mrph = next((m for m in plugin.get_records_by_signature('MRPH') if int(m.form_id.value) == target), None)
        if mrph is None:
            self.notes.append(f"{who}: {addon.editor_id}'s {MORPH_SIG[sex]} isn't an MRPH in {plugin.file_path.name}")
            return
        tmpp = mrph.get_subrecord('TMPP')
        if tmpp is None:
            self.notes.append(f"{mrph.editor_id}: no TMPP (performance path)")
            return
        folder = tmpp.get_string()
        dat = self.data_dir / folder.replace('/', '\\') / 'morph.dat'
        if not dat.exists():
            self.notes.append(f"{mrph.editor_id}: no morph.dat in {folder}")
            return
        import sf_racecheck
        from pyn.pynifly import NifFile
        from pyn.sf_morph import MorphFile
        path = self.data_dir / 'Meshes' / nif
        if not path.exists():
            self.notes.append(f"{who}: {nif} isn't under Data\\Meshes yet (deploy it)")
            return
        mesh = sf_racecheck.resolve_mesh([str(self.data_dir)], NifFile(str(path)).shapes[0].mesh_paths()[0])
        if mesh and os.path.exists(mesh):
            morph_verts, mesh_verts = MorphFile.from_file(str(dat)).num_vertices, sf_racecheck.mesh_vertex_count(mesh)
            if morph_verts != mesh_verts:
                self.notes.append(f"{mrph.editor_id} ({folder}) has {morph_verts} vertices but {nif} has "
                                  f"{mesh_verts}; the game won't apply it")

    def _base_addon(self, plugin, head, sex):
        found = self._source_addon(plugin, head, sex)
        if found is None:
            self.notes.append(f"no {plugin.file_path.name} addon has {head} as its {sex} model; "
                              f"using {HEAD_TEMPLATE}")
            found = plugin.get_record_by_editor_id(HEAD_TEMPLATE)
            if found is None:
                raise CrowdError(f"{HEAD_TEMPLATE} isn't in {plugin.file_path.name}")
        return found

    def _head_addon(self, plugin, pair, body, edid):
        """The race plugin's addon for the male head, with both sexes' models and morphs."""
        male = self._base_addon(plugin, pair.male['head'], 'male')
        female = self._base_addon(plugin, pair.female['head'], 'female')
        self._check_morph(plugin, male, 'male', variant_nifs(pair.male)[body], pair.male['head'])
        self._check_morph(plugin, female, 'female', variant_nifs(pair.female)[body], pair.female['head'])
        arma = self._new_copy(male, 'FSF_AA_' + edid)
        self._set(arma, 'MOD2', z(variant_nifs(pair.male)[body]))
        self._set(arma, 'MOD3', z(variant_nifs(pair.female)[body]))
        link = female.get_subrecord('NAM6')
        if link is not None:
            self._set(arma, 'NAM6', bytes(link.data))
        self._on_crowd_race(arma)
        self._count('ARMA')
        return arma

    def _on_crowd_race(self, arma):
        """The addon's race is the crowd race, and it needs no other."""
        self._set(arma, 'RNAM', u32(int(self.crowd_race.form_id.value)))
        self._drop(arma, 'MODL')

    def _tail_addon(self, plugin, race_edid, addon, tones, by_sex):
        """A copy of the player race's tail with each sex's tail in that sex's tone. Crowds have no skin
        tones, so a tail matching its head comes on the head armor. Not Is Skin: its colour is in its
        material."""
        source = plugin.get_record_by_editor_id(addon)
        if source is None:
            raise CrowdError(f"tail addon {addon} isn't in {plugin.file_path.name}")
        tail = self._new_copy(source, f'FSF_AA_CrowdTail_{race_edid}_m{tones[0]}f{tones[1]}')
        for sex, nif in by_sex.items():
            self._set(tail, MODEL[sex], z(nif))
        self._on_crowd_race(tail)
        tail.flags = _make_flags('ARMA', int(tail.flags) & ~(ARMA_IS_SKIN | ARMA_IS_SKIN_HANDS))
        self._count('ARMA')
        return tail

    def _beard_addon(self, plugin, nifs, colors):
        """Vanilla's crowd hair addon with each sex's ruff as that sex's model, in the beard slot,
        naming the race's colour group. `nifs` is {sex: nif}, for the sexes whose head has a ruff.

        A sex with no ruff gets an empty model rather than none, because removing MOD2 or MOD3 leaves
        its FLLDs out of step and xEdit misparses the rest. Each ruff takes its morph from the race
        plugin's addon that has it as that sex's model, so it follows the face."""
        key = tuple((sex, nifs[sex].lower()) for sex in MODEL if sex in nifs)
        if key in self.beards:
            return self.beards[key]
        name = '_'.join(os.path.splitext(os.path.basename(nifs[sex]))[0] for sex in MODEL if sex in nifs)
        arma = self._new_copy(self._vanilla_record('AA_CrowdHair_Business_NOTPLAYABLE'), 'FSF_AA_CrowdBeard_' + name)
        self._set(arma, 'BO64', struct.pack('<Q', BEARD_SLOT_BIT))
        if arma.get_subrecord('MNAM').get_uint32() != 1:
            raise CrowdError('AA_CrowdHair_Business_NOTPLAYABLE is no longer a Simple AVM addon')
        self._set(arma, 'TNAM', z(colors))
        morphs = []
        for sex, sig in MODEL.items():
            nif = nifs.get(sex)
            self._set(arma, sig, z(nif) if nif else b'\0')
            if not nif:
                continue
            who = self._head_name(nif)
            source = self._source_addon(plugin, nif, sex, need_morph=True)
            if source is None:
                self.notes.append(f"{who}: no addon with it as the {sex} model and a {MORPH_SIG[sex]} "
                                  f"morph; it won't follow the face")
                continue
            self._check_morph(plugin, source, sex, nif, who)
            morphs.append(SubRecord(MORPH_SIG[sex], bytes(source.get_subrecord(MORPH_SIG[sex]).data)))
        at = arma.subrecords.index(arma.get_subrecord('MNAM'))
        arma.subrecords[at:at] = morphs                 # NAM4 then NAM6, before MNAM, as vanilla orders them
        self.beards[key] = arma
        self._count('ARMA')
        return arma

    def _head_armor(self, plugin, pair, body, race_edid, tails, colors):
        edid = f"CrowdHead_{race_edid}_{pair.name}{BODY_EDID[body]}"
        addons = [self._head_addon(plugin, pair, body, edid + '_NOTPLAYABLE'), tails[pair.tail]]
        slots = TAIL_SLOT_BIT
        ruffs = {sex: head['beard_nifs'][body] for sex, head in (('male', pair.male), ('female', pair.female))
                 if head.get('beard')}
        if ruffs:
            addons.append(self._beard_addon(plugin, ruffs, colors))
            slots |= BEARD_SLOT_BIT
        armor = self._new_copy(self._vanilla_record('CrowdHead_af_md1_NOTPLAYABLE'), f'FSF_{edid}_NOTPLAYABLE')
        self._set(armor, 'MODL', u32(self._local_ref(addons[0])))
        at = armor.subrecords.index(armor.get_subrecord('MODL')) + 1
        for addon in addons[1:]:
            armor.subrecords[at:at] = [SubRecord('INDX', b'\0\0'), SubRecord('MODL', u32(self._local_ref(addon)))]
            at += 2
        worn = struct.unpack('<Q', bytes(armor.get_subrecord('BO64').data))[0]
        self._set(armor, 'BO64', struct.pack('<Q', worn | slots))
        self._count('ARMO')
        return armor

    # -- whole lists

    def _race_head_lists(self, race_edid, plan: RacePlan) -> Dict[str, object]:
        """{body type: the race's head list}: a pick-one over breed lists, in the breeds' ratio."""
        plugin = self.plugins.get_plugin(plan.config.plugin)
        if self.masters.index(plan.config.plugin) != 1 or list(plugin.header.masters) != [self.masters[0]]:
            raise CrowdError(f"{plan.config.plugin} must be the output's second master and master only "
                             f"{self.masters[0]}: copies of its addons keep their FormIDs")
        tails = {tones: self._tail_addon(plugin, race_edid, plan.tail_addon, tones, by_sex)
                 for tones, by_sex in plan.tail_nifs.items()}
        colors = plan.beard_colors
        lists = {}
        for body in BODIES:
            entries = []
            for breed, share in plan.breed_shares.items():
                armors = [self._head_armor(plugin, pair, body, race_edid, tails, colors)
                          for pair in plan.heads[breed]]
                breed_list = self._new_list(f'FSF_LL_Crowd_Heads_{race_edid}_{breed}{BODY_EDID[body]}',
                                            [self._local_ref(a) for a in armors])
                self.breed_lists.setdefault(race_edid, {}).setdefault(body, {})[breed] = breed_list
                entries += [self._local_ref(breed_list)] * share
            lists[body] = self._new_list(f'FSF_LL_Crowd_Heads_{race_edid}{BODY_EDID[body]}', entries)
        return lists

    def _override_outfit(self, outfit, head_ref, hair_ref, mix_ref):
        """The outfit with its head and hair lists replaced by the mix, its other items untouched."""
        copy = outfit.copy()
        inam = copy.get_subrecords('INAM')
        if len(inam) != 1:
            raise CrowdError(f"{outfit.editor_id}: {len(inam)} INAM, expected 1")
        data = bytes(inam[0].data)
        items = list(struct.unpack(f'<{len(data) // 4}I', data))
        at = min(items.index(head_ref), items.index(hair_ref))
        kept = [x for x in items if x not in (head_ref, hair_ref)]
        kept.insert(at, mix_ref)
        inam[0].data = struct.pack(f'<{len(kept)}I', *kept)
        self.out.add_record(copy)
        self._count('OTFT overrides')

    def build(self, test_npcs=False) -> list:
        """Add every crowd record to the plugin. Returns the test NPCs, [] unless asked for."""
        if not self.plan.races:
            return []
        # Test NPCs go first, so the male average one is always object 0x800.
        npcs = self._test_npcs() if test_npcs else {}
        race_lists = {race: self._race_head_lists(race, plan) for race, plan in self.plan.races.items()}
        mixes = {}
        for outfit, head, hair in crowd_outfits(self.plugins, self.order):
            if Path(outfit.plugin.file_path).name.lower() != self.masters[0].lower():
                self.notes.append(f"{outfit.editor_id}: winning override is in {outfit.plugin.file_path.name}; "
                                  f"FormID remapping isn't built yet, so it stays human")
                continue
            head_ref = int(head.form_id.value)
            hair_ref = int(hair.form_id.value)
            key = (head.editor_id, hair.editor_id)
            if key not in mixes:
                mixes[key] = self._mix_list(head, hair, head_ref, hair_ref, race_lists)
            self._override_outfit(outfit, head_ref, hair_ref, self._local_ref(mixes[key]))
        if npcs:
            self._dress_test_npcs(npcs, race_lists[next(iter(race_lists))])
        return list(npcs.values())

    def _mix_list(self, head, hair, head_ref, hair_ref, race_lists):
        name = f"{head.editor_id[len('LL_Crowd_'):]}_{hair.editor_id[len('LL_Crowd_'):]}"
        body = HEAD_LISTS[head.editor_id]
        entries = []
        for race, share in self.plan.shares.items():
            if race == HUMAN:
                human = self._new_list(f'FSF_LL_Crowd_Human_{name}', [head_ref, hair_ref], use_all=True)
                entries += [self._local_ref(human)] * share
            elif self.crowd_hair is not None:
                # Each breed's heads with its own fitted copy of the outfit's hair list.
                breeds = []
                for breed, breed_share in self.plan.races[race].breed_shares.items():
                    heads = self._local_ref(self.breed_lists[race][body][breed])
                    hairs = self._fitted_hair_list(race, breed, hair, hair_ref)
                    both = self._new_list(f'FSF_LL_Crowd_{race}_{breed}_{name}',
                                          [heads] + ([hairs] if hairs else []), use_all=True)
                    breeds += [self._local_ref(both)] * breed_share
                entries += [self._local_ref(self._new_list(f'FSF_LL_Crowd_{race}_{name}', breeds))] * share
            elif self.keep_hair:
                # The race's head with the outfit's own human hair (--keep-hair).
                both = self._new_list(f'FSF_LL_Crowd_{race}_{name}',
                                      [self._local_ref(race_lists[race][body]), hair_ref], use_all=True)
                entries += [self._local_ref(both)] * share
            else:
                entries += [self._local_ref(race_lists[race][body])] * share
        return self._new_list(f'FSF_LL_Crowd_Mix_{name}', entries)

    # -- fitted crowd hair

    def _vanilla(self, rec) -> bool:
        """Is the record's winning version in the first master? Copies of others would need their
        FormIDs remapped, which isn't built yet."""
        if Path(rec.plugin.file_path).name.lower() == self.masters[0].lower():
            return True
        self.notes.append(f"{rec.editor_id}: winning override is in {rec.plugin.file_path.name}; FormID "
                          f"remapping isn't built yet, so furry crowds wear it unfitted")
        return False

    def _fitted_hair_list(self, race, breed, hair, hair_ref):
        """The breed's copy of a hair list, as a reference: the armors the race takes, as fitted to
        the breed's heads. None if it takes none of them."""
        heads = self.crowd_hair.breeds[(race, breed)]
        key = ('LVLI', heads, hair.editor_id, race)
        if key in self.fitted:
            return self.fitted[key]
        if not self._vanilla(hair):
            self.fitted[key] = hair_ref
            return hair_ref
        takes = set(self.crowd_hair.armors[race])
        refs = []
        for sr in hair.get_subrecords('LVLO'):
            raw = struct.unpack_from('<I', bytes(sr.data), 4)[0]
            armor = self.plugins.resolve_form_id(FormID(raw), hair.plugin)
            if armor is not None and armor.editor_id in takes:
                refs.append(self._local_ref(self._fitted_armor(heads, armor)) if self._vanilla(armor) else raw)
        found = None
        if refs:
            found = self._new_copy(hair, f'FSF_{hair.editor_id}_{race}_{heads[0]}_{heads[1]}')
            subs = [s for s in found.subrecords if s.signature != 'LVLO']
            at = next(i for i, s in enumerate(subs) if s.signature == 'LLCT') + 1
            subs[at - 1].data = bytes([len(refs)])
            subs[at:at] = [SubRecord('LVLO', u32(1) + u32(ref) + u32(1)) for ref in refs]
            found.subrecords[:] = subs
            self._count('LVLI')
            found = self._local_ref(found)
        self.fitted[key] = found
        return found

    def _fitted_armor(self, heads, armor):
        """A hair or hat armor whose addons are the fitted ones."""
        key = ('ARMO', heads, armor.editor_id)
        if key not in self.fitted:
            stem = armor.editor_id.removesuffix('_NOTPLAYABLE')
            copy = self._new_copy(armor, f'FSF_{stem}_{heads[0]}_{heads[1]}_NOTPLAYABLE')
            for sr in copy.get_subrecords('MODL'):
                addon = self.plugins.resolve_form_id(FormID(struct.unpack('<I', bytes(sr.data)[:4])[0]), armor.plugin)
                if addon is not None and self._vanilla(addon):
                    sr.data = u32(self._local_ref(self._fitted_addon(heads, addon)))
            self._count('ARMO')
            self.fitted[key] = copy
        return self.fitted[key]

    def _fitted_addon(self, heads, addon):
        """A copy of the addon naming each sex's nif as fitted to that sex's head."""
        key = ('ARMA', heads, addon.editor_id)
        if key not in self.fitted:
            stem = addon.editor_id.removesuffix('_NOTPLAYABLE')
            copy = self._new_copy(addon, f'FSF_{stem}_{heads[0]}_{heads[1]}_NOTPLAYABLE')
            for (sex, sig), head in zip(MODEL.items(), heads):
                model = copy.get_subrecord(sig)
                if model is None or not model.get_string():
                    continue
                fitted = self.crowd_hair.model(head, model.get_string())
                if fitted is None:
                    self.notes.append(f"{addon.editor_id}: {model.get_string()} wasn't fitted to {head}; "
                                      f"it stays as it is")
                    continue
                self._set(copy, sig, z(fitted))
            self._count('ARMA')
            self.fitted[key] = copy
        return self.fitted[key]

    # -- the test NPCs

    def _test_npcs(self):
        """Akila's crowd actors, one per sex and body type. Still HumanCrowdRace with their own skin,
        as real crowd actors are, so they test what crowds get."""
        npcs = {}
        for sex, actor in TEST_ACTORS.items():
            for body in BODIES:
                npc = self._new_copy(self._vanilla_record(actor),
                                     f'FSF_CrowdTest_{TEST_SUFFIX[sex]}{BODY_EDID[body]}', 'Crowd Test')
                npcs[(sex, body)] = npc
        return npcs

    def _dress_test_npcs(self, npcs, head_lists):
        """Akila's jacket and boots, with the race's heads straight from its list: never human."""
        for (sex, body), npc in npcs.items():
            clothes = self._vanilla_record(f'Clothes_Crowd_Akila_JacketBoots_01{BODY_EDID[body]}_NOTPLAYABLE')
            suffix = BODY_EDID[body] + ('' if sex == 'male' else '_F')
            outfit = self._new_copy(self._vanilla_record(f'Outfit_Crowds_Akila_{sex.capitalize()}'),
                                    f'FSF_Outfit_CrowdTest{suffix}')
            self._set(outfit, 'INAM', u32(int(clothes.form_id.value)) + u32(self._local_ref(head_lists[body])))
            self._set(npc, 'DOFT', u32(self._local_ref(outfit)))


def add_crowd(out, plugins, order, masters, data_dir, plan: CrowdPlan, test_npcs=False, keep_hair=False,
              crowd_hair=None):
    """Add the crowd records to the output plugin. Returns (test NPCs, counts, notes). keep_hair:
    furry heads wear the outfit's own human hair list too, as fitted to each breed when `crowd_hair`
    (a crowd_hair.CrowdHairFit) is given."""
    builder = CrowdBuilder(out, plugins, order, masters, data_dir, plan, keep_hair, crowd_hair)
    npcs = builder.build(test_npcs)
    return npcs, builder.counts, list(dict.fromkeys(builder.notes))


# ---------------------------------------------------------------- files beside the plugin

def crowd_skeleton_paths(plugins, data_dir) -> List[Path]:
    """Where the crowd skeletons (and _facebones) sit in Data: vanilla's crowd race's own paths."""
    vanilla = plugins.get_record_by_edid('RACE', CROWD_RACE)
    if vanilla is None:
        return []
    return [Path(data_dir) / 'Meshes' / (os.path.splitext(s.get_string())[0] + suffix + '.nif')
            for s in vanilla.get_subrecords('ANAM') for suffix in ('', '_facebones')]


def copy_skeleton(plugins, plan: CrowdPlan, data_dir, dest) -> List[Path]:
    """The crowd race's skeleton, tail bones included, over vanilla's crowd skeleton under `dest`.

    Crowd actors stay HumanCrowdRace, whose skeleton has no tail bones. Each race's crowd race names
    the same files, because there's no extended skeleton for crowd races."""
    written = []
    if not plan.races:
        return written
    data_dir, dest = Path(data_dir), Path(dest)
    vanilla = plugins.get_record_by_edid('RACE', CROWD_RACE)
    cfg = next(iter(plan.races.values())).config
    furry = plugins.get_record_by_edid('RACE', cfg.crowd_race_editorid)
    if furry is None:
        raise CrowdError(f"{cfg.editorid}: crowd race {cfg.crowd_race_editorid} isn't in the load order")
    paths = zip([s.get_string() for s in furry.get_subrecords('ANAM')],
                [s.get_string() for s in vanilla.get_subrecords('ANAM')])
    for source, target in paths:
        for suffix in ('', '_facebones'):
            src = data_dir / 'Meshes' / (os.path.splitext(source)[0] + suffix + '.nif')
            dst = dest / 'Meshes' / (os.path.splitext(target)[0] + suffix + '.nif')
            if not src.exists():
                raise CrowdError(f"crowd skeleton {src} doesn't exist")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            written.append(dst)
    return written


def write_test_batch(path, plugin_name, npcs, data_dir, order):
    """A console batch placing the test NPCs by their light form IDs. Returns its lines."""
    names = [n.lower() for n in order]
    lines = []
    for npc in npcs:
        target = npc.editor_id
        if plugin_name.lower() in names:
            slot = 0
            for name in order[:names.index(plugin_name.lower())]:
                file = Path(data_dir) / name
                if file.exists():
                    with open(file, 'rb') as f:
                        slot += bool(struct.unpack_from('<I', f.read(12), 8)[0] & 0x100)   # SF light flag
            target = f'FE{slot:03X}{int(npc.form_id.value) & 0xFFF:03X}'
        lines.append(f'player.placeatme {target} 1')
    with open(path, 'w', newline='\r\n') as f:
        f.write('\n'.join(lines) + '\n')
    return lines
