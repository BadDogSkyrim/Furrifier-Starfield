"""Crowd hair and hats fitted to the furry crowd heads (sf_furrify --hair, when crowds are furry).

Crowd actors wear hair as armor. Each crowd outfit names a hair list (LL_Crowd_Hairs_*) of hair and
hat armors. Each armor has one or two addons on HumanCrowdRace, whose MOD2 and MOD3 are the male and
female nifs. They have no morphs and no cloth, but they have LOD meshes.

One fit serves a breed: its first crowd head of each sex (the breed's heads by name, so md1 before
md2), and the breed's other heads wear it. Breeds whose first heads are the same share the fit. The
source is vanilla's first crowd head of each sex (the first armor in LL_Crowd_Heads). Bethesda puts any
crowd hair on any crowd head, so the differences between crowd heads are taken as too small to matter.

A crowd head has no HideEar morph, and its mesh also holds the eyes and arms. So each head is
fitted to as the race's own head (the one chargen uses) folds its ears: each crowd head vertex moves
as HideEar moves its nearest own-head vertex. Vertices farther than NEAR from the own head (the arms,
an ear too big to fold) are left out, and rays through them borrow from their neighbours.

A race's [hair] crowd_include / crowd_exclude pick the armors by EditorID (globs; no include means
all). The files go under the output folder, Meshes\\Actors\\<head folder>\\Hair\\<head>\\<nif>, with
their meshes in Geometries. A rerun refits only the nifs whose digest changed.
"""
import json
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from fsftools import hair_fit
from fsftools.hair_stage import (FITTER_VERSION, SOURCE_RACE, Assets, _digest, load_head, race_heads, wants)

CROWD_FIT_VERSION = 2             # bump when a change to the crowd fit should refit every nif
SOURCE_HEAD_LIST = 'LL_Crowd_Heads'
MODEL = {'male': 'MOD2', 'female': 'MOD3'}
CHARGEN_SEX = {'male': 'MALE', 'female': 'FEMALE'}
NEAR = 0.03                       # metres: farther from the race's own head is not head (arms)
MANIFEST = Path('FSFTools') / 'hair_fit' / 'crowd.json'


def _text(sr) -> str:
    return bytes(sr.data).rstrip(b'\0').decode('cp1252') if sr is not None else ''


def _entries(plugins, lvli) -> List:
    """A leveled list's entries (level, reference, count): the records referenced, in order."""
    out = []
    for sr in lvli.get_subrecords('LVLO'):
        ref = struct.unpack_from('<I', bytes(sr.data), 4)[0]
        out.append(plugins.resolve_form_id(_formid(ref), lvli.plugin))
    return out


def _formid(value):
    from esplib.utils import FormID
    return FormID(value)


def addons(plugins, armor) -> List:
    """An armor's addons, in order."""
    return [plugins.resolve_form_id(_formid(struct.unpack('<I', bytes(sr.data)[:4])[0]), armor.plugin)
            for sr in armor.get_subrecords('MODL')]


@dataclass
class CrowdHairs:
    """What crowds wear on their heads: the hair lists the outfits name and the armors in them."""
    lists: Dict[str, object]              # EditorID -> LVLI, as the outfits name them
    armors: Dict[str, object]             # EditorID -> ARMO, every one in those lists


def crowd_hairs(plugins, order) -> CrowdHairs:
    from fsftools.crowd_builder import CrowdError, crowd_outfits
    lists = {}
    for _, _, hair in crowd_outfits(plugins, order):
        lists.setdefault(hair.editor_id, hair)
    armors = {}
    for lst in lists.values():
        for rec in _entries(plugins, lst):
            if rec is None or rec.signature != 'ARMO':
                raise CrowdError(f"{lst.editor_id}: an entry that isn't an armor "
                                 f"({rec.signature if rec else 'not in the load order'})")
            armors.setdefault(rec.editor_id, rec)
    return CrowdHairs(lists, armors)


def source_heads(plugins) -> Dict[str, str]:
    """{sex: nif}: vanilla's first crowd head armor's models."""
    lst = plugins.get_record_by_edid('LVLI', SOURCE_HEAD_LIST)
    if lst is None:
        raise ValueError(f'{SOURCE_HEAD_LIST} not in the load order')
    armor = _entries(plugins, lst)[0]
    aa = addons(plugins, armor)[0]
    return {sex: _text(aa.get_subrecord(sig)) for sex, sig in MODEL.items()}


def first_head(pairs, sex: str) -> dict:
    """The breed's first head of a sex: the first head name, its first variant by name. Variants of
    one head share its mesh."""
    variants = [getattr(p, sex) for p in pairs]
    head = min(v['head'].lower() for v in variants)
    return min((v for v in variants if v['head'].lower() == head), key=lambda v: v['name'])


def head_key(variant: dict) -> str:
    return Path(variant['head']).stem


def head_folder(variant: dict) -> str:
    """Actors\\FSFFox_Crowd\\Mesh\\Male\\Variants\\x.nif -> FSFFox_Crowd."""
    parts = Path(variant['nifs']['average'].replace('\\', '/')).parts
    if len(parts) < 2 or parts[0].lower() != 'actors':
        raise ValueError(f"{variant['name']}: nif {variant['nifs']['average']} is not under Actors")
    return parts[1]


def cut_head(shape: hair_fit.Shape, own) -> Tuple[hair_fit.Head, float]:
    """The crowd head as the fit sees it, against the race's own head (a HeadShape): each vertex
    moved as HideEar moves its nearest vertex on the own head, so the ears fold down, and only the
    vertices within NEAR of the own head kept, which drops the arms and any ear too big to fold.
    Returns the head and the share of vertices kept."""
    verts = shape.to_bone(shape.positions)
    rest = own.shape.to_bone(own.shape.positions)
    near = hair_fit._nearest(rest, verts, 1)[:, 0]
    keep = np.linalg.norm(rest[near] - verts, axis=1) < NEAR
    folded = verts + (own.head.verts - rest)[near]
    return hair_fit.Head(folded, shape.tris[keep[shape.tris].all(1)]), float(keep.mean())


@dataclass
class CrowdHairFit:
    """The fitted nifs, by (target head, source nif lowered), and each breed's heads (male, female)."""
    models: Dict[Tuple[str, str], str] = field(default_factory=dict)
    breeds: Dict[Tuple[str, str], Tuple[str, str]] = field(default_factory=dict)
    armors: Dict[str, List[str]] = field(default_factory=dict)     # race -> armor EditorIDs it takes
    hairs: Optional[CrowdHairs] = None

    def model(self, head: str, source: str) -> Optional[str]:
        return self.models.get((head.lower(), source.lower()))


def fit(plugins, order, data_dir: Path, plan, races, out_dir: Path, assets: Optional[Path] = None,
        dry_run: bool = False, log=print, verbose: bool = False) -> CrowdHairFit:
    """Fit every crowd hair and hat nif to each breed's first heads; write the files into out_dir.
    `plan`: the CrowdPlan; `races`: {EditorID: RaceConfig}."""
    from fsftools.progress import Progress
    out_dir = Path(out_dir)
    files = Assets(data_dir, assets)
    hairs = crowd_hairs(plugins, order)
    result = CrowdHairFit(hairs=hairs)
    if not plan.races:
        return result
    manifest_path = out_dir / MANIFEST
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        manifest = {}

    def own_head(race_edid, sex):
        race = plugins.get_record_by_edid('RACE', race_edid)
        if race is None:
            raise ValueError(f'race {race_edid} not in the load order')
        head = race_heads(plugins, race).get(CHARGEN_SEX[sex])
        if head is None:
            raise ValueError(f'{race_edid} has no {sex} head')
        return load_head(plugins, files, head, log)

    sources = {}
    for sex, nif in source_heads(plugins).items():
        shape = hair_fit.load_lods(files.find(Path('Meshes') / nif), files.mesh, count=1)[0]
        head, kept = cut_head(shape, own_head(SOURCE_RACE, sex))
        sources[sex] = (head, _digest(shape.nif, shape.mesh), nif)
        if verbose:
            log(f'    source {sex} crowd head {nif}: {kept:.0%} of it is head')

    # What to fit: (target head key, sex) -> (variant, race, the armors it takes).
    targets: Dict[Tuple[str, str], list] = {}
    for race_edid, rplan in plan.races.items():
        cfg = races[race_edid]
        takes = [e for e in hairs.armors if wants(e, cfg.crowd_hair_include, cfg.crowd_hair_exclude)]
        result.armors[race_edid] = takes
        for breed, pairs in rplan.heads.items():
            pick = {sex: first_head(pairs, sex) for sex in MODEL}
            result.breeds[(race_edid, breed)] = (head_key(pick['male']), head_key(pick['female']))
            for sex, variant in pick.items():
                slot = targets.setdefault((head_key(variant), sex), [variant, race_edid, []])
                slot[2] += [e for e in takes if e not in slot[2]]

    fresh, refit, kept = {}, 0, 0
    jobs = []
    for (key, sex), (variant, race_edid, takes) in sorted(targets.items()):
        models = []
        for edid in takes:
            for aa in addons(plugins, hairs.armors[edid]):
                m = _text(aa.get_subrecord(MODEL[sex]))
                if m and m.lower() not in (x.lower() for x in models):
                    models.append(m)
        jobs.append((key, sex, variant, race_edid, models))
    total = sum(len(j[4]) for j in jobs)
    with Progress('Fitting crowd hair', total) as bar:
        for key, sex, variant, race_edid, models in jobs:
            shape = hair_fit.load_lods(files.find(Path('Meshes') / variant['nifs']['average']), files.mesh, count=1)[0]
            own = own_head(race_edid, sex)
            target, share = cut_head(shape, own)
            if verbose:
                log(f'    {key}: {share:.0%} of it is head')
            src_head, src_digest, _ = sources[sex]
            head_digest = _digest(CROWD_FIT_VERSION, FITTER_VERSION, NEAR, src_digest, own.digest,
                                  sources[sex][2], shape.nif, shape.mesh)
            for model in models:
                rel = str(Path('Actors') / head_folder(variant) / 'Hair' / key /
                          Path(model.replace('\\', '/')).name).replace('/', '\\')
                result.models[(key.lower(), model.lower())] = rel
                nif = files.find(Path('Meshes') / model)
                if not nif.exists():
                    raise ValueError(f'{model} not found' + (' in Data or the unpacked assets' if assets else
                                                             ' (give --assets for nifs in BA2s)'))
                lods = hair_fit.load_lods(nif, files.mesh)
                digest = _digest(head_digest, nif, *dict.fromkeys(files.mesh(n) for n in
                                                                  hair_fit.nif_mesh_names(lods[0].nif)))
                fresh[rel] = digest
                dest = out_dir / 'Meshes' / rel.replace('\\', '/')
                if manifest.get(rel) == digest and dest.exists() or dry_run:
                    kept += not dry_run
                else:
                    data, meshes, fits = hair_fit.fit_lods(lods, src_head, target)
                    for name, mesh in meshes.items():
                        p = out_dir / 'Geometries' / (name.replace('\\', '/') + '.mesh')
                        p.parent.mkdir(parents=True, exist_ok=True)
                        p.write_bytes(mesh)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(data)
                    refit += 1
                    if verbose:
                        moved = max(float(np.linalg.norm(f.offsets, axis=1).max()) for f in fits)
                        log(f'    {rel}: max offset {moved * 1000:.1f} mm, '
                            f'{sum(f.missed for f in fits)} rays missed')
                bar.update(1, Path(model).name)
    if dry_run:
        log(f'  Crowd hair: would fit {sum(1 for r, d in fresh.items() if manifest.get(r) != d)} of {len(fresh)}')
        return result
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(dict(sorted(fresh.items())), indent=1), encoding='utf-8')
    log(f'  Crowd hair: {len(fresh)} nifs for {len(jobs)} heads ({refit} refitted, {kept} up to date)')
    return result
