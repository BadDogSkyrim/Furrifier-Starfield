"""hair_fit: refitting a head part onto another head. File writing on vanilla hair, the fit itself on
synthetic heads, and on real heads: vanilla's human head, and the FSF snapshot's canine one."""
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fsftools import hair_fit  # noqa: E402
from tests import tt  # noqa: E402
from tests.fsfdata import SNAPSHOT  # noqa: E402

A = Path(tt.SF_ASSETS)
HAIR = r'actors\human\mesh\hairs\cropped\cropped_m.nif'
HUMAN_HEAD = r'actors\human\characterassets\male\malehead.nif'
CANINE_HEAD = r'Actors\fsfcanine\CharacterAssets\male\CanineMaleHead.nif'


def vanilla_mesh(name):
    return A / 'Geometries' / (name + '.mesh')


def snapshot_mesh(name):
    p = SNAPSHOT / 'Geometries' / (name + '.mesh')
    return p if p.exists() else vanilla_mesh(name)


def vanilla(rel):
    return hair_fit.load_shape(A / 'Meshes' / rel, vanilla_mesh)


def sphere(radius, n=24):
    """A UV sphere round the origin: (verts, tris)."""
    th, ph = np.meshgrid(np.linspace(0.05, np.pi - 0.05, n), np.linspace(0, 2 * np.pi, 2 * n, endpoint=False),
                         indexing='ij')
    v = np.stack([np.sin(th) * np.cos(ph), np.sin(th) * np.sin(ph), np.cos(th)], -1).reshape(-1, 3) * radius
    tris = []
    for i in range(n - 1):
        for j in range(2 * n):
            a, b = i * 2 * n + j, i * 2 * n + (j + 1) % (2 * n)
            c, d = a + 2 * n, b + 2 * n
            tris += [(a, b, d), (a, d, c)]
    return v, np.array(tris)


def test_radial_hits_sphere():
    """The outermost hit on a sphere is its radius (to the facets' sag)."""
    v, t = sphere(0.1, 48)
    rng = np.random.default_rng(1)
    d = rng.normal(size=(200, 3))
    d[:, 2] *= 0.5                       # keep away from the open poles
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    r = hair_fit.radial_hits(hair_fit.Head(v, t), d)
    assert not np.isnan(r).any()
    assert np.abs(r - 0.1).max() < 0.001


def test_fit_moves_by_the_radius_change():
    """Hair 1 cm out from a 10 cm head sits 1 cm out from a 12 cm one: moved 2 cm along its ray."""
    small, t = sphere(0.10)
    big, _ = sphere(0.12)
    hair, hair_tris = sphere(0.11, 12)
    fit = hair_fit.fit_offsets(hair_fit.Head(small, t), hair_fit.Head(big, t), hair, hair_tris, smooth=0)
    moved = hair + fit.offsets
    assert np.abs(np.linalg.norm(moved, axis=1) - 0.13).max() < 0.002
    assert fit.missed == 0       # many rays run along the spheres' edges: rounding mustn't lose them


def test_misses_borrow_from_neighbours():
    """A vertex whose ray misses the target takes its neighbours' offset."""
    small, t = sphere(0.10)
    big, _ = sphere(0.12)
    keep = big[:, 2] < 0.11              # a hole at the target's top
    target = hair_fit.Head(big, t[keep[t].all(1)])
    hair = np.array([[0.0, 0.0, 0.11], [0.0, 0.07, 0.08], [0.07, 0.0, 0.08], [0.0, -0.07, 0.08]])
    fit = hair_fit.fit_offsets(hair_fit.Head(small, t), target, hair, np.array([[0, 1, 2], [0, 2, 3]]),
                               smooth=0)
    assert fit.missed >= 1
    assert abs(np.linalg.norm(fit.offsets[0]) - 0.02) < 0.004


@tt.requires_assets('SF')
def test_patch_nif_unchanged_is_identical():
    """Pointing a nif at its own mesh, with nothing grown, gives back the same bytes."""
    data = (A / 'Meshes' / HAIR).read_bytes()
    assert hair_fit.patch_nif(data, hair_fit.nif_mesh_name(data), 0.0) == data


@tt.requires_assets('SF')
def test_patch_nif_renames_and_grows():
    data = (A / 'Meshes' / HAIR).read_bytes()
    new = hair_fit.patch_nif(data, 'a' * 20 + '\\' + 'b' * 20, 0.01)
    assert hair_fit.nif_mesh_name(new) == 'a' * 20 + '\\' + 'b' * 20
    nif = hair_fit.nif_layout(new)
    bd = next(nif.block(i) for i in range(len(nif.sizes)) if nif.type_of(i) == 'BSSkin::BoneData')
    old = hair_fit.nif_layout(data)
    bd0 = next(old.block(i) for i in range(len(old.sizes)) if old.type_of(i) == 'BSSkin::BoneData')
    n = struct.unpack_from('<I', bd)[0]
    for b in range(n):
        r, r0 = (struct.unpack_from('<f', x, 4 + b * 68 + 12)[0] for x in (bd, bd0))
        assert abs(r - r0 - 0.01) < 1e-6


@tt.requires_assets('SF')
def test_write_mesh_unmoved_keeps_the_mesh():
    """Writing a mesh's own positions back keeps every byte but the cull boxes, which match."""
    s = vanilla(HAIR)
    out = hair_fit.write_mesh(s.mesh, s.positions)
    m, _, _ = hair_fit.mesh_arrays(s.mesh)
    _, _, cull_at = hair_fit._tail(s.mesh, m)
    assert out[:cull_at] == s.mesh[:cull_at]
    a = np.frombuffer(out, '<f4', offset=cull_at)
    b = np.frombuffer(s.mesh, '<f4', offset=cull_at)
    assert np.abs(a - b).max() < 1e-6


@tt.requires_assets('SF')
def test_human_onto_human_moves_nothing():
    head = vanilla(HUMAN_HEAD)
    h = hair_fit.head_in_bone_space(head)
    hair = vanilla(HAIR)
    fit = hair_fit.fit_offsets(h, h, hair.to_bone(hair.positions), hair.tris)
    assert not fit.offsets.any()


MORPHS = A / 'Meshes' / 'morphs' / 'human' / 'male'


def human_keys(kind, name, n):
    return hair_fit.load_keys(MORPHS / kind / name / 'morph.dat', n)


@tt.requires_assets('SF')
def test_keys_round_trip():
    """Vanilla hair morphs read, written and read again: the same keys and values wherever a key
    moves a vertex 0.1 mm or more (smaller records are dropped)."""
    import tempfile
    hair = vanilla(HAIR)
    n = len(hair.positions)
    keys = hair_fit.load_keys(MORPHS / 'chargen' / 'cropped_m' / 'morph.dat', n)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / 'morph.dat'
        out.write_bytes(hair_fit.write_keys(keys, n))
        again = hair_fit.load_keys(out, n)
    assert list(again) == list(keys)
    for name, key in keys.items():
        m = key.moved()
        assert (again[name].moved() == m).all(), name
        for f in ('pos', 'normal', 'tangent'):
            assert (getattr(again[name], f)[m] == getattr(key, f)[m]).all(), (name, f)


@tt.requires_assets('SF')
def test_human_onto_human_keeps_the_morphs():
    """Fitting human hair to the human head keeps each key vanilla gave the hair."""
    head = vanilla(HUMAN_HEAD)
    h = hair_fit.head_in_bone_space(head)
    hair = vanilla(HAIR)
    pts = hair.to_bone(hair.positions)
    src = hair_fit.sources(h.verts, pts)
    sources = {True: src, False: src}
    for kind in ('chargen', 'performance'):
        head_keys = human_keys(kind, 'head', len(head.positions))
        part_keys = human_keys(kind, 'cropped_m', len(hair.positions))
        out = hair_fit.fit_keys(head_keys, head_keys, part_keys, sources, sources, head, head, hair)
        for name, key in part_keys.items():
            if key.moved().any():
                assert name in out, name
                assert np.abs(out[name].pos - key.pos).max() < 1e-9, name


def test_transfer_turns_through_bone_space():
    """A head key moving every vertex by d reaches the part as d, turned from the head's frame
    into the part's."""
    rot = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1.0]])      # head shape -> bone: 90 degrees about z
    head = hair_fit.Shape(b'', b'', np.random.default_rng(2).normal(size=(50, 3)) * 0.1,
                          np.zeros((0, 3), int), rot, 1.0, np.array([0.0, 0.0, 1.6]))
    part = hair_fit.Shape(b'', b'', np.zeros((5, 3)), np.zeros((0, 3), int), np.eye(3), 1.0, np.zeros(3))
    d = np.array([0.01, 0.0, 0.0])
    key = hair_fit.Key(np.tile(d, (50, 1)), np.zeros((50, 3)), np.zeros((50, 3)))
    src = hair_fit.sources(head.to_bone(head.positions), np.zeros((5, 3)))
    moved = hair_fit.transfer(key, src, head, part)
    assert np.allclose(moved.pos, rot @ d)


@tt.requires_assets('SF')
def test_canine_fit_keeps_the_gap():
    """On the canine head each hair vertex keeps its distance out from the head along its ray
    (before smoothing), and the head's model-space bind is read in metres."""
    human = hair_fit.head_in_bone_space(vanilla(HUMAN_HEAD))
    canine_shape = hair_fit.load_shape(SNAPSHOT / 'Meshes' / CANINE_HEAD, snapshot_mesh)
    assert np.linalg.norm(canine_shape.translation) > 1.0      # the head's height, in metres
    canine = hair_fit.head_in_bone_space(canine_shape)
    # Both heads in C_Head space are about the same size and place.
    assert np.abs(np.median(np.linalg.norm(canine.verts, axis=1))
                  - np.median(np.linalg.norm(human.verts, axis=1))) < 0.03
    hair = vanilla(HAIR)
    pts = hair.to_bone(hair.positions)
    fit = hair_fit.fit_offsets(human, canine, pts, hair.tris, smooth=0)
    moved = pts + fit.offsets
    dirs = pts / np.linalg.norm(pts, axis=1, keepdims=True)
    gap_before = np.linalg.norm(pts, axis=1) - hair_fit.radial_hits(human, dirs)
    gap_after = np.linalg.norm(moved, axis=1) - hair_fit.radial_hits(canine, dirs)
    ok = ~np.isnan(gap_before) & ~np.isnan(gap_after)
    assert ok.mean() > 0.99
    assert np.abs(gap_after[ok] - gap_before[ok]).max() <= hair_fit.EPSILON + 1e-9   # the cutoff


# ----- cloth -------------------------------------------------------------------------------------

# A head capsule; two neck capsules and three skin bones; bone planes (182) and a head capsule.
CLOTH_HAIRS = [r'actors\human\mesh\hairs\bob\bob_f.nif', r'actors\human\mesh\hairs\shaggy\shaggy_m.nif',
               r'actors\human\mesh\hairs\choppy_bob\choppy_bob_f.nif']


def cloth_case(rel):
    from pyn import sf_cloth
    hair = vanilla(rel)
    blob = hair_fit.cloth_blob(hair.nif)
    return hair, blob, sf_cloth.read_model(blob)


def plane_values(model):
    """{(particle, bone): n.x + d} for every bone-plane record, x in the plane bone's frame."""
    from pyn import sf_cloth
    names = [b[0] for b in model.skeleton]
    binds = [np.array(m) for m in sf_cloth.bind_matrices(model.skeleton)]
    out = {}
    for sim in model.sims:
        for p in sim.planes:
            inv = np.linalg.inv(binds[names.index(p['bone'])])
            n, d = np.array(p['equation'][:3]), p['equation'][3]
            for i in p['particles']:
                x = inv[:3, :3] @ np.array(sim.positions[i]) + inv[:3, 3]
                out[(i, p['bone'])] = float(n @ x + d)
    return out


@tt.requires_assets('SF')
def test_cloth_unmoved_reads_back_the_same():
    """No offsets: the rebuilt cloth has the same particles, planes and capsules."""
    from pyn import sf_cloth
    for rel in CLOTH_HAIRS:
        hair, blob, before = cloth_case(rel)
        pts = hair.to_bone(hair.positions)
        fit = hair_fit.fit_cloth(blob, pts, np.zeros_like(pts))
        after = sf_cloth.read_model(fit.blob)
        assert fit.moved == 0.0
        for s1, s2 in zip(before.sims, after.sims):
            assert np.abs(np.array(s1.positions) - np.array(s2.positions)).max() < 1e-5, rel
        assert all(abs(old - new) < 1e-6 for _n, old, new in fit.capsules), fit.capsules
        a, b = plane_values(before), plane_values(after)
        assert set(a) == set(b) and all(abs(a[k] - b[k]) < 1e-5 for k in a), rel


@tt.requires_assets('SF')
def test_cloth_moves_with_the_hair():
    """Every particle moves by its nearest hair vertices' offset (here the same for all), keeps its
    distance from each bone plane, and no particle starts inside a capsule it was clear of."""
    from pyn import sf_cloth
    move = np.array([0.012, 0.003, -0.002])            # C_Head space, metres
    for rel in CLOTH_HAIRS:
        hair, blob, before = cloth_case(rel)
        pts = hair.to_bone(hair.positions)
        fit = hair_fit.fit_cloth(blob, pts, np.tile(move, (len(pts), 1)))
        after = sf_cloth.read_model(fit.blob)
        names = [b[0] for b in before.skeleton]
        head = np.array(sf_cloth.bind_matrices(before.skeleton)[names.index('C_Head')])
        want = head[:3, :3] @ move
        for s1, s2 in zip(before.sims, after.sims):
            got = np.array(s2.positions) - np.array(s1.positions)
            assert np.abs(got - want).max() < 1e-4, (rel, np.abs(got - want).max())
        a, b = plane_values(before), plane_values(after)
        assert set(a) == set(b) and all(abs(a[k] - b[k]) < 1e-4 for k in a), rel
        for col_b, col_a in zip(before.collidables, after.collidables):
            inv = np.linalg.inv(np.array(col_a.transform))
            for sim_b, sim_a in zip(before.sims, after.sims):
                if before.collidables.index(col_b) not in sim_b.collidable_ids:
                    continue
                bit = 1 << sim_b.collidable_ids.index(before.collidables.index(col_b))
                hit = [i for i, m in enumerate(sim_b.collision_masks) if m & bit]
                for pos, col in ((sim_b.positions, col_b), (sim_a.positions, col_a)):
                    local = np.array([pos[i] for i in hit]) @ inv[:3, :3].T + inv[:3, 3]
                    gap = hair_fit._segment_distance(local, np.array(col.params['start']),
                                                     np.array(col.params['end'])) - col.params['radius']
                    if col is col_b:
                        clear_before = gap
                    else:
                        assert (gap >= np.minimum(clear_before, 0) - 1e-5).all(), (rel, col.name)
