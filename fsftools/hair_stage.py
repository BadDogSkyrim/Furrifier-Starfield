"""Fit the source race's hair to other races' heads and write the parts and their records.

    python -m fsftools.hair_stage --races FSFFoxRace FSFHyenaRace --sex FEMALE --limit 10 \\
        --out C:/tmp/sf_hair_fit/out --assets C:/Modding/Starfield/00StarfieldAssets

Races sharing a head share the fitted hair: one fit per head, with an RNAM list of all of them.

A fitted HDPT is a copy of the source one with a new EditorID, model, race list and morphs. Its
morphs have a key for each of the target head's keys that moves it (hair_fit.fit_keys). Hairs with
cloth or extra parts are skipped for now and reported.
"""
import argparse
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


@dataclass
class HeadShape:
    shape: hair_fit.Shape
    head: hair_fit.Head                       # bone space, HideEar applied
    keys: Dict[str, Dict[str, hair_fit.Key]]  # 'chargen'/'performance' -> keys
    morph_dirs: Dict[str, str]                # 'chargen'/'performance' -> TCMP/TMPP folder
    ears: np.ndarray                          # vertices HideEar moves

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


def load_part_keys(plugins, assets: Assets, hdpt, num_verts: int):
    """A part's morph keys and folders by kind, from its MRPH; empty where it has none."""
    keys, dirs = {k: {} for k in MORPH_SUBS}, {}
    mrph = plugins.resolve_reference(hdpt, 'MNAM') if hdpt.get_subrecord('MNAM') else None
    for kind, sig in MORPH_SUBS.items():
        sr = mrph.get_subrecord(sig) if mrph is not None else None
        if sr is None:
            continue
        dirs[kind] = _text(sr)
        path = assets.find(Path(dirs[kind]) / 'morph.dat')
        if path.exists():
            keys[kind] = hair_fit.load_keys(path, num_verts)
    return keys, dirs, mrph


def load_head(plugins, assets: Assets, hdpt) -> HeadShape:
    """A head in C_Head space with its HideEar performance key applied, and its morphs."""
    shape = assets.shape(_text(hdpt.get_subrecord('MODL')))
    keys, dirs, _ = load_part_keys(plugins, assets, hdpt, len(shape.positions))
    missing = [k for k in MORPH_SUBS if k not in dirs]
    if missing:
        raise ValueError(f'{hdpt.editor_id}: no {"/".join(missing)} morphs')
    hide = keys['performance'].get(HIDE_EAR)
    if hide is None:
        print(f'  WARNING: {hdpt.editor_id} has no {HIDE_EAR} key; fitting with the ears out')
        ears = np.zeros(len(shape.positions), bool)
        key = None
    else:
        ears = hide.moved()
        key = _load_morphs(assets.find(Path(dirs['performance']) / 'morph.dat')).get(HIDE_EAR)
    return HeadShape(shape, hair_fit.head_in_bone_space(shape, key), keys, dirs, ears)


def is_ear_key(name: str) -> bool:
    """A chargen key of the Ears region."""
    return name.endswith('_Ears')


@dataclass
class Fitted:
    source: object             # the source HDPT
    edid: str
    model: str                 # relative to Meshes
    files: Dict[Path, bytes] = field(default_factory=dict)
    morphs: Dict[str, str] = field(default_factory=dict)   # kind -> folder, relative to Data
    mobc: bytes = b'\xff\x00\x00\x00'
    stats: str = ''


def fit_hair(plugins, assets: Assets, hdpt, source: HeadShape, target: HeadShape, prefix: str,
             folder: str, sex: str, ears_move_hair: bool = True) -> Fitted:
    """The hair's nif, its companion, their meshes and the morphs, fitted to the target head."""
    model = _text(hdpt.get_subrecord('MODL'))
    nif_path = assets.find(Path('Meshes') / model)
    shape = assets.shape(model)
    part = shape.to_bone(shape.positions)
    fit = hair_fit.fit_offsets(source.head, target.head, part, shape.tris)
    name = Path(model.replace('\\', '/')).name
    rel = Path('Actors') / folder / 'Hair' / sex.capitalize() / name
    out = Fitted(hdpt, fitted_edid(hdpt.editor_id, prefix), str(rel).replace('/', '\\'))
    pieces = [(shape, rel)]
    companion = hair_fit.companion_path(nif_path)
    if companion is not None:
        other = hair_fit.load_shape(companion, assets.mesh)
        if len(other.positions) != len(shape.positions) or \
                np.abs(other.positions - shape.positions).max() > hair_fit.EPSILON:
            raise ValueError(f'{companion.name}: its vertices differ from {name}')
        pieces.append((other, rel.with_name(companion.name)))
    for piece, path in pieces:
        nif, mesh_name, mesh = hair_fit.fit_files(piece, fit.offsets)
        out.files[Path('Meshes') / path] = nif
        out.files[Path('Geometries') / (mesh_name + '.mesh')] = mesh
    part_keys, _, mrph = load_part_keys(plugins, assets, hdpt, len(shape.positions))
    if mrph is not None and mrph.get_subrecord('MOBC') is not None:
        out.mobc = bytes(mrph.get_subrecord('MOBC').data)
    target_src = target.sources(part + fit.offsets, ears_move_hair)
    source_src = source.sources(part, ears_move_hair)
    counts = []
    for kind in MORPH_SUBS:
        keys = hair_fit.fit_keys(target.keys[kind], source.keys[kind], part_keys[kind], target_src,
                                 source_src, target.shape, source.shape, shape, ear_key=is_ear_key)
        folder_rel = str(Path(target.morph_dirs[kind].replace('\\', '/')).parent / Path(name).stem)
        out.morphs[kind] = folder_rel.replace('/', '\\')
        out.files[Path(folder_rel) / 'morph.dat'] = hair_fit.write_keys(keys, len(shape.positions))
        counts.append(f'{len(keys)} {kind}')
    moved = np.linalg.norm(fit.offsets, axis=1)
    out.stats = (f'{len(moved)} verts, offset mean {moved.mean() * 1000:.1f} mm, max {moved.max() * 1000:.1f} mm, '
                 f'{fit.missed} rays missed, companion {"yes" if companion else "no"}; keys {", ".join(counts)}')
    return out


def skip_reason(assets: Assets, hdpt) -> Optional[str]:
    if hdpt.get_subrecord('HNAM') is not None:
        return 'has extra parts (a later phase)'
    nif = assets.find(Path('Meshes') / _text(hdpt.get_subrecord('MODL')))
    if not nif.exists():
        return f'{nif} not found'
    if b'BSClothExtraData' in nif.read_bytes():
        return 'has cloth (a later phase)'
    return None


# ----- records -----------------------------------------------------------------------------------

def _z(s: str) -> bytes:
    return s.encode('cp1252') + b'\0'


def write_records(path: Path, masters: List[str], fitted_by_head, plugins, strings, author: str):
    """Create or update the hair plugin: per head, a race list and the fitted HDPTs. A record with
    the same EditorID is rewritten in place under its FormID."""
    from esplib import Plugin, Record, SubRecord
    from fsftools.plugin_writer import _output_form_id, _patch_sf_light_flag
    from esplib.utils import FormID

    if path.exists():
        out = Plugin.load(str(path))
        if [m.lower() for m in out.header.masters] != [m.lower() for m in masters]:
            raise ValueError(f'{path.name} has masters {out.header.masters}, expected {masters}')
    else:
        out = Plugin()
        out.file_path = path
        out.header.version = 0.96
        out.header.masters = list(masters)
        out.header.master_sizes = [0] * len(masters)
        out.header.is_esl = True
        out.header.is_esm = True
        out.header.author = author
    own = len(masters) << 24
    existing = {(r.signature, r.editor_id): r for r in out}
    next_id = max([FIRST_ID, out.header.next_object_id or 0]
                  + [(int(r.form_id.value) & 0xFFFFFF) + 1 for r in out])

    def put(sig: str, edid: str, subs) -> int:
        nonlocal next_id
        rec = existing.get((sig, edid))
        if rec is None:
            rec = Record(sig, FormID(own | next_id))
            next_id += 1
            out.add_record(rec)
            existing[(sig, edid)] = rec
        rec.subrecords[:] = [SubRecord('EDID', _z(edid))] + subs
        return int(rec.form_id.value)

    for (prefix, races), fitted in fitted_by_head.items():
        race_list = put('FLST', f'{prefix}_HairRaces',
                        [SubRecord('LNAM', struct.pack('<I', _output_form_id(r, masters))) for r in races])
        for f in fitted:
            home = Path(f.source.plugin.file_path).name
            if home.lower() != masters[0].lower():
                raise ValueError(f'{f.source.editor_id} is from {home}: only {masters[0]} hairs so far')
            morph = put('MRPH', f'MORPH_{f.edid}',
                         [SubRecord('TMPP', _z(f.morphs['performance'])),
                          SubRecord('TCMP', _z(f.morphs['chargen'])), SubRecord('MOBC', f.mobc)])
            subs = []
            for sr in f.source.subrecords:
                if sr.signature == 'EDID':
                    continue
                if sr.signature == 'FULL':
                    sid = struct.unpack('<I', sr.data[:4])[0] if len(sr.data) == 4 else None
                    text = strings.get(sid) if sid is not None else None
                    subs.append(SubRecord('FULL', _z(text if text else f.edid)))
                elif sr.signature == 'MODL':
                    subs.append(SubRecord('MODL', _z(f.model)))
                elif sr.signature == 'RNAM':
                    subs.append(SubRecord('RNAM', struct.pack('<I', race_list)))
                elif sr.signature == 'MNAM':
                    continue
                else:
                    subs.append(SubRecord(sr.signature, bytes(sr.data)))
            subs.append(SubRecord('MNAM', struct.pack('<I', morph)))
            put('HDPT', f.edid, subs)
    out.header.next_object_id = next_id
    out.save(str(path))
    _patch_sf_light_flag(path)


# ----- driver ------------------------------------------------------------------------------------

def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--races', nargs='+', required=True, help='target races, by EditorID')
    p.add_argument('--source-race', default='HumanRace')
    p.add_argument('--sex', choices=SEXES, action='append', help='default: both')
    p.add_argument('--hair', nargs='+', metavar='EDID', help='only these source hairs')
    p.add_argument('--limit', type=int, help='at most this many hairs per head and sex')
    p.add_argument('--out', type=Path, required=True, help='root for Meshes, Geometries and the plugin')
    p.add_argument('--hair-plugin', default='FSFHair.esm', help='created in --out if missing')
    p.add_argument('--plugins', nargs='+', help='load order (default: Starfield.esm, then the masters '
                   'of each plugin defining a target race)')
    p.add_argument('--data', type=Path)
    p.add_argument('--assets', type=Path, help='unpacked vanilla assets, laid out like Data')
    p.add_argument('--ears-fixed', action='store_true',
                   help="ear vertices never move the hair (default: they do, under every key; the "
                        "hair's base shape is fitted with the ears hidden either way)")
    p.add_argument('--dry-run', action='store_true', help='fit and report; write nothing')
    return p.parse_args(argv)


def main(argv=None):
    from fsftools.plugin_loader import discover_data_dir, load_order_for_plugin, load_plugins
    from fsftools.string_table import load_all_string_tables
    args = parse_args(argv)
    data_dir = args.data or discover_data_dir()
    order = args.plugins or ['Starfield.esm']
    if not args.plugins:
        for name in sorted(p.name for p in Path(data_dir).glob('*.esm')):
            if name.lower().startswith('fsf') and name.lower() != args.hair_plugin.lower():
                for n in load_order_for_plugin(Path(data_dir), name):
                    if n.lower() not in [o.lower() for o in order]:
                        order.append(n)
    plugins = load_plugins(Path(data_dir), order)
    assets = Assets(data_dir, args.assets)
    source_race = plugins.get_record_by_edid('RACE', args.source_race)
    source_heads = race_heads(plugins, source_race)

    groups: Dict = {}
    for edid in args.races:
        race = plugins.get_record_by_edid('RACE', edid)
        if race is None:
            raise SystemExit(f'race {edid} not found in {order}')
        for sex, head in race_heads(plugins, race).items():
            groups.setdefault((head_prefix(head), sex), (head, []))[1].append(race)

    fitted_by_head: Dict = {}
    skipped = []
    for (prefix, sex), (head, races) in sorted(groups.items()):
        if args.sex and sex not in args.sex:
            continue
        print(f'== {prefix} {sex}: {head.editor_id} for {", ".join(r.editor_id for r in races)}')
        src = load_head(plugins, assets, source_heads[sex])
        tgt = load_head(plugins, assets, head)
        done = []
        for hdpt in source_hairs(plugins, source_race, sex):
            if args.hair and hdpt.editor_id not in args.hair:
                continue
            if args.limit is not None and len(done) >= args.limit:
                break
            why = skip_reason(assets, hdpt)
            if why:
                skipped.append((hdpt.editor_id, why))
                continue
            f = fit_hair(plugins, assets, hdpt, src, tgt, prefix, head_folder(head), sex,
                         not args.ears_fixed)
            print(f'  {f.edid}: {f.stats}')
            done.append(f)
            if not args.dry_run:
                for rel, data in f.files.items():
                    dest = args.out / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(data)
        key = (prefix, tuple(races))
        fitted_by_head.setdefault(key, []).extend(done)
    for edid, why in skipped:
        print(f'  skipped {edid}: {why}')
    if args.dry_run:
        return
    masters = []
    for plugin_name in order:
        if any(r.plugin is not None and Path(r.plugin.file_path).name.lower() == plugin_name.lower()
               for (_p, races) in fitted_by_head for r in races) or plugin_name.lower() == 'starfield.esm':
            masters.append(plugin_name)
    strings = load_all_string_tables(Path(data_dir), 'Starfield')
    path = args.out / args.hair_plugin
    write_records(path, masters, {(p, races): f for (p, races), f in fitted_by_head.items()},
                  plugins, strings, 'FSFTools hair fit')
    print(f'wrote {path}: {sum(len(f) for f in fitted_by_head.values())} hairs')


if __name__ == '__main__':
    main()
