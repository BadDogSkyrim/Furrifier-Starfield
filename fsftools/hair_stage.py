"""The furrifier's hair stage: fit the source race's hair to each race's head (sf_furrify --hair).

Races sharing a head share the fitted hair: one fit per head and sex, named for the head
(Human_Female_Hair_Bob -> FSFCanine_Female_Hair_Bob), listing the races that want it. A race's TOML
picks its hairs with [hair] include/exclude (EditorID globs; no include means every hair).

A fitted HDPT is a copy of the source one with a new EditorID, model, race list and morphs. Its
morphs have a key for each of the head's keys that moves it (hair_fit.fit_keys). The files go under
the output folder and the records into the hair plugin there, created if missing; a record with the
same EditorID is rewritten in place under its FormID, so a player's saved choice survives a rerun.

Each fitted hair records a digest of what it was made from. A rerun fits only the hairs whose digest
changed; the rest keep their files. Hairs with cloth or extra parts aren't fitted yet.
"""
import fnmatch
import hashlib
import json
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from fsftools import hair_fit
from fsftools.facegen import _load_morphs, _text, find_asset
from fsftools.race_data import FLAG_EXTRA_PART, FLAG_PLAYABLE, sex_flag

PART_FACE = 1
PART_HAIR = 3
HIDE_EAR = 'HideEar'
SEXES = ('MALE', 'FEMALE')
FIRST_ID = 0x800
SOURCE_RACE = 'HumanRace'
HAIR_PLUGIN = 'FSFHair.esm'
FITTER_VERSION = 1            # bump when a change to the fit should refit every hair
# Every subrecord vanilla's hairs carry, plus TNAM. A hair with another (scripts, conditions) is
# skipped: its references wouldn't be remapped.
KNOWN_SUBS = {'EDID', 'FULL', 'MODL', 'FLLD', 'DATA', 'PNAM', 'NAM2', 'NAM3', 'RNAM', 'MNAM', 'HNAM', 'TNAM'}
REFERENCE_SUBS = ('TNAM', 'HNAM')


def _pnam(hdpt) -> Optional[int]:
    sr = hdpt.get_subrecord('PNAM')
    return struct.unpack('<I', sr.data[:4])[0] if sr is not None else None


def _flags(hdpt) -> int:
    sr = hdpt.get_subrecord('DATA')
    return sr.data[0] if sr is not None and sr.data else 0


def race_heads(plugins, race) -> Dict[str, object]:
    """The race's face HDPT for each sex, from its HEAD list."""
    out = {}
    for sr in race.get_subrecords('HEAD'):
        h = plugins.resolve_form_id(sr.get_form_id(0), race.plugin)
        if h is None or _pnam(h) != PART_FACE:
            continue
        for sex in SEXES:
            if _flags(h) & sex_flag(sex):
                out.setdefault(sex, h)
    return out


def _race_ids(plugins, flst) -> set:
    return {int(r.form_id.value) for r in (plugins.resolve_form_id(s.get_form_id(0), flst.plugin)
                                           for s in flst.get_subrecords('LNAM')) if r is not None}


def source_hairs(plugins, race, sex: str) -> List:
    """Playable hair parts the race can wear, for one sex, in EditorID order. Extra parts aren't
    listed: they come with the hair that names them."""
    from fsftools.plugin_loader import winning_records
    out = []
    want = int(race.form_id.value)
    for h in winning_records(plugins, 'HDPT'):
        if _pnam(h) != PART_HAIR:
            continue
        f = _flags(h)
        if not f & FLAG_PLAYABLE or f & FLAG_EXTRA_PART or not f & sex_flag(sex):
            continue
        if h.get_subrecord('MODL') is None:
            continue
        flst = plugins.resolve_reference(h, 'RNAM')
        if flst is None or want not in _race_ids(plugins, flst):
            continue
        out.append(h)
    return sorted(out, key=lambda h: h.editor_id or '')


def head_prefix(head) -> str:
    """The head's EditorID up to its sex: FSFCanine_Female_Head -> FSFCanine."""
    edid = head.editor_id
    for sex in ('_Male', '_Female'):
        i = edid.find(sex)
        if i > 0:
            return edid[:i]
    raise ValueError(f'{edid}: no _Male/_Female in the head EditorID')


def fitted_edid(source_edid: str, prefix: str) -> str:
    """Human_Female_Hair_Bob -> <prefix>_Female_Hair_Bob; a name not starting Human_ gets the prefix."""
    if source_edid.lower().startswith('human_'):
        return prefix + source_edid[len('Human'):]
    return f'{prefix}_{source_edid}'


def head_folder(head) -> str:
    """The folder under Meshes\\Actors the head lives in: Actors\\fsfcanine\\... -> fsfcanine."""
    parts = Path(_text(head.get_subrecord('MODL')).replace('\\', '/')).parts
    if len(parts) < 2 or parts[0].lower() != 'actors':
        raise ValueError(f'{head.editor_id}: model {parts} is not under Actors')
    return parts[1]


def wants(edid: str, include: List[str], exclude: List[str]) -> bool:
    """Does a race's [hair] include/exclude take this hair? Globs, any case; no include = all."""
    e = edid.lower()
    if include and not any(fnmatch.fnmatch(e, g.lower()) for g in include):
        return False
    return not any(fnmatch.fnmatch(e, g.lower()) for g in exclude)


@dataclass
class HeadShape:
    shape: hair_fit.Shape
    head: hair_fit.Head                       # bone space, HideEar applied
    keys: Dict[str, Dict[str, hair_fit.Key]]  # 'chargen'/'performance' -> keys
    morph_dirs: Dict[str, str]                # 'chargen'/'performance' -> TCMP/TMPP folder
    ears: np.ndarray                          # vertices HideEar moves
    digest: str = ''                          # of the files it was read from

    def sources(self, part_bone: np.ndarray, ears_move_hair: bool) -> Dict[bool, hair_fit.Sources]:
        """Sources for ear keys [True] and the rest [False]: no ear vertices, unless the ears move
        the hair, when every key draws on every vertex."""
        if ears_move_hair:
            every = hair_fit.sources(self.head.verts, part_bone)
            return {True: every, False: every}
        no_ears = hair_fit.sources(self.head.verts, part_bone, ~self.ears)
        return {True: no_ears, False: no_ears}


class Assets:
    """Game files, loose in Data first, else in the unpacked vanilla assets."""

    def __init__(self, data_dir: Path, assets: Optional[Path]):
        self.data_dir, self.assets = Path(data_dir), assets

    def find(self, rel) -> Path:
        return find_asset(Path(rel), self.data_dir, self.assets)

    def mesh(self, name: str) -> Path:
        return self.find(Path('Geometries') / (name + '.mesh'))

    def shape(self, model: str) -> hair_fit.Shape:
        return hair_fit.load_shape(self.find(Path('Meshes') / model), self.mesh)


MORPH_SUBS = {'chargen': 'TCMP', 'performance': 'TMPP'}


def _mrph(plugins, hdpt):
    return plugins.resolve_reference(hdpt, 'MNAM') if hdpt.get_subrecord('MNAM') else None


def morph_paths(plugins, assets: Assets, hdpt) -> Dict[str, Path]:
    """The part's morph.dat files by kind, from its MRPH; only those that exist."""
    mrph = _mrph(plugins, hdpt)
    out = {}
    for kind, sig in MORPH_SUBS.items():
        sr = mrph.get_subrecord(sig) if mrph is not None else None
        if sr is not None:
            path = assets.find(Path(_text(sr)) / 'morph.dat')
            if path.exists():
                out[kind] = path
    return out


def load_part_keys(plugins, assets: Assets, hdpt, num_verts: int):
    """A part's morph keys and folders by kind, from its MRPH; empty where it has none."""
    keys, dirs = {k: {} for k in MORPH_SUBS}, {}
    mrph = _mrph(plugins, hdpt)
    for kind, sig in MORPH_SUBS.items():
        sr = mrph.get_subrecord(sig) if mrph is not None else None
        if sr is None:
            continue
        dirs[kind] = _text(sr)
        path = assets.find(Path(dirs[kind]) / 'morph.dat')
        if path.exists():
            keys[kind] = hair_fit.load_keys(path, num_verts)
    return keys, dirs, mrph


def part_files(plugins, assets: Assets, hdpt) -> List[Path]:
    """Every file a part is made of: nif, companion, their meshes, morphs. For digests."""
    nif = assets.find(Path('Meshes') / _text(hdpt.get_subrecord('MODL')))
    files = [nif]
    companion = hair_fit.companion_path(nif)
    if companion is not None:
        files.append(companion)
    files += [assets.mesh(hair_fit.nif_mesh_name(f.read_bytes())) for f in list(files)]
    return files + sorted(morph_paths(plugins, assets, hdpt).values())


def _digest(*parts) -> str:
    h = hashlib.sha1()
    for p in parts:
        if isinstance(p, Path):
            h.update(p.read_bytes() if p.exists() else b'<missing>')
        elif isinstance(p, bytes):
            h.update(p)
        else:
            h.update(str(p).encode('utf-8'))
        h.update(b'\0')
    return h.hexdigest()


def load_head(plugins, assets: Assets, hdpt, log=print) -> HeadShape:
    """A head in C_Head space with its HideEar performance key applied, and its morphs."""
    shape = assets.shape(_text(hdpt.get_subrecord('MODL')))
    keys, dirs, _ = load_part_keys(plugins, assets, hdpt, len(shape.positions))
    missing = [k for k in MORPH_SUBS if k not in dirs]
    if missing:
        raise ValueError(f'{hdpt.editor_id}: no {"/".join(missing)} morphs')
    hide = keys['performance'].get(HIDE_EAR)
    if hide is None:
        log(f'  WARNING: {hdpt.editor_id} has no {HIDE_EAR} key; fitting with the ears out')
        ears = np.zeros(len(shape.positions), bool)
        key = None
    else:
        ears = hide.moved()
        key = _load_morphs(assets.find(Path(dirs['performance']) / 'morph.dat')).get(HIDE_EAR)
    return HeadShape(shape, hair_fit.head_in_bone_space(shape, key), keys, dirs, ears,
                     _digest(*part_files(plugins, assets, hdpt)))


def is_ear_key(name: str) -> bool:
    """A chargen key of the Ears region."""
    return name.endswith('_Ears')


@dataclass
class Fitted:
    """A hair as fitted to a head: its record's new values and, once fitted, its files."""
    source: object             # the source HDPT
    edid: str
    model: str                 # relative to Meshes
    races: List                # the target races that want it
    morphs: Dict[str, str] = field(default_factory=dict)   # kind -> folder, relative to Data
    mobc: bytes = b'\xff\x00\x00\x00'
    files: Dict[Path, bytes] = field(default_factory=dict)
    digest: str = ''
    stats: str = ''


def plan_hair(plugins, hdpt, target: HeadShape, prefix: str, folder: str, sex: str, races) -> Fitted:
    """What a fitted hair is called and where its files go; no fitting yet."""
    model = _text(hdpt.get_subrecord('MODL'))
    name = Path(model.replace('\\', '/')).name
    rel = str(Path('Actors') / folder / 'Hair' / sex.capitalize() / name).replace('/', '\\')
    out = Fitted(hdpt, fitted_edid(hdpt.editor_id, prefix), rel, list(races))
    for kind in MORPH_SUBS:
        out.morphs[kind] = str(Path(target.morph_dirs[kind].replace('\\', '/')).parent
                               / Path(name).stem).replace('/', '\\')
    mrph = _mrph(plugins, hdpt)
    if mrph is not None and mrph.get_subrecord('MOBC') is not None:
        out.mobc = bytes(mrph.get_subrecord('MOBC').data)
    return out


def fit_hair(plugins, assets: Assets, f: Fitted, source: HeadShape, target: HeadShape,
             ears_move_hair: bool = True):
    """Fill in the fitted hair's files: its nif, companion, their meshes and the morphs."""
    model = _text(f.source.get_subrecord('MODL'))
    nif_path = assets.find(Path('Meshes') / model)
    shape = assets.shape(model)
    part = shape.to_bone(shape.positions)
    fit = hair_fit.fit_offsets(source.head, target.head, part, shape.tris)
    rel = Path(f.model.replace('\\', '/'))
    pieces = [(shape, rel)]
    companion = hair_fit.companion_path(nif_path)
    if companion is not None:
        other = hair_fit.load_shape(companion, assets.mesh)
        if len(other.positions) != len(shape.positions) or \
                np.abs(other.positions - shape.positions).max() > hair_fit.EPSILON:
            raise ValueError(f'{companion.name}: its vertices differ from {rel.name}')
        pieces.append((other, rel.with_name(companion.name)))
    for piece, path in pieces:
        nif, mesh_name, mesh = hair_fit.fit_files(piece, fit.offsets)
        f.files[Path('Meshes') / path] = nif
        f.files[Path('Geometries') / (mesh_name + '.mesh')] = mesh
    part_keys, _, _ = load_part_keys(plugins, assets, f.source, len(shape.positions))
    target_src = target.sources(part + fit.offsets, ears_move_hair)
    source_src = source.sources(part, ears_move_hair)
    counts = []
    for kind in MORPH_SUBS:
        keys = hair_fit.fit_keys(target.keys[kind], source.keys[kind], part_keys[kind], target_src,
                                 source_src, target.shape, source.shape, shape, ear_key=is_ear_key)
        f.files[Path(f.morphs[kind].replace('\\', '/')) / 'morph.dat'] = \
            hair_fit.write_keys(keys, len(shape.positions))
        counts.append(f'{len(keys)} {kind}')
    moved = np.linalg.norm(fit.offsets, axis=1)
    f.stats = (f'offset mean {moved.mean() * 1000:.1f} mm, max {moved.max() * 1000:.1f} mm, '
               f'{fit.missed} rays missed; keys {", ".join(counts)}')


def skip_reason(assets: Assets, hdpt) -> Optional[str]:
    unknown = sorted({s.signature for s in hdpt.subrecords} - KNOWN_SUBS)
    if unknown:
        return f'has {", ".join(unknown)}, which isn\'t copied'
    if hdpt.get_subrecord('HNAM') is not None:
        return 'has extra parts (not fitted yet)'
    nif = assets.find(Path('Meshes') / _text(hdpt.get_subrecord('MODL')))
    if not nif.exists():
        return f'{nif.name} not found' + (' in Data or the unpacked assets' if assets.assets else
                                          ' (give --assets for parts in BA2s)')
    if b'BSClothExtraData' in nif.read_bytes():
        return 'has cloth (not fitted yet)'
    return None


# ----- records -----------------------------------------------------------------------------------

def _z(s: str) -> bytes:
    return s.encode('cp1252') + b'\0'


def race_list_edid(prefix: str, races, all_races) -> str:
    """The race list's EditorID: one per head for every race on it, else named for its races."""
    names = sorted(r.editor_id for r in races)
    if names == sorted(r.editor_id for r in all_races):
        return f'{prefix}_HairRaces'
    return f'{prefix}_HairRaces_' + '_'.join(names)


def _open_plugin(path: Path, masters: List[str], author: str):
    """The hair plugin, loaded if it exists, its masters grown to hold `masters`."""
    from esplib import Plugin
    if not path.exists():
        out = Plugin()
        out.file_path = path
        out.header.version = 0.96
        out.header.masters = list(masters)
        out.header.master_sizes = [0] * len(masters)
        out.header.is_esl = True
        out.header.is_esm = True
        out.header.author = author
        return out
    out = Plugin.load(str(path))
    have = list(out.header.masters)
    lowered = [m.lower() for m in have]
    return _grow_masters(out, have + [m for m in masters if m.lower() not in lowered])


def write_records(path: Path, masters: List[str], groups, plugins, strings_for, author: str,
                  prune: List[str] = ()):
    """Create or update the hair plugin. `groups`: (prefix, every race on that head, [Fitted]).
    `prune`: prefixes whose hairs not in `groups` are removed. Returns the plugin's masters."""
    from esplib import Record, SubRecord
    from esplib.utils import FormID
    from fsftools.formid_remap import Remapper
    from fsftools.plugin_writer import _output_form_id, _patch_sf_light_flag

    out = _open_plugin(path, masters, author)
    masters = list(out.header.masters)
    remapper = Remapper(masters, plugins)
    existing = {(r.signature, r.editor_id): r for r in out}
    next_id = max([FIRST_ID, out.header.next_object_id or 0]
                  + [(int(r.form_id.value) & 0xFFFFFF) + 1 for r in out])
    pending = []

    def put(sig: str, edid: str, subs) -> int:
        nonlocal next_id
        rec = existing.get((sig, edid))
        if rec is None:
            rec = Record(sig, FormID(next_id))     # its master index is set once the masters settle
            next_id += 1
            pending.append(rec)
            existing[(sig, edid)] = rec
        rec.subrecords[:] = [SubRecord('EDID', _z(edid))] + subs
        return rec

    used = set()
    refs = []                     # (subrecord, own record): own references, set once masters settle
    for prefix, all_races, fitted in groups:
        lists = {}
        for f in fitted:
            name = race_list_edid(prefix, f.races, all_races)
            if name not in lists:
                lists[name] = put('FLST', name, [SubRecord('LNAM', struct.pack('<I', _output_form_id(r, masters)))
                                                 for r in sorted(f.races, key=lambda r: r.editor_id)])
                used.add(('FLST', name))
            morph = put('MRPH', f'MORPH_{f.edid}',
                        [SubRecord('TMPP', _z(f.morphs['performance'])),
                         SubRecord('TCMP', _z(f.morphs['chargen'])), SubRecord('MOBC', f.mobc)])
            used.update({('MRPH', f'MORPH_{f.edid}'), ('HDPT', f.edid)})
            source = f.source
            localized = bool(source.plugin.is_localized)
            subs = []
            for sr in source.subrecords:
                sig = sr.signature
                if sig in ('EDID', 'MNAM'):
                    continue
                if sig == 'FULL':
                    if localized and len(sr.data) == 4:      # a string ID: our plugin isn't localized
                        text = strings_for(source.plugin).get(struct.unpack('<I', sr.data)[0])
                        subs.append(SubRecord('FULL', _z(text or f.edid)))
                    else:
                        subs.append(SubRecord('FULL', bytes(sr.data)))
                elif sig == 'MODL':
                    subs.append(SubRecord('MODL', _z(f.model)))
                elif sig == 'RNAM':
                    sub = SubRecord('RNAM', b'\0' * 4)
                    refs.append((sub, lists[name]))
                    subs.append(sub)
                elif sig in REFERENCE_SUBS:
                    value = remapper.remap(struct.unpack('<I', sr.data)[0], source.plugin)
                    subs.append(SubRecord(sig, struct.pack('<I', value)))
                else:
                    subs.append(SubRecord(sig, bytes(sr.data)))
            sub = SubRecord('MNAM', b'\0' * 4)
            refs.append((sub, morph))
            subs.append(sub)
            put('HDPT', f.edid, subs)
    # The remapper adds masters for hairs from other plugins; our records follow.
    _grow_masters(out, masters)
    own = len(masters) << 24
    for rec in pending:
        rec.form_id = FormID(own | int(rec.form_id.value))
        out.add_record(rec)
    for sub, target in refs:
        sub.data = struct.pack('<I', int(target.form_id.value))
    for prefix in prune:
        for rec in list(out):
            if (rec.signature, rec.editor_id) in used:
                continue
            e = rec.editor_id or ''
            if (rec.signature == 'HDPT' and e.startswith(prefix + '_')) or \
                    (rec.signature == 'MRPH' and e.startswith(f'MORPH_{prefix}_')) or \
                    (rec.signature == 'FLST' and e.startswith(f'{prefix}_HairRaces')):
                out.remove_record(rec)
    out.header.next_object_id = next_id
    from fsftools import safe_write
    path.parent.mkdir(parents=True, exist_ok=True)
    with safe_write.replacing(path) as scratch:
        out.save(str(scratch))
        _patch_sf_light_flag(scratch)
    return list(out.header.masters)


def _grow_masters(out, masters: List[str]):
    """The plugin with its master list grown to `masters` (new names appended). Its own records'
    FormIDs, and references to them, follow the master count; their object IDs, which name them in
    the game (it's a light plugin), stay."""
    from esplib.utils import FormID
    have = list(out.header.masters)
    if [m.lower() for m in masters[:len(have)]] != [m.lower() for m in have]:
        raise ValueError(f'masters {masters} would reorder {have}')
    if len(masters) == len(have):
        return out
    old, new = len(have) << 24, len(masters) << 24
    for rec in out:
        value = int(rec.form_id.value)
        if value & 0xFF000000 == old:
            rec.form_id = FormID(new | (value & 0xFFFFFF))
        for sr in rec.subrecords:
            if sr.signature in ('RNAM', 'MNAM', 'LNAM', 'HNAM') and len(sr.data) == 4:
                ref = struct.unpack('<I', sr.data)[0]
                if ref & 0xFF000000 == old:
                    sr.data = struct.pack('<I', new | (ref & 0xFFFFFF))
    out.header.masters = list(masters)
    out.header.master_sizes = [0] * len(masters)
    return out


# ----- the stage ---------------------------------------------------------------------------------

def _manifest_path(out_dir: Path, plugin_name: str) -> Path:
    return Path(out_dir) / 'FSFTools' / 'hair_fit' / (Path(plugin_name).stem + '.json')


def run(plugins, data_dir: Path, races, out_dir: Path, plugin_name: str = HAIR_PLUGIN,
        assets: Optional[Path] = None, ears_move_hair: bool = True, dry_run: bool = False,
        strings_for=None, log=print) -> Optional[Path]:
    """Fit hair for the races (RaceConfigs) into out_dir and write the hair plugin there.
    Returns the plugin's path, or None if no race takes any hair (or on a dry run)."""
    from fsftools.progress import Progress
    out_dir = Path(out_dir)
    files = Assets(data_dir, assets)
    source_race = plugins.get_record_by_edid('RACE', SOURCE_RACE)
    if source_race is None:
        raise ValueError(f'{SOURCE_RACE} not in the load order')
    source_heads = race_heads(plugins, source_race)

    groups: Dict = {}
    for cfg in races:
        race = plugins.get_record_by_edid('RACE', cfg.editorid)
        if race is None:
            raise ValueError(f'race {cfg.editorid} not in the load order')
        for sex, head in race_heads(plugins, race).items():
            groups.setdefault((head_prefix(head), sex), (head, []))[1].append((race, cfg))

    manifest_path = _manifest_path(out_dir, plugin_name)
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        manifest = {}
    plugin_path = out_dir / plugin_name
    fresh = {}
    by_prefix: Dict[str, list] = {}
    skipped, refit, kept = [], 0, 0
    for (prefix, sex), (head, members) in sorted(groups.items()):
        all_races = [r for r, _ in members]
        candidates = []
        for hdpt in source_hairs(plugins, source_race, sex):
            takers = [r for r, cfg in members if wants(hdpt.editor_id, cfg.hair_include, cfg.hair_exclude)]
            if not takers:
                continue
            why = skip_reason(files, hdpt)
            if why:
                skipped.append((hdpt.editor_id, why))
                continue
            candidates.append((hdpt, takers))
        log(f'  {prefix} {sex}: {len(candidates)} hairs for '
            f'{", ".join(r.editor_id for r in all_races)}')
        if not candidates:
            by_prefix.setdefault(prefix, [all_races, []])
            continue
        source = load_head(plugins, files, source_heads[sex], log)
        target = load_head(plugins, files, head, log)
        fitted = []
        with Progress(f'Fitting {prefix} {sex} hair', len(candidates)) as bar:
            for hdpt, takers in candidates:
                f = plan_hair(plugins, hdpt, target, prefix, head_folder(head), sex, takers)
                f.digest = _digest(FITTER_VERSION, ears_move_hair, source.digest, target.digest, f.model,
                                   *[f'{s.signature}:{bytes(s.data).hex()}' for s in hdpt.subrecords],
                                   *part_files(plugins, files, hdpt))
                fresh[f.edid] = f.digest
                done = manifest.get(f.edid) == f.digest and (out_dir / 'Meshes' / f.model.replace('\\', '/')).exists()
                if done or dry_run:
                    kept += done
                else:
                    fit_hair(plugins, files, f, source, target, ears_move_hair)
                    for rel, data in f.files.items():
                        dest = out_dir / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_bytes(data)
                    refit += 1
                fitted.append(f)
                bar.update(1, f.edid)
        by_prefix.setdefault(prefix, [all_races, []])[1].extend(fitted)
    for edid, why in sorted(set(skipped)):
        log(f'    skipped {edid}: {why}')
    total = sum(len(f) for _, f in by_prefix.values())
    if dry_run:
        log(f'  Hair: would fit {total - sum(1 for e, d in fresh.items() if manifest.get(e) == d)} of '
            f'{total}; {len(set(skipped))} skipped')
        return None
    if not total and not plugin_path.exists():
        return None
    masters = ['Starfield.esm']                # spelled as the race TOMLs spell them
    for cfg in races:
        if cfg.plugin.lower() not in (m.lower() for m in masters):
            masters.append(cfg.plugin)
    if strings_for is None:
        from fsftools.string_table import load_all_string_tables
        tables = {}

        def strings_for(plugin):
            stem = Path(plugin.file_path).stem
            if stem not in tables:
                tables[stem] = load_all_string_tables(Path(data_dir), stem)
            return tables[stem]
    write_records(plugin_path, masters, [(p, a, f) for p, (a, f) in sorted(by_prefix.items())],
                  plugins, strings_for, 'FSFTools hair fit', prune=list(by_prefix))
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(dict(sorted(fresh.items())), indent=1), encoding='utf-8')
    log(f'  Hair: {total} fitted hairs in {plugin_path} ({refit} refitted, {kept} up to date); '
        f'{len(set(skipped))} skipped')
    return plugin_path
