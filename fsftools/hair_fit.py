"""Refit a head part made for one head (the source) onto another (the target).

Generic: two heads in, a part in, a fitted part out. Nothing here knows about any one mod.

Everything works in one bone's space (C_Head), in metres. A raw Starfield .mesh holds its positions
in metres; the skin binds are in game units. Vanilla hair and heads bind C_Head with no offset (the
mesh is already in head space); other heads may be in model space, with the head's height in the
bind. The fit:

- Cast a ray from the bone's origin through each part vertex. Its offset is (target radius - source
  radius) along the ray, each radius being the outermost hit on that head.
- A vertex whose ray misses either head takes the mean offset of its nearest neighbours that hit.
- The offset field is smoothed over the part's own triangles, a few rounds.

Files: the fitted .mesh keeps everything but the positions and the meshlet cull boxes, which are
recomputed (one box per meshlet, its triangles taken in order; vanilla's match to 1e-8). The nif is
a byte copy with the mesh path changed and each bone's bounding sphere grown by the largest offset,
which stays a safe culling bound.
"""
import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

BONE = 'C_Head'
EPSILON = 1e-4                 # metres: smaller offsets count as none
HAVOC_SCALE_FACTOR = 69.99125  # game units per metre (PyNifly's nifconstants)


# ----- nif bytes ---------------------------------------------------------------------------------

@dataclass
class NifLayout:
    data: bytes
    types: List[str]
    block_types: List[int]
    sizes_at: int              # offset of the block-size table
    blocks_at: int             # offset of the first block
    sizes: List[int]

    def block(self, i: int) -> bytes:
        o = self.blocks_at + sum(self.sizes[:i])
        return self.data[o:o + self.sizes[i]]

    def type_of(self, i: int) -> str:
        return self.types[self.block_types[i]]

    def with_blocks(self, new: Dict[int, bytes]) -> bytes:
        """The nif with some blocks replaced; sizes updated, everything else byte for byte."""
        blocks = [new.get(i, self.block(i)) for i in range(len(self.sizes))]
        end = self.blocks_at + sum(self.sizes)
        return b''.join([self.data[:self.sizes_at], struct.pack(f'<{len(blocks)}I', *map(len, blocks)),
                         self.data[self.sizes_at + 4 * len(blocks):self.blocks_at], *blocks, self.data[end:]])


def nif_layout(data: bytes) -> NifLayout:
    """Where a Starfield nif's block table and blocks are (see facegen.read_nif)."""
    o = data.index(b'\n') + 1 + 4 + 1 + 4
    count = struct.unpack_from('<I', data, o)[0]
    o += 8
    for o in range(o, min(o + 1024, len(data) - 8)):
        num_types, first = struct.unpack_from('<HI', data, o)
        if 0 < num_types < 128 and 3 < first < 64 and data[o + 6:o + 8] in (b'BS', b'Ni', b'bh'):
            break
    else:
        raise ValueError('no block type list found')
    o += 2
    types = []
    for _ in range(num_types):
        n = struct.unpack_from('<I', data, o)[0]
        types.append(data[o + 4:o + 4 + n].decode('latin1'))
        o += 4 + n
    block_types = list(struct.unpack_from(f'<{count}H', data, o))
    o += 2 * count
    sizes_at = o
    sizes = list(struct.unpack_from(f'<{count}I', data, o))
    o += 4 * count
    num_strings = struct.unpack_from('<I', data, o)[0]
    o += 8
    for _ in range(num_strings):
        o += 4 + struct.unpack_from('<I', data, o)[0]
    num_groups = struct.unpack_from('<I', data, o)[0]
    o += 4 + 4 * num_groups
    return NifLayout(data, types, block_types, sizes_at, o, sizes)


def _geometry(nif: NifLayout) -> int:
    found = [i for i in range(len(nif.sizes)) if nif.type_of(i) == 'BSGeometry']
    if len(found) != 1:
        raise ValueError(f'{len(found)} shapes; a fitted part has one')
    return found[0]


def _mesh_slot(geo: bytes) -> Tuple[int, int, int]:
    """(offset of slot 0's BSGeometryMesh, its name's offset, name length); the other slots empty."""
    from fsftools.facegen import _geometry_fields
    f = _geometry_fields(geo)
    o = f['mesh']
    n = struct.unpack_from('<I', geo, o + 12)[0]
    rest = geo[o + 16 + n:]
    if rest[:3] != b'\0\0\0':
        raise ValueError('more than one LOD slot')
    return o, o + 16, n


def nif_mesh_name(data: bytes) -> str:
    nif = nif_layout(data)
    geo = nif.block(_geometry(nif))
    _, at, n = _mesh_slot(geo)
    return geo[at:at + n].decode('latin1')


def patch_nif(data: bytes, mesh_name: str, grow: float) -> bytes:
    """The nif pointing at another .mesh, its bones' bounding spheres grown by `grow` metres."""
    nif = nif_layout(data)
    gi = _geometry(nif)
    geo = nif.block(gi)
    slot, at, n = _mesh_slot(geo)
    name = mesh_name.encode('latin1')
    new_geo = geo[:at - 4] + struct.pack('<I', len(name)) + name + geo[at + n:]
    from fsftools.facegen import _geometry_fields
    skin = _geometry_fields(geo)['skin']
    bone_data = struct.unpack_from('<I', nif.block(skin), 4)[0]
    bd = bytearray(nif.block(bone_data))
    num = struct.unpack_from('<I', bd)[0]
    stride = (len(bd) - 4) // num if num else 0
    if num and stride * num + 4 != len(bd):
        raise ValueError('unexpected BSSkin::BoneData layout')
    for b in range(num):
        at_r = 4 + b * stride + 12
        r = struct.unpack_from('<f', bd, at_r)[0]
        struct.pack_into('<f', bd, at_r, r + grow)
    return nif.with_blocks({gi: new_geo, bone_data: bytes(bd)})


# ----- .mesh bytes -------------------------------------------------------------------------------

def mesh_arrays(data: bytes):
    """(layout, positions in metres (n,3), triangles (m,3))."""
    from fsftools.facegen import _mesh_layout
    m = _mesh_layout(data)
    pos = np.frombuffer(data, '<i2', m['num_verts'] * 3, m['pos']).reshape(-1, 3) / 32767.0 * m['scale']
    tris = np.frombuffer(data, '<u2', m['num_indices'], 8).reshape(-1, 3).astype(np.int64)
    return m, pos.astype(np.float64), tris


def _tail(data: bytes, m) -> Tuple[int, np.ndarray, int]:
    """(offset of the meshlet count, meshlets (k,4), offset of the cull data)."""
    o = m['end']
    for _ in range(struct.unpack_from('<I', data, o)[0]):
        o += 4
        o += struct.unpack_from('<I', data, o)[0] * 2
    o += 4
    at = o
    n = struct.unpack_from('<I', data, o)[0]
    meshlets = np.frombuffer(data, '<u4', n * 4, o + 4).reshape(-1, 4)
    cull_at = o + 4 + n * 16
    if struct.unpack_from('<I', data, cull_at)[0] != n or cull_at + 4 + n * 24 != len(data):
        raise ValueError('unexpected meshlet/cull layout')
    return at, meshlets, cull_at + 4


def cull_boxes(pos: np.ndarray, tris: np.ndarray, meshlets: np.ndarray) -> np.ndarray:
    """Each meshlet's box (centre, half-extents): its primCount triangles, taken in order."""
    out = np.zeros((len(meshlets), 6), np.float32)
    start = 0
    for k, count in enumerate(meshlets[:, 2]):
        v = pos[np.unique(tris[start:start + count])]
        lo, hi = v.min(0), v.max(0)
        out[k] = np.r_[(lo + hi) / 2, (hi - lo) / 2]
        start += count
    return out


def write_mesh(data: bytes, positions: np.ndarray) -> bytes:
    """The .mesh with new positions (metres) and its cull boxes to match."""
    m, _, tris = mesh_arrays(data)
    scale = m['scale']
    peak = float(np.abs(positions).max())
    if peak > scale:
        raise ValueError(f'fitted positions reach {peak:.3f} m, past the mesh scale {scale}')
    q = np.rint(positions / scale * 32767.0).clip(-32767, 32767).astype('<i2')
    out = bytearray(data)
    out[m['pos']:m['pos'] + m['num_verts'] * 6] = q.tobytes()
    _, meshlets, cull_at = _tail(data, m)
    decoded = q.astype(np.float64) / 32767.0 * scale
    out[cull_at:] = cull_boxes(decoded, tris, meshlets).astype('<f4').tobytes()
    return bytes(out)


def mesh_name(data: bytes) -> str:
    """A .mesh's name as the game tools make it: its SHA-1, split 20\\20."""
    d = hashlib.sha1(data).hexdigest()
    return d[:20] + '\\' + d[20:]


# ----- geometry ----------------------------------------------------------------------------------

@dataclass
class Shape:
    """A one-shape nif and its .mesh, with the bone-space transform."""
    nif: bytes
    mesh: bytes
    positions: np.ndarray      # shape space, metres
    tris: np.ndarray
    rotation: np.ndarray       # shape -> bone: p_bone = scale * R @ p + translation
    scale: float
    translation: np.ndarray    # metres

    def to_bone(self, p: np.ndarray) -> np.ndarray:
        return (p @ self.rotation.T) * self.scale + self.translation

    def to_shape(self, v: np.ndarray) -> np.ndarray:
        """A bone-space vector (an offset) back into shape space."""
        return (v @ self.rotation) / self.scale


def load_shape(nif_path: Path, mesh_path_for) -> Shape:
    """Read a one-shape nif and its mesh; `mesh_path_for(name)` finds a .mesh by its nif name."""
    from pyn.pynifly import NifFile
    nif = Path(nif_path).read_bytes()
    name = nif_mesh_name(nif)
    mesh = Path(mesh_path_for(name)).read_bytes()
    _, pos, tris = mesh_arrays(mesh)
    shape = NifFile(str(nif_path)).shapes[0]
    if BONE not in list(shape.bone_names or []):
        raise ValueError(f'{nif_path}: not skinned to {BONE}')
    xf = shape.get_shape_skin_to_bone(BONE)
    # The bind is in game units (PyNifly reads it as the nif holds it); the raw .mesh is metres.
    t = np.array(xf.translation[:], np.float64) / HAVOC_SCALE_FACTOR
    return Shape(nif, mesh, pos, tris, np.array(xf.rotation).reshape(3, 3), float(xf.scale), t)


@dataclass
class Head:
    verts: np.ndarray          # bone space, metres
    tris: np.ndarray


def head_in_bone_space(shape: Shape, morph=None) -> Head:
    """The head in bone space, with one morph key (a facegen.MorphKey, e.g. HideEar) applied."""
    p = shape.positions.copy()
    if morph is not None:
        p[morph.verts] += morph.pos
    return Head(shape.to_bone(p), shape.tris)


def radial_hits(head: Head, dirs: np.ndarray, chunk: int = 2048) -> np.ndarray:
    """Distance from the origin to the outermost hit on the head along each unit direction; NaN on
    a miss. Each triangle is culled by the cone round its centre that holds its corners."""
    v0, v1, v2 = (head.verts[head.tris[:, k]] for k in range(3))
    unit = [v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12) for v in (v0, v1, v2)]
    c = unit[0] + unit[1] + unit[2]
    c /= np.maximum(np.linalg.norm(c, axis=1, keepdims=True), 1e-12)
    cos_cone = np.minimum.reduce([(u * c).sum(1) for u in unit]) - 1e-6
    cos_cone[cos_cone <= 0] = -2.0         # a cone past 90 degrees: test every ray
    e1, e2 = v1 - v0, v2 - v0
    out = np.full(len(dirs), np.nan)
    for s in range(0, len(dirs), chunk):
        d = dirs[s:s + chunk]
        ri, ti = np.nonzero(d @ c.T >= cos_cone[None, :])
        if not len(ri):
            continue
        dd = d[ri]
        p = np.cross(dd, e2[ti])
        det = (e1[ti] * p).sum(1)
        ok = np.abs(det) > 1e-14
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        tv = -v0[ti]
        u = (tv * p).sum(1) * inv
        q = np.cross(tv, e1[ti])
        v = (dd * q).sum(1) * inv
        t = (e2[ti] * q).sum(1) * inv
        # A ray along a shared edge must hit one of its triangles despite rounding.
        hit = ok & (u >= -1e-7) & (v >= -1e-7) & (u + v <= 1 + 1e-7) & (t > 0)
        best = np.full(len(d), -np.inf)
        np.maximum.at(best, ri[hit], t[hit])
        best[np.isinf(best)] = np.nan
        out[s:s + chunk] = best
    return out


def _nearest(ref: np.ndarray, pts: np.ndarray, k: int, chunk: int = 1024) -> np.ndarray:
    """Indices of the k nearest `ref` points to each of `pts`."""
    r2 = (ref ** 2).sum(1)
    out = []
    k = min(k, len(ref))
    for s in range(0, len(pts), chunk):
        p = pts[s:s + chunk]
        d2 = (p ** 2).sum(1)[:, None] + r2[None, :] - 2 * p @ ref.T
        out.append(np.argpartition(d2, k - 1, axis=1)[:, :k])
    return np.vstack(out)


def _smooth(values: np.ndarray, tris: np.ndarray, rounds: int) -> np.ndarray:
    """Average each vertex with its edge neighbours, `rounds` times (half its own, half theirs)."""
    if rounds <= 0:
        return values
    a = np.r_[tris[:, 0], tris[:, 1], tris[:, 2], tris[:, 1], tris[:, 2], tris[:, 0]]
    b = np.r_[tris[:, 1], tris[:, 2], tris[:, 0], tris[:, 0], tris[:, 1], tris[:, 2]]
    n = len(values)
    count = np.bincount(a, minlength=n).astype(np.float64)
    for _ in range(rounds):
        total = np.zeros(n)
        np.add.at(total, a, values[b])
        mean = np.where(count > 0, total / np.maximum(count, 1), values)
        values = 0.5 * values + 0.5 * mean
    return values


@dataclass
class Fit:
    offsets: np.ndarray        # bone space, metres, per part vertex
    missed: int                # vertices whose ray missed a head
    radial: np.ndarray         # the smoothed radius change per vertex


def fit_offsets(source: Head, target: Head, part_bone: np.ndarray, part_tris: np.ndarray,
                smooth: int = 3, neighbours: int = 8) -> Fit:
    """How far to move each part vertex (bone space) to sit on the target head as it sat on the source."""
    r = np.linalg.norm(part_bone, axis=1)
    dirs = part_bone / np.maximum(r, 1e-12)[:, None]
    delta = radial_hits(target, dirs) - radial_hits(source, dirs)
    missed = np.isnan(delta)
    if missed.all():
        raise ValueError('no ray hit both heads')
    if missed.any():
        near = _nearest(part_bone[~missed], part_bone[missed], neighbours)
        delta[missed] = delta[~missed][near].mean(1)
    delta = _smooth(delta, part_tris, smooth)
    delta[np.abs(delta) < EPSILON] = 0.0
    return Fit(dirs * delta[:, None], int(missed.sum()), delta)


def fitted_positions(shape: Shape, offsets_bone: np.ndarray) -> np.ndarray:
    """The shape's positions moved by bone-space offsets."""
    return shape.positions + shape.to_shape(offsets_bone)


def fit_files(shape: Shape, offsets_bone: np.ndarray) -> Tuple[bytes, str, bytes]:
    """(nif bytes, mesh name, mesh bytes) for a shape moved by the offsets."""
    mesh = write_mesh(shape.mesh, fitted_positions(shape, offsets_bone))
    name = mesh_name(mesh)
    grow = float(np.linalg.norm(offsets_bone, axis=1).max()) / shape.scale if len(offsets_bone) else 0.0
    return patch_nif(shape.nif, name, grow), name, mesh


def companion_path(nif_path: Path) -> Optional[Path]:
    """The part's _facebones companion beside it, whatever its case; None if there isn't one."""
    nif_path = Path(nif_path)
    want = (nif_path.stem + '_facebones.nif').lower()
    if not nif_path.parent.is_dir():
        return None
    return next((p for p in nif_path.parent.iterdir() if p.name.lower() == want), None)


# ----- morphs ------------------------------------------------------------------------------------

@dataclass
class Key:
    """A morph key, dense over its mesh's vertices, in that mesh's shape space (metres)."""
    pos: np.ndarray            # (n, 3)
    normal: np.ndarray         # (n, 3) normal delta
    tangent: np.ndarray        # (n, 3) tangent delta

    def moved(self) -> np.ndarray:
        return np.linalg.norm(self.pos, axis=1) >= EPSILON


def _udec(u: np.ndarray) -> np.ndarray:
    return np.stack([((u >> s) & 1023) / 511.5 - 1.0 for s in (0, 10, 20)], axis=-1)


def _dec3n(v: np.ndarray) -> np.ndarray:
    """Encode deltas as DEC3N with w = 1, truncating as vanilla's writer does (a hair over, so a
    decoded code comes back as itself)."""
    c = ((np.clip(v, -1.0, 1.0) + 1.0) * 511.5 + 1e-6).astype(np.int64).clip(0, 1023)
    return (c[:, 0] | (c[:, 1] << 10) | (c[:, 2] << 20) | (1 << 30)).astype(np.uint32)


def load_keys(path: Path, num_verts: int) -> Dict[str, Key]:
    """A morph.dat as dense keys, in its file's key order."""
    from pyn.sf_morph import MorphFile, _marker_bits
    mf = MorphFile.from_file(str(path))
    if mf.num_vertices != num_verts:
        raise ValueError(f'{path}: {mf.num_vertices} vertices, the mesh has {num_verts}')
    rec = np.array(mf.records, dtype=np.uint64).reshape(-1, 6) if mf.records else np.zeros((0, 6), np.uint64)
    pos = rec[:, :3].astype(np.uint16).view(np.float16).astype(np.float64)
    nrm = _udec(rec[:, 4].astype(np.uint32))
    tan = _udec(rec[:, 5].astype(np.uint32))
    out = {name: Key(np.zeros((num_verts, 3)), np.zeros((num_verts, 3)), np.zeros((num_verts, 3)))
           for name in mf.morph_names}
    for v, (start, marker) in enumerate(mf.offsets):
        for i, k in enumerate(_marker_bits(marker)):
            key = out[mf.morph_names[k]]
            key.pos[v], key.normal[v], key.tangent[v] = pos[start + i], nrm[start + i], tan[start + i]
    return out


def write_keys(keys: Dict[str, Key], num_verts: int) -> bytes:
    """A morph.dat of the keys, in their order. A vertex gets a record for each key that moves it."""
    from pyn.sf_morph import MorphFile, _bits_marker
    names = list(keys)
    moved = np.stack([keys[n].moved() for n in names], 1) if names else np.zeros((num_verts, 0), bool)
    enc = {n: (keys[n].pos.astype(np.float16).view(np.uint16), _dec3n(keys[n].normal), _dec3n(keys[n].tangent))
           for n in names}
    mf = MorphFile()
    mf.num_vertices = num_verts
    mf.morph_names = names
    for v in range(num_verts):
        ks = np.nonzero(moved[v])[0]
        mf.offsets.append((len(mf.records), _bits_marker(int(k) for k in ks)))
        for k in ks:
            p, n, t = enc[names[k]]
            mf.records.append((int(p[v, 0]), int(p[v, 1]), int(p[v, 2]), 0, int(n[v]), int(t[v])))
    return mf.to_bytes()


@dataclass
class Sources:
    """For each part vertex, its nearest head vertices and their inverse-distance weights."""
    index: np.ndarray          # (n, k) head vertex indices
    weight: np.ndarray         # (n, k), rows sum to 1


def sources(head_bone: np.ndarray, part_bone: np.ndarray, allowed: Optional[np.ndarray] = None,
            k: int = 4) -> Sources:
    """The k nearest allowed head vertices to each part vertex, both in bone space."""
    ids = np.arange(len(head_bone)) if allowed is None else np.nonzero(allowed)[0]
    near = _nearest(head_bone[ids], part_bone, k)
    d = np.linalg.norm(head_bone[ids][near] - part_bone[:, None, :], axis=2)
    w = 1.0 / np.maximum(d, 1e-3)
    return Sources(ids[near], w / w.sum(1, keepdims=True))


def transfer(key: Key, src: Sources, head: Shape, part: Shape) -> Key:
    """A head key copied onto the part: each part vertex takes its sources' weighted mean delta,
    turned from the head's shape space through bone space into the part's."""
    def carry(a):
        bone = head.to_bone(a) - head.to_bone(np.zeros((1, 3)))       # vectors: no translation
        mean = (bone[src.index] * src.weight[..., None]).sum(1)
        return part.to_shape(mean)
    return Key(carry(key.pos), carry(key.normal), carry(key.tangent))


def _sum(*keys: Key, signs=None) -> Key:
    signs = signs or [1] * len(keys)
    return Key(*(sum(s * getattr(k, f) for s, k in zip(signs, keys)) for f in ('pos', 'normal', 'tangent')))


def fit_keys(target_keys: Dict[str, Key], source_keys: Dict[str, Key], part_keys: Dict[str, Key],
             target_src: Dict[bool, Sources], source_src: Dict[bool, Sources],
             target: Shape, source: Shape, part: Shape,
             ear_key=lambda name: False) -> Dict[str, Key]:
    """The fitted part's keys: one for each target-head key that moves it.

    - The part and the source head both have the key: the part's own delta, plus the target's
      delta minus the source's, each copied onto the part. Bethesda's tuning stays.
    - Otherwise the target's delta copied onto the part.
    Keys only the part has (a hat key) keep the part's delta. Keys only the source head has go.
    `*_src[True]` are the sources for ear keys (no ear vertices), `[False]` for the rest."""
    out = {}
    for name, tk in target_keys.items():
        ear = ear_key(name)
        moved_t = transfer(tk, target_src[ear], target, part)
        if name in part_keys and name in source_keys:
            moved_s = transfer(source_keys[name], source_src[ear], source, part)
            key = _sum(part_keys[name], moved_t, moved_s, signs=[1, 1, -1])
        else:
            key = moved_t
        if key.moved().any():
            out[name] = key
    for name, pk in part_keys.items():
        if name not in target_keys and name not in source_keys and pk.moved().any():
            out[name] = pk
    return out
