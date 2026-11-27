"""Bake NPC FaceGen without the Creation Kit: the head nif, its meshes and its four textures.

What this writes was worked out by comparing against the CK's own output (tests/test_facegen.py
holds that comparison), under a mod folder laid out like Data:

    Meshes\\Actors\\Character\\FaceGenData\\FaceGeom\\<plugin>\\<id>.NIF
    Textures\\Actors\\Character\\FaceCustomization\\<plugin>\\<id>_{Color,Normal,ao,rough}.dds
    Geometries\\<20 hex>\\<20 hex>.mesh

<plugin> is the plugin that defines the NPC and <id> its local FormID, as the CK names them.

The nif holds one shape per head part, its skin copied from the part's own nif. Each part's mesh
is its source mesh with the NPC's chargen morphs and body weights applied, named by the SHA-1 of
its bytes, so parts that come out identical share one file.

The NPC's morph groups also pick the textures. Each FCT_<region>_mask paints its region with the maps
of whichever phenotypes have a key there, at the key's weight, and with <sex>_default for the rest;
FCT_null_mask paints the NPC's phenotype. The normal, rough, ao and base colour are all blended that
way, then the tint layers are laid over the colour in linear space. A region with no morph key
therefore gets the default maps, however little its key would move the vertices.

Not reproduced exactly: the CK also nudges every part's vertices, morphed or not (about 0.03 mm on
an eye, 0.5 mm near the neck), and sets a flag bit on some shapes and not others, with no rule found.
"""
import hashlib
import os
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from fsftools import safe_write

KIND_SIMPLE, KIND_COMPLEX = 1, 2
FLT_MAX = b'\xff\xff\x7f\x7f'
MIPS = 5                   # the CK writes 5 of a 1024 face's 11 levels
# INTV at which a tint layer is laid on at full strength; 64 (the presets' usual) clamps to it. Measured
# on the CK's bake of the hyena male preset, derm at INTV 53: strength 0.8406, i.e. 53/63, not 53/64.
FULL_INTENSITY = 63
# The face maps' folder (under Textures) for a race without FCTP: HumanRace has none.
DEFAULT_FCTP = r'actors\human\faces\chargen'


def _text(sr) -> str:
    return sr.data.rstrip(b'\0').decode('utf-8', 'replace')


# ----- nif reading -----------------------------------------------------------------------------

@dataclass
class Nif:
    types: List[str]
    strings: List[str]
    blocks: List[Tuple[str, bytes]]

    def shape_names(self) -> List[str]:
        return [self.strings[struct.unpack_from('<I', b)[0]] for t, b in self.blocks if t == 'BSGeometry']


def read_nif(data: bytes) -> Nif:
    """The block list of a Starfield nif. Blocks stay as bytes: their sizes are in the header."""
    o = data.index(b'\n') + 1 + 4 + 1 + 4
    count = struct.unpack_from('<I', data, o)[0]
    o += 8
    # The export-info strings vary in layout, so find the type list by its shape.
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
    index = struct.unpack_from(f'<{count}H', data, o)
    o += 2 * count
    sizes = struct.unpack_from(f'<{count}I', data, o)
    o += 4 * count
    num_strings = struct.unpack_from('<I', data, o)[0]
    o += 8
    strings = []
    for _ in range(num_strings):
        n = struct.unpack_from('<I', data, o)[0]
        strings.append(data[o + 4:o + 4 + n].decode('latin1'))
        o += 4 + n
    o += 4          # groups
    blocks = []
    for i in range(count):
        blocks.append((types[index[i]], data[o:o + sizes[i]]))
        o += sizes[i]
    return Nif(types, strings, blocks)


# ----- mesh ------------------------------------------------------------------------------------

def _mesh_layout(data: bytes):
    """Offsets of a .mesh's sections, through the weights. See Library meshes.md section 2."""
    _, num_indices = struct.unpack_from('<II', data)
    o = 8 + num_indices * 2
    scale, _, num_verts = struct.unpack_from('<fII', data, o)
    o += 12
    pos = o
    o += num_verts * 6
    counts = {}
    for name in ('uv1', 'uv2', 'color', 'normal', 'tangent', 'weight'):
        n = struct.unpack_from('<I', data, o)[0]
        counts[name] = (o + 4, n)
        o += 4 + n * 4
    return dict(scale=scale, num_indices=num_indices, num_verts=num_verts, pos=pos, end=o, **counts)


def split_mesh(data: bytes) -> Dict[str, bytes]:
    """A .mesh cut where a bake can differ. A section is what the bake must keep or may change."""
    m = _mesh_layout(data)
    normal, tangent = m['normal'], m['tangent']
    return {'head': data[:m['pos']], 'pos': data[m['pos']:m['pos'] + m['num_verts'] * 6],
            'uv': data[m['pos'] + m['num_verts'] * 6:normal[0]],
            'normals': data[normal[0]:normal[0] + normal[1] * 4],
            'tangents': data[tangent[0]:tangent[0] + tangent[1] * 4],
            'weights': data[tangent[0] + tangent[1] * 4:m['end']], 'tail': data[m['end']:]}


@dataclass
class MorphKey:
    verts: np.ndarray
    pos: np.ndarray       # metres
    normal: np.ndarray
    tangent: np.ndarray


@dataclass
class PartSource:
    """A head part's nif blocks, source mesh and chargen morphs."""
    edid: str
    geometry: bytes
    skin_attach: bytes
    integer_data: bytes
    instance: bytes
    bone_data: bytes
    shader: bytes
    material: str
    mesh: bytes
    tri_size: int
    num_verts: int
    morphs: Dict[str, MorphKey] = field(default_factory=dict)


@dataclass
class BakedMesh:
    name: str           # <20 hex>\<20 hex>
    tri_size: int
    num_verts: int
    data: bytes


def _udec(u: np.ndarray) -> np.ndarray:
    return np.stack([((u >> s) & 1023) / 511.5 - 1.0 for s in (0, 10, 20)], axis=-1)


def _load_morphs(path: Path) -> Dict[str, MorphKey]:
    from pyn.sf_morph import MorphFile, _half_to_float, _marker_bits
    mf = MorphFile.from_file(str(path))
    rows = {n: [] for n in mf.morph_names}
    for v, (start, marker) in enumerate(mf.offsets):
        for i, k in enumerate(_marker_bits(marker)):
            rows[mf.morph_names[k]].append((v, start + i))
    out = {}
    for name, items in rows.items():
        if not items:
            continue
        records = [mf.records[r] for _, r in items]
        out[name] = MorphKey(
            np.array([v for v, _ in items]),
            np.array([[_half_to_float(x) for x in r[:3]] for r in records], np.float64),
            _udec(np.array([r[4] for r in records], np.uint32)),
            _udec(np.array([r[5] for r in records], np.uint32)))
    return out


def find_asset(rel: Path, data_dir: Path, assets: Optional[Path], first: Optional[Path] = None) -> Path:
    """A game file: in `first` (this run's output, not yet deployed), else loose in Data, else in the
    unpacked vanilla assets (--assets). The Data path when none has it, so reading it raises."""
    if first is not None and (Path(first) / rel).exists():
        return Path(first) / rel
    loose = Path(data_dir) / rel
    if loose.exists() or assets is None:
        return loose
    unpacked = Path(assets) / rel
    return unpacked if unpacked.exists() else loose


def load_part_source(data_dir: Path, hdpt, plugins, assets: Optional[Path] = None,
                     first: Optional[Path] = None) -> PartSource:
    """Read a head part's own nif and mesh. Fox parts are loose; a vanilla part (a kept hair) is in
    a BA2, so it's read from the unpacked assets; a fitted hair may be in the run's output (`first`),
    not yet deployed. Missing from all raises."""
    data_dir = Path(data_dir)
    modl = _text(hdpt.get_subrecord('MODL'))
    nif = read_nif(find_asset(Path('Meshes') / modl, data_dir, assets, first).read_bytes())
    found = [i for i, (t, _) in enumerate(nif.blocks) if t == 'BSGeometry']
    if len(found) != 1:
        raise ValueError(f"{hdpt.editor_id}: {modl} has {len(found)} shapes; expected one")
    geo = nif.blocks[found[0]][1]
    fields = _geometry_fields(geo)
    extras = {nif.blocks[r][0]: nif.blocks[r][1] for r in fields['extras']}
    mesh_len = struct.unpack_from('<I', geo, fields['mesh'] + 12)[0]
    mesh_name = geo[fields['mesh'] + 16:fields['mesh'] + 16 + mesh_len].decode('latin1')
    tri_size, num_verts = struct.unpack_from('<II', geo, fields['mesh'])
    mesh = find_asset(Path('Geometries') / (mesh_name + '.mesh'), data_dir, assets, first).read_bytes()
    instance = nif.blocks[fields['skin']][1]
    shader = nif.blocks[fields['shader']][1]
    source = PartSource(
        edid=hdpt.editor_id, geometry=geo, skin_attach=extras['SkinAttach'],
        integer_data=extras['NiIntegerExtraData'], instance=instance,
        bone_data=nif.blocks[struct.unpack_from('<I', instance, 4)[0]][1], shader=shader,
        material=nif.strings[struct.unpack_from('<I', shader)[0]], mesh=mesh,
        tri_size=tri_size, num_verts=num_verts)
    mnam = hdpt.get_subrecord('MNAM')
    if mnam is not None:
        mrph = plugins.resolve_reference(hdpt, 'MNAM')
        tcmp = mrph.get_subrecord('TCMP') if mrph is not None else None
        path = find_asset(Path(_text(tcmp)) / 'morph.dat', data_dir, assets, first) if tcmp is not None else None
        if path is not None and path.exists():
            from pyn.sf_morph import MorphFile
            morph_verts = MorphFile.from_file(str(path)).num_vertices
            if morph_verts != num_verts:
                raise ValueError(f"{hdpt.editor_id}: its chargen morph {_text(tcmp)}\\morph.dat has {morph_verts} "
                                 f"vertices, but its nif {modl} (mesh {mesh_name}) has {num_verts}. The morph was "
                                 f"made for another mesh: export the part and its morphs together.")
            source.morphs = _load_morphs(path)
    return source


def _geometry_fields(geo: bytes) -> Dict:
    """Where a BSGeometry's fields sit: the name, extras, then fixed-size fields up to the refs."""
    num_extra = struct.unpack_from('<I', geo, 4)[0]
    extras = list(struct.unpack_from(f'<{num_extra}I', geo, 8))
    o = 8 + num_extra * 4
    flags = o + 4           # controller, then flags
    xform = flags + 4
    refs = xform + 13 * 4 + 4 + 40    # transform, collision, bounds
    skin, shader, alpha = struct.unpack_from('<III', geo, refs)
    mesh = refs + 12
    if geo[mesh] != 1:
        raise ValueError('first mesh slot is empty')
    return dict(extras=extras, flags=flags, xform=xform, refs=refs, skin=skin, shader=shader, alpha=alpha,
                mesh=mesh + 1)


def bake_mesh(source: PartSource, weights: Dict[str, float]) -> BakedMesh:
    """The source mesh with morphs applied and its LOD and cull data gone, named by its SHA-1."""
    data = source.mesh
    m = _mesh_layout(data)
    active = [(source.morphs[k], w) for k, w in weights.items() if w and k in source.morphs]

    positions = np.frombuffer(data, '<i2', m['num_verts'] * 3, m['pos']).reshape(-1, 3).astype(np.float64)
    normal_off, normal_n = m['normal']
    tangent_off, tangent_n = m['tangent']
    normals = np.frombuffer(data, '<u4', normal_n, normal_off).copy()
    tangents = np.frombuffer(data, '<u4', tangent_n, tangent_off).copy()

    pos_bytes = data[m['pos']:m['pos'] + m['num_verts'] * 6]
    normals &= 0x3FFFFFFF         # the CK clears the 2-bit w on both
    tangents &= 0x3FFFFFFF
    if active:
        factor = 32767 / m['scale']
        n_vec, t_vec = _udec(normals), _udec(tangents)
        touched = np.zeros(m['num_verts'], bool)
        for key, w in active:
            positions[key.verts] += key.pos * w * factor
            n_vec[key.verts] += key.normal * w
            t_vec[key.verts] += key.tangent * w
            touched[key.verts] = True
        pos_bytes = np.rint(positions).clip(-32768, 32767).astype('<i2').tobytes()
        normals[touched] = _encode_udec(n_vec[touched])
        tangents[touched] = _encode_udec(t_vec[touched])

    out = b''.join((data[:m['pos']], pos_bytes, data[m['pos'] + m['num_verts'] * 6:normal_off],
                    normals.astype('<u4').tobytes(), data[normal_off + normal_n * 4:tangent_off],
                    tangents.astype('<u4').tobytes(), data[tangent_off + tangent_n * 4:m['end']],
                    b'\0\0\0\0'))
    digest = hashlib.sha1(out).hexdigest()
    return BakedMesh(digest[:20] + '\\' + digest[20:], m['num_indices'], m['num_verts'], out)


def _encode_udec(vectors: np.ndarray) -> np.ndarray:
    unit = vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-9)
    codes = np.floor((unit + 1) * 511.5).astype(np.int64).clip(0, 1023).astype(np.uint32)
    return codes[:, 0] | (codes[:, 1] << 10) | (codes[:, 2] << 20)


# ----- nif writing -----------------------------------------------------------------------------

_NIF_HEADER = b'Gamebryo File Format, Version 20.2.0.7\n\x07\x00\x02\x14\x01\x0c\x00\x00\x00'
# The last 13 bytes are a length-prefixed string of junk, and vary between the CK's own files.
_NIF_STREAM = struct.pack('<I', 175) + b'\x01\x00\x03\x00\x00\x00\x01\x00' \
    + b'\x0c\xfe\xff\xff\xff\xff\xff\xff\xff\xc0\x82\x15\x00'
_NIF_TYPES = ['BSFaceGenNiNode', 'BSGeometry', 'SkinAttach', 'NiIntegerExtraData',
              'BSSkin::Instance', 'BSSkin::BoneData', 'BSLightingShaderProperty']
_ROOT_NAME = 'BSFaceGenNiNodeSkinned'
_IDENTITY = struct.pack('<13f', 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 1)


def build_nif(shapes: List[Tuple[str, PartSource, BakedMesh]]) -> bytes:
    """The FaceGen nif: a root, then six blocks per shape in the CK's order."""
    strings = [_ROOT_NAME]

    def intern(s: str) -> int:
        if s not in strings:
            strings.append(s)
        return strings.index(s)

    blocks = [(0, b'')]
    children = []
    for edid, source, mesh in shapes:
        base = len(blocks)
        children.append(base)
        name = intern(edid)
        skin_name = intern('SkinBMP')
        material_name = intern('MaterialID')
        material = intern(source.material)

        path = f'Geometries\\{mesh.name}.mesh'.encode('latin1')
        f = _geometry_fields(source.geometry)
        flags = struct.unpack_from('<I', source.geometry, f['flags'])[0] | 0x00080000
        geometry = b''.join((
            struct.pack('<II', name, 2), struct.pack('<II', base + 1, base + 2), source.geometry[8 + len(f['extras']) * 4:f['flags']],
            struct.pack('<I', flags), source.geometry[f['xform']:f['refs']],
            struct.pack('<IIi', base + 3, base + 5, -1), b'\x01',
            struct.pack('<IIII', mesh.tri_size, mesh.num_verts, 0x40, len(path)), path, b'\0\0\0'))
        bones = struct.unpack_from('<I', source.skin_attach, 4)[0]
        instance = b''.join((struct.pack('<III', 0, base + 4, bones), struct.pack('<i', -1) * bones,
                             struct.pack('<I', bones), struct.pack('<fff', 0, 1, 1) * bones))
        blocks += [(1, geometry),
                   (2, struct.pack('<I', skin_name) + source.skin_attach[4:]),
                   (3, struct.pack('<I', material_name) + source.integer_data[4:]),
                   (4, instance),
                   (5, source.bone_data),
                   (6, struct.pack('<IIi', material, 0, -1))]

    root = b''.join((struct.pack('<IIi', 0, 0, -1), struct.pack('<I', 0x0000000E), _IDENTITY, struct.pack('<i', -1),
                     struct.pack('<I', len(children)), struct.pack(f'<{len(children)}I', *children), b'\x01\x00'))
    blocks[0] = (0, root)

    out = [_NIF_HEADER, struct.pack('<I', len(blocks)), _NIF_STREAM, struct.pack('<H', len(_NIF_TYPES))]
    for t in _NIF_TYPES:
        out += [struct.pack('<I', len(t)), t.encode('latin1')]
    out.append(struct.pack(f'<{len(blocks)}H', *[t for t, _ in blocks]))
    out.append(struct.pack(f'<{len(blocks)}I', *[len(b) for _, b in blocks]))
    encoded = [s.encode('latin1') for s in strings]
    out.append(struct.pack('<II', len(encoded), max(len(s) for s in encoded)))
    for s in encoded:
        out += [struct.pack('<I', len(s)), s]
    out.append(struct.pack('<I', 0))
    out += [b for _, b in blocks]
    out.append(struct.pack('<II', 1, 0))
    return b''.join(out)


# ----- colour ----------------------------------------------------------------------------------

_LINEAR = np.where(np.arange(256) / 255.0 <= 0.04045, (np.arange(256) / 255.0) / 12.92,
                   ((np.arange(256) / 255.0 + 0.055) / 1.055) ** 2.4).astype(np.float32)


def _srgb_to_linear(a: np.ndarray) -> np.ndarray:
    return _LINEAR[np.rint(a * 255).astype(np.uint8)]


def _linear_to_srgb(a: np.ndarray) -> np.ndarray:
    a = np.clip(a, 0, 1)
    return np.where(a <= 0.0031308, a * 12.92, 1.055 * np.power(a, 1 / 2.4) - 0.055)


def _load(data_dir: Path, path: str, cache: Dict, assets: Optional[Path] = None,
          first: Optional[Path] = None) -> np.ndarray:
    """A texture, found as find_asset finds it: a vanilla one (a kept hair's scalp mask) may be only
    in the unpacked assets."""
    import uv_transfer
    if path not in cache:
        found = find_asset(Path(path.replace('\\', '/')), data_dir, assets, first)
        cache[path] = uv_transfer.load_image(str(found))
    return cache[path]


def _sized(image: np.ndarray, h: int, w: int) -> np.ndarray:
    if image.shape[:2] == (h, w):
        return image
    from PIL import Image
    return np.stack([np.asarray(Image.fromarray(image[..., i]).resize((w, h), Image.BILINEAR))
                     for i in range(image.shape[-1])], axis=-1)


def composite_face(data_dir, base, layers: List[Tuple[str, bytes, int]], cache: Dict,
                   assets: Optional[Path] = None, first: Optional[Path] = None) -> np.ndarray:
    """The baked colour as H x W x 3 uint8. Layers are (texture, NNAM bytes, INTV), bottom first.

    base is a texture path, or {path: H x W weight} to blend several. A colour texture (RGBA) lays
    on by its own alpha. A mask (an R8 `_mask`, no alpha; or any layer with a non-zero NNAM) paints
    the NNAM's colour through its red: the bytes are x, B, G, R, already linear, and the x byte
    isn't an alpha. NNAM 00000000 on a mask is black, not invisible.
    """
    if isinstance(base, dict):
        out = sum(_srgb_to_linear(_load(data_dir, p, cache, assets, first)[..., :3]) * w[..., None]
                  for p, w in base.items())
    else:
        out = _srgb_to_linear(_load(data_dir, base, cache, assets, first)[..., :3])
    h, w = out.shape[:2]
    for path, color, intensity in layers:
        image = _sized(_load(data_dir, path, cache, assets, first), h, w)
        strength = min(1.0, intensity / FULL_INTENSITY)
        if color != b'\0\0\0\0' or image.shape[-1] < 4:
            alpha = image[..., :1] * strength
            out = out * (1 - alpha) + np.array([color[3], color[2], color[1]], np.float32) / 255 * alpha
        else:
            alpha = (image[..., 3:4] if image.shape[-1] == 4 else np.ones((h, w, 1), np.float32)) * strength
            rgb = image[..., :3] if image.shape[-1] >= 3 else np.repeat(image[..., :1], 3, axis=-1)
            out = out * (1 - alpha) + _srgb_to_linear(rgb) * alpha
    return np.rint(_linear_to_srgb(out) * 255).astype(np.uint8)


# Head parts that paint the face through their NAM3: part type (HDPT PNAM) -> (mask group, colour sub).
FOLLICLE_GROUPS = {4: ('BeardFollicleMask', 'FHCL'), 3: ('HairFollicleMask', 'HCOL')}


def mask_painting_parts(parts, kept_hair) -> List:
    """The parts whose follicle masks are painted: not a kept human hair, whose mask is drawn for
    the human face's UVs and would land in the wrong place on the race's face."""
    return [h for h in parts if h.editor_id not in kept_hair]


def follicle_layers(parts, npc, avm) -> List[Tuple[str, bytes]]:
    """(mask texture, NNAM colour) for each part whose NAM3 names a follicle mask.

    NAM3 is a key in the Simple group for the part's type (or its `_AVMDEXT` extension), matched
    exactly; a key with no entry paints nothing, as in the CK. The colour is the NPC's hair colour
    sub (FHCL for facial hair, HCOL for hair) looked up in the Modulation group of the same name.
    """
    from fsftools.race_data import KIND_MODULATION, KIND_SIMPLE, group_entries
    out = []
    for hdpt in parts:
        nam3, pnam = hdpt.get_subrecord('NAM3'), hdpt.get_subrecord('PNAM')
        if nam3 is None or pnam is None:
            continue
        group = FOLLICLE_GROUPS.get(struct.unpack('<I', pnam.data[:4])[0])
        if group is None:
            continue
        name, colour_sig = group
        masks = {}
        for edid in (name, name + '_AVMDEXT'):
            rec = avm.get((KIND_SIMPLE, edid))
            if rec is not None:
                masks.update(group_entries(rec))
        texture = masks.get(_text(nam3), (None, b''))[0]
        if not texture:
            continue
        # No colour (no HCOL, or a name the group lacks) paints black, as a mask with NNAM 0 does.
        colour_sub = npc.get_subrecord(colour_sig)
        modulation = avm.get((KIND_MODULATION, name))
        colour = group_entries(modulation).get(_text(colour_sub)) \
            if colour_sub is not None and modulation is not None else None
        out.append((texture, bytes(colour[1]) if colour is not None else b'\0\0\0\0'))
    return out


def follicle_rough(rough: np.ndarray, masks: List[Tuple[np.ndarray, bytes]]) -> np.ndarray:
    """The roughness (0-255) with each follicle mask's colour's first byte laid on by the mask. A
    first byte of 0 (no colour) leaves the roughness as it is."""
    for image, colour in masks:
        if not colour[0]:
            continue
        a = _sized(image, *rough.shape)[..., 0]
        rough = rough * (1 - a) + colour[0] * a
    return rough


def _dds_header(h: int, w: int) -> bytes:
    """The CK's header for a colour face: DX10, R8G8B8A8_UNORM_SRGB, MIPS levels."""
    head = bytearray(148)
    head[:4] = b'DDS '
    struct.pack_into('<IIIIII', head, 4, 124, 0x0002100F, h, w, w * 4, 1)
    struct.pack_into('<I', head, 28, MIPS)
    struct.pack_into('<II4s', head, 76, 32, 4, b'DX10')
    struct.pack_into('<I', head, 108, 0x00401008)
    struct.pack_into('<IIIII', head, 128, 29, 3, 0, 1, 0)
    return bytes(head)


def write_color_dds(path, image: np.ndarray):
    """H x W x 3 uint8 to a DDS with MIPS levels; each level averages the one above."""
    h, w = image.shape[:2]
    rgba = np.dstack([image, np.full((h, w), 255, np.uint8)])
    parts = [_dds_header(h, w), rgba.tobytes()]
    level = rgba.astype(np.float32)
    for _ in range(MIPS - 1):
        level = (level[::2, ::2] + level[1::2, ::2] + level[::2, 1::2] + level[1::2, 1::2]) / 4
        parts.append(np.rint(level).astype(np.uint8).tobytes())
    safe_write.write_bytes(path, b''.join(parts))


# ----- region-blended maps -----------------------------------------------------------------------

_R8_HEADER = bytes.fromhex(
    '444453207c0000000f1002000004000000040000000400000100000005000000'
    '0000000000000000000000000000000000000000000000000000000000000000'
    '00000000000000000000000020000000000002000000000008000000ff000000'
    '0000000000000000000000000810400000000000000000000000000000000000'
)
assert len(_R8_HEADER) == 128


def _texconv():
    import sf_texconv
    found = sf_texconv.find_texconv(None)
    if not found:
        raise RuntimeError('texconv.exe not found; set TEXCONV')
    return found


class FaceMaps:
    """A race's FCT masks and phenotype maps, decoded once each and blended per NPC."""

    def __init__(self, data_dir: Path, fctp: str, regions: List[str], work_dir: Path):
        self.folder = Path(data_dir) / 'Textures' / fctp
        self.regions = list(regions)
        self.work_dir = Path(work_dir)
        self.images: Dict[str, np.ndarray] = {}
        self.masks = {r: self._read(f'FCT_{r}_mask.dds')[..., 0] / 255.0 for r in self.regions + ['null']}

    def _read(self, name: str) -> np.ndarray:
        if name not in self.images:
            source = self.folder / name
            if not source.exists():
                raise FileNotFoundError(source)
            run = subprocess.run([_texconv(), '-nologo', '-y', '-ft', 'png', '-f', 'R8G8B8A8_UNORM',
                                  '-o', str(self.work_dir), str(source)], capture_output=True, text=True)
            made = self.work_dir / (source.stem + '.png')
            if run.returncode != 0 or not made.exists():
                raise RuntimeError(f"texconv could not read {source}: {run.stdout}")
            from PIL import Image
            with Image.open(made) as im:
                self.images[name] = np.asarray(im.convert('RGB'), np.float32)
            made.unlink()
        return self.images[name]

    def has_maps(self, phenotype: str) -> bool:
        return all((self.folder / f'{phenotype}_{s}.dds').exists() for s in ('ao', 'rough', 'normal'))

    def region_weights(self, phenotype: str, default: str, morphs: Dict[str, float]) -> Dict[str, np.ndarray]:
        """{phenotype: H x W weight} summing to 1 wherever any mask covers."""
        keyed = {}
        for key, value in morphs.items():
            who, _, region = key.rpartition('_')
            # A phenotype with no maps (vanilla's male_eu_md3) doesn't count: its share of the region
            # goes to the default, as in the CK's bake.
            if region in self.masks and region != 'null' and who and self.has_maps(who):
                keyed.setdefault(region, {})
                keyed[region][who] = keyed[region].get(who, 0.0) + value
        shape = self.masks['null'].shape
        out = {phenotype: self.masks['null'].astype(np.float32).copy(), default: np.zeros(shape, np.float32)}
        for region in self.regions:
            mask = self.masks[region].astype(np.float32)
            rows = keyed.get(region, {})
            used = sum(rows.values())
            for who, value in rows.items():
                out[who] = out.get(who, np.zeros(shape, np.float32)) + mask * (value / max(used, 1.0))
            out[default] += mask * max(0.0, 1.0 - used)
        total = np.maximum(sum(out.values()), 1e-6)
        return {who: w / total for who, w in out.items()}

    def blend(self, suffix: str, weights: Dict[str, np.ndarray]) -> np.ndarray:
        """The map for one NPC as H x W x 3 float. Phenotypes with no such map are skipped."""
        images = [(self._read(f'{who}_{suffix}.dds'), w) for who, w in weights.items()]
        if all(np.array_equal(images[0][0], image) for image, _ in images[1:]):
            return images[0][0]       # floating point would otherwise make each NPC's bytes differ
        out = None
        for image, w in images:
            part = image * w[..., None]
            out = part if out is None else out + part
        return out


def _mips(level: np.ndarray) -> List[bytes]:
    parts = [np.rint(level).astype(np.uint8).tobytes()]
    for _ in range(MIPS - 1):
        level = (level[::2, ::2] + level[1::2, ::2] + level[::2, 1::2] + level[1::2, 1::2]) / 4
        parts.append(np.rint(level).astype(np.uint8).tobytes())
    return parts


def write_r8_dds(path, channel: np.ndarray):
    """One channel to the CK's legacy R8 layout, as for _ao and _rough."""
    safe_write.write_bytes(path, _R8_HEADER + b''.join(_mips(channel)))


def write_normals(jobs: List[Tuple[Path, np.ndarray]], work_dir: Path, batch: int = 40):
    """BC5 through texconv, in batches: a source PNG per job, then one call per batch."""
    from PIL import Image
    for i in range(0, len(jobs), batch):
        group = jobs[i:i + batch]
        made = []
        for dest, image in group:
            png = work_dir / (dest.stem + '.png')
            rgb = np.rint(image).astype(np.uint8)
            Image.fromarray(rgb).save(png)
            made.append(png)
        run = subprocess.run([_texconv(), '-nologo', '-y', '-m', str(MIPS), '-f', 'BC5_SNORM', '-dx9', '-srgb',
                              '-o', str(work_dir), *[str(p) for p in made]], capture_output=True, text=True)
        for (dest, _), png in zip(group, made):
            done = png.with_suffix('.dds')
            if run.returncode != 0 or not done.exists():
                raise RuntimeError(f"texconv failed on {png}: {run.stdout}")
            with safe_write.replacing(dest) as scratch:
                shutil.move(str(done), str(scratch))
            png.unlink()


# Names one shared map may have. NTFS stops at 1024, and a hardlink deploy (Vortex, MO2's) adds one name per
# staged name, so a group has to stay at half that or the deploy fails ("The OS is reporting an error without
# details"). Past it, the next NPC starts a new group.
LINKS_PER_FILE = 500


def _link_or_write(cache: Dict[str, Path], dest: Path, write):
    """Write a map, hard-linking NPCs whose bytes come out the same (the AO usually does)."""
    with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False, suffix='.tmp') as tmp:
        scratch = Path(tmp.name)
    try:
        write(scratch)
        digest = hashlib.sha1(scratch.read_bytes()).hexdigest()
    except BaseException:
        scratch.unlink()
        raise
    if dest.exists():
        dest.unlink()
    shared = cache.get(digest)
    if shared is not None and shared.exists() and os.stat(shared).st_nlink < LINKS_PER_FILE:
        scratch.unlink()
        try:
            os.link(shared, dest)
            return
        except OSError:
            pass
        with safe_write.replacing(dest) as copy:
            shutil.copyfile(shared, copy)
    else:
        scratch.replace(dest)
        cache[digest] = dest


# ----- the bake --------------------------------------------------------------------------------

def _face_tones(race, avm) -> Dict[str, List[str]]:
    """{phenotype: texture per skin tone} through the race's FSTT complex group."""
    fstt = next((_text(s) for s in race.subrecords if s.signature == 'FSTT'), None)
    group = avm.get((KIND_COMPLEX, fstt))
    out = {}
    if group is None:
        return out
    pairs, key = [], None
    for s in group.subrecords:
        if s.signature == 'LNAM':
            key = _text(s)
        elif s.signature == 'VNAM' and key:
            pairs.append((key, _text(s)))
            key = None
    for phenotype, target in pairs:
        simple = avm.get((KIND_SIMPLE, target.split('_', 1)[-1]))
        if simple is None:
            continue
        textures, current = [], False
        for s in simple.subrecords:
            if s.signature == 'LNAM':
                current = True
            elif s.signature == 'VNAM' and current:
                textures.append(_text(s))
                current = False
        out[phenotype] = textures
    return out


def _with_extra_parts(parts: List, plugins) -> List:
    """Each part, then the parts its HNAM pulls in, once each."""
    seen, out = set(), []

    def add(hdpt):
        if hdpt is None or hdpt.editor_id in seen:
            return
        seen.add(hdpt.editor_id)
        out.append(hdpt)
        for s in hdpt.get_subrecords('HNAM'):
            add(plugins.resolve_form_id(s.get_form_id(0), hdpt.plugin))

    for part in parts:
        add(part)
    return out


def _weights(change) -> Dict[str, float]:
    """The morph keys for this NPC: its morph groups, plus body weights the head also follows."""
    weights = dict(change.morph_groups)
    mwgt = change.source.get_subrecord('MWGT')
    if mwgt is not None and len(mwgt.data) == 12:
        weights.update(zip(('Thin', 'Strong', 'Overweight'), struct.unpack('<3f', mwgt.data)))
    return weights


def bake_all(changes, appearances, plugins, data_dir, out_dir, log=print,
             assets: Optional[Path] = None) -> Tuple[int, List[str]]:
    from fsftools.formid_remap import defining_plugin
    """Bake every planned NPC under out_dir. Returns (baked, problems)."""
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    sources: Dict[str, PartSource] = {}
    tones_by_race = {}
    textures: Dict = {}
    written = set()
    problems = []
    baked = 0
    missing = {}
    face_maps: Dict[str, FaceMaps] = {}
    shared: Dict[str, Path] = {}
    normals: List[Tuple[Path, np.ndarray]] = []
    from fsftools.progress import Progress
    with tempfile.TemporaryDirectory() as td, Progress('FaceGen', len(changes)) as bar:
        work = Path(td)
        for change in changes:
            bar.update(1, change.npc_editorid)
            appearance = appearances[change.new_race_edid]
            race = appearance.race
            tones = tones_by_race.setdefault(change.new_race_edid, _face_tones(race, appearance.avm))
            who = change.npc_editorid
            base_list = tones.get(change.phenotype)
            if base_list is None:
                missing.setdefault(change.phenotype, []).append(who)
                continue
            if change.new_ston >= len(base_list):
                problems.append(f"{who}: skin tone {change.new_ston} is past the {len(base_list)} of {change.phenotype}")
                continue
            home = defining_plugin(change.source, plugins).file_path.name
            from fsftools import formids
            ident = f'{formids.object_id(int(change.source.form_id.value), change.source.plugin):08X}'

            shapes, baked_parts = [], []
            weights = _weights(change)
            kept = {h.editor_id for h in _with_extra_parts(change.kept_hair, plugins)}
            for hdpt in _with_extra_parts(change.head_parts, plugins):
                if hdpt.get_subrecord('MODL') is None:
                    continue
                if hdpt.editor_id not in sources:
                    try:
                        sources[hdpt.editor_id] = load_part_source(data_dir, hdpt, plugins, assets, out_dir)
                    except (OSError, ValueError) as e:
                        if hdpt.editor_id not in kept:
                            raise
                        # A kept hair is an experiment: one that can't be read is left off, not fatal.
                        sources[hdpt.editor_id] = None
                        problems.append(f"kept hair {hdpt.editor_id} left out of the bake: {e}"
                                        + ("" if assets else " (give --assets for vanilla parts)"))
                source = sources[hdpt.editor_id]
                if source is None:
                    continue
                mesh = bake_mesh(source, weights)
                if mesh.name not in written:
                    path = out_dir / 'Geometries' / (mesh.name.replace('\\', os.sep) + '.mesh')
                    safe_write.write_bytes(path, mesh.data)
                    written.add(mesh.name)
                shapes.append((hdpt.editor_id, source, mesh))
                baked_parts.append((hdpt, source, mesh))

            nif = out_dir / 'Meshes' / 'Actors' / 'Character' / 'FaceGenData' / 'FaceGeom' / home / f'{ident}.NIF'
            safe_write.write_bytes(nif, build_nif(shapes))

            tex = out_dir / 'Textures' / 'Actors' / 'Character' / 'FaceCustomization' / home
            tex.mkdir(parents=True, exist_ok=True)
            maps = face_maps.get(change.new_race_edid)
            if maps is None:
                fctp = next((_text(s) for s in race.subrecords if s.signature == 'FCTP'), DEFAULT_FCTP)
                maps = face_maps[change.new_race_edid] = FaceMaps(data_dir, fctp, appearance.regions, work)
            default = ('female' if change.sex == 'FEMALE' else 'male') + '_default'
            region = maps.region_weights(change.phenotype, default, change.morph_groups)
            bases = {}
            for who, weight in region.items():
                listed = tones.get(who) or base_list
                path = listed[min(change.new_ston, len(listed) - 1)]
                bases[path] = bases[path] + weight if path in bases else weight
            # Follicle masks (a hair's or beard's NAM3) paint on top of the tints, at full strength.
            follicles = follicle_layers(mask_painting_parts([h for h, _, _ in baked_parts], kept),
                                        change.source, appearance.avm)
            layers = [(t.texture, t.color, t.intensity) for t in change.tints]
            layers += [(path, colour, FULL_INTENSITY) for path, colour in follicles]
            write_color_dds(tex / f'{ident}_Color.dds', composite_face(data_dir, bases, layers, textures, assets, out_dir))
            for suffix, source_suffix in (('ao', 'ao'), ('rough', 'rough')):
                channel = maps.blend(source_suffix, region)[..., 0]
                if suffix == 'rough' and follicles:
                    channel = follicle_rough(channel, [(_load(data_dir, p, textures, assets, out_dir), c)
                                                      for p, c in follicles])
                _link_or_write(shared, tex / f'{ident}_{suffix}.dds', lambda p, c=channel: write_r8_dds(p, c))
            normals.append((tex / f'{ident}_Normal.dds', maps.blend('normal', region)))
            if len(normals) >= 40:
                write_normals(normals, work)
                normals = []
            baked += 1
        if normals:
            write_normals(normals, work)
    for phenotype, names in missing.items():
        problems.append(f"{len(names)} NPCs not baked: {phenotype} is not an entry of the race's face skin tones "
                        f"(FSFFoxFaceSkinTones), and the CK bakes those with a black base. "
                        f"First few: {', '.join(names[:5])}")
    return baked, problems
