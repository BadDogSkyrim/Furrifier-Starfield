"""uv_transfer's Blender side, tested in Blender with PyNifly's test harness.
Moved here from PyNifly's tests/blender/test_starfield.py with the script. Run with
tests/blender/run_blender_tests.py."""
import importlib
import sys
from pathlib import Path

from tests.blender.common import *  # noqa: F401,F403 -- PyNifly's harness: bpy, TT, TTB, BD


def _uv_transfer():
    """FSFTools' uv_transfer.py, freshly loaded."""
    scripts = str(Path(__file__).resolve().parents[2])      # the FSFTools folder
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import uv_transfer
    return importlib.reload(uv_transfer)


def _uv_transfer_rig():
    """The vanilla hands and left eye as two parts, and a target made by joining copies of them,
    the way a crowd head is made. The target's hand UVs are turned 90 degrees and halved into
    the lower-left quarter; its eye UVs are quartered into the upper right. Returns
    (target, hands, eye, n_hand_faces)."""
    import numpy as np
    bpy.ops.import_scene.pynifly(filepath=TTB.test_file(r"tests\SF\meshes\hands_3rd_f.nif"))
    hands = TTB.find_shape("Hands_3rd_F:0")
    bpy.ops.object.select_all(action='DESELECT')
    bpy.context.view_layer.objects.active = None
    bpy.ops.import_scene.pynifly(filepath=TTB.test_file(r"tests\SF\meshes\lefteye.nif"))
    eye = TTB.find_shape("LeftEye:1")

    copies = []
    for o in (hands, eye):
        c = o.copy()
        c.data = o.data.copy()
        c.modifiers.clear()
        bpy.context.scene.collection.objects.link(c)
        copies.append(c)
    n_hand = len(copies[0].data.polygons)
    BD.ObjectSelect(copies, active=True)
    bpy.ops.object.join()
    target = bpy.context.view_layer.objects.active
    target.name = "CrowdTarget"

    me = target.data
    uv = np.empty(len(me.loops) * 2, np.float32)
    me.uv_layers.active.data.foreach_get('uv', uv)
    uv = uv.reshape(-1, 2)
    hand_loops = me.polygons[n_hand].loop_start   # hand faces come first: theirs was active
    h = uv[:hand_loops] - 0.5
    uv[:hand_loops] = np.stack([-h[:, 1], h[:, 0]], axis=1) * 0.5 + 0.25
    uv[hand_loops:] = uv[hand_loops:] * 0.25 + 0.7
    me.uv_layers.active.data.foreach_set('uv', uv.ravel())
    return target, hands, eye, n_hand


@TT.category('STARFIELD', 'SHADER')
def TEST_UV_TRANSFER_MAP():
    """uv_transfer maps each triangle of a joined mesh to the part triangle it came from.

    A crowd head is several parts (head, eyes, mouth, hands) joined into one mesh with one
    texture, its UVs repacked. The map ties each of its triangles to the part triangle it is a
    copy of, so the parts' textures can be copied in triangle by triangle. Faces deleted from
    the joined mesh are fine; a face that has moved off its part is an error, named so it can
    be fixed."""
    import bmesh
    import numpy as np
    U = _uv_transfer()
    target, hands, eye, n_hand = _uv_transfer_rig()

    # Faces removed from the joined mesh on purpose: fine.
    bm = bmesh.new()
    bm.from_mesh(target.data)
    bm.faces.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.faces[i] for i in range(5)], context='FACES')
    bm.to_mesh(target.data)
    bm.free()
    n_hand -= 5

    m = U.build_map(target, [hands, eye])
    target.data.calc_loop_triangles()
    assert TT.is_eq(len(m['part']), len(target.data.loop_triangles), "every triangle mapped")
    assert TT.is_eq(sorted(m['parts']), sorted([hands.name, eye.name]), "parts named")

    # Each triangle carries its part's own UVs: the target's are the part's, moved.
    hand_i = list(m['parts']).index(hands.name)
    is_hand = m['part'] == hand_i
    s = m['src_uv'][is_hand] - 0.5
    want = np.stack([-s[..., 1], s[..., 0]], axis=-1) * 0.5 + 0.25
    assert TT.is_true(np.allclose(m['tgt_uv'][is_hand], want, atol=1e-5),
                      "hand triangles carry their own UVs from the hands")
    s = m['src_uv'][~is_hand]
    assert TT.is_true(np.allclose(m['tgt_uv'][~is_hand], s * 0.25 + 0.7, atol=1e-5),
                      "eye triangles carry their own UVs from the eye")

    rep = U.map_report(m)
    assert TT.is_eq((rep[hands.name]['rotation'], round(rep[hands.name]['scale'], 3)), (90, 0.5),
                    "hands reported turned 90 degrees and halved")
    assert TT.is_eq((rep[eye.name]['rotation'], round(rep[eye.name]['scale'], 3)), (0, 0.25),
                    "eye reported quartered")

    # A vertex moved off its part: an error naming every face that uses it.
    v = target.data.polygons[0].vertices[0]
    target.data.vertices[v].co.z += 1.0
    users = {p.index for p in target.data.polygons if v in p.vertices}
    try:
        U.build_map(target, [hands, eye])
        assert False, "a moved vertex must stop the map"
    except U.MapError as e:
        assert TT.is_eq(set(e.faces), users, "the faces using the moved vertex are named")


@TT.category('STARFIELD', 'SHADER')
@TT.requires_assets('SF')
def TEST_UV_TRANSFER_PAINT():
    """uv_transfer paints a part's texture onto the joined mesh's UV layout.

    Colour lands where the triangle went. A normal map is also turned with its triangle: the
    hands' UVs are turned 90 degrees here, and a normal copied without turning would light
    them from the wrong side."""
    import numpy as np
    U = _uv_transfer()
    target, hands, eye, n_hand = _uv_transfer_rig()
    m = U.build_map(target, [hands, eye])

    def load(name):
        im = bpy.data.images.load(os.path.join(TT.SF_ASSETS, r"textures\actors\human\hands", name))
        im.colorspace_settings.name = 'Non-Color'
        w, h = im.size
        px = np.empty(w * h * 4, np.float32)
        im.pixels.foreach_get(px)
        return px.reshape(h, w, 4)[::-1, :, :3].copy()   # top row first, as files store it

    # The hands' quarter is 1024 pixels across at size 2048, as is the source: no shrinking.
    size = 2048
    is_hand = m['part'] == list(m['parts']).index(hands.name)
    tris = np.flatnonzero(is_hand)[::40]

    def compare(out, src, f):
        """Mean of f(painted pixel, source texel) at each test triangle's centre pixel."""
        errs = []
        for t in tris:
            T, S = m['tgt_uv'][t], m['src_uv'][t]
            c = T.mean(axis=0)
            ix, iy = int(c[0] * size), int((1 - c[1]) * size)
            p = np.array([(ix + 0.5) / size, 1 - (iy + 0.5) / size])
            A = np.column_stack([T[1] - T[0], T[2] - T[0]])
            if abs(np.linalg.det(A)) < 1e-12:
                continue
            b = np.linalg.solve(A, p - T[0])
            su = S[0] + b[0] * (S[1] - S[0]) + b[1] * (S[2] - S[0])
            h, w = src.shape[:2]
            sx, sy = int(su[0] % 1 * w), int((1 - su[1] % 1) * h)
            errs.append(f(out[iy, ix], src[sy, sx]))
        return float(np.mean(errs))

    color = load("defaulthandsf_sk1_color.png")
    out = U.paint(m, {hands.name: color, eye.name: (0.5, 0.5, 0.5)}, size=size)
    assert TT.is_eq(out.shape[:2], (size, size), "painted at the asked size")
    err = compare(out, color, lambda a, b: np.abs(a - b).mean())
    assert TT.is_true(err < 0.01, f"hand colour lands where its triangles went: {err:.3f}")

    normal = load("defaulthandsf_normal.png")
    out = U.paint(m, {hands.name: normal, eye.name: (0.5, 0.5, 1.0)}, size=size, normal=True)

    def xy(px):   # DirectX green: the stored green points down the texture
        return np.array([px[0] * 2 - 1, -(px[1] * 2 - 1)])

    turned = compare(out, normal, lambda a, b: np.abs(xy(a) - np.array([-xy(b)[1], xy(b)[0]])).mean())
    copied = compare(out, normal, lambda a, b: np.abs(xy(a) - xy(b)).mean())
    assert TT.is_true(turned < 0.01, f"normals turned with their triangles: {turned:.3f}")
    assert TT.is_true(copied > 3 * turned, f"CONTROL: a plain copy is wrong: {copied:.3f}")


@TT.category('STARFIELD', 'SHADER')
def TEST_UV_TRANSFER_SELECT_FAILED():
    """uv_transfer shows the faces that don't match by selecting them, and only them.

    It used to set just the faces' select flags. Edit Mode in vertex select mode shows vertex
    flags, so Bad Dog saw whatever vertices were selected before: a finger that had matched
    fine, and none of the faces that hadn't."""
    U = _uv_transfer()
    target, hands, eye, n_hand = _uv_transfer_rig()
    me = target.data
    me.vertices.foreach_set('select', [True] * len(me.vertices))   # a stale selection
    me.edges.foreach_set('select', [True] * len(me.edges))
    me.polygons.foreach_set('select', [True] * len(me.polygons))

    bad = [0, 7, n_hand + 3]
    U.select_faces(target, bad)
    want_v = {v for f in bad for v in me.polygons[f].vertices}
    want_e = {me.loops[li].edge_index for f in bad
              for li in range(me.polygons[f].loop_start,
                              me.polygons[f].loop_start + me.polygons[f].loop_total)}
    assert TT.is_eq({p.index for p in me.polygons if p.select}, set(bad), "only those faces")
    assert TT.is_eq({v.index for v in me.vertices if v.select}, want_v, "only their vertices")
    assert TT.is_eq({e.index for e in me.edges if e.select}, want_e, "only their edges")


@TT.category('STARFIELD', 'SHADER')
def TEST_UV_TRANSFER_MATERIAL_PARTS():
    """uv_transfer treats each material of a part object as a part of its own.

    Bad Dog joined the teeth into the head object; they keep their own material and texture.
    As one part, the teeth sampled the head texture and came out the colour of its empty
    background. A part object with several materials in use is now one part per material,
    named "<object>:<material>", each painted from its own texture."""
    import numpy as np
    U = _uv_transfer()
    target, hands, eye, n_hand = _uv_transfer_rig()

    # Give the source hands a second material on the left half of their UV layout. (By
    # region, not face by face: the two hands share their UVs, and faces painting the same
    # pixels share a texture.)
    second = bpy.data.materials.new("HandsSecond")
    hands.data.materials.append(second)
    first = hands.data.materials[0].name
    me = hands.data
    uv = np.empty(len(me.loops) * 2, np.float32)
    me.uv_layers.active.data.foreach_get('uv', uv)
    uv = uv.reshape(-1, 2)
    mi = [int(uv[p.loop_start:p.loop_start + p.loop_total, 0].mean() < 0.5) for p in me.polygons]
    me.polygons.foreach_set('material_index', mi)

    m = U.build_map(target, [hands, eye])
    names = [str(n) for n in m['parts']]
    want = sorted([f"{hands.name}:{first}", f"{hands.name}:HandsSecond", eye.name])
    assert TT.is_eq(sorted(names), want, "one part per material in use")

    # Each hand triangle belongs to the part of the material its source face has.
    target.data.calc_loop_triangles()
    tri_poly = np.empty(len(target.data.loop_triangles), np.int32)
    target.data.loop_triangles.foreach_get('polygon_index', tri_poly)
    is_hand = tri_poly < n_hand
    part_name = np.array(names)[m['part']]
    want_part = np.where(np.array(mi)[np.minimum(tri_poly, n_hand - 1)] == 1,
                         f"{hands.name}:HandsSecond", f"{hands.name}:{first}")
    assert TT.is_true((part_name[is_hand] == want_part[is_hand]).all(),
                      "hand triangles split by their source face's material")

    # Painted from its own texture: two flat colours land on their own triangles. Only
    # triangles big enough to own their centre pixel are measured.
    size = 2048
    out = U.paint(m, {f"{hands.name}:{first}": (1.0, 0.0, 0.0),
                      f"{hands.name}:HandsSecond": (0.0, 0.0, 1.0),
                      eye.name: (0.0, 1.0, 0.0)}, size=size, pad=0)
    T = m['tgt_uv'] * size
    area = np.abs((T[:, 1, 0] - T[:, 0, 0]) * (T[:, 2, 1] - T[:, 0, 1])
                  - (T[:, 2, 0] - T[:, 0, 0]) * (T[:, 1, 1] - T[:, 0, 1])) / 2
    hits = {'r': 0, 'b': 0, 'wrong': 0}
    for t in np.flatnonzero(is_hand & (area > 30)):
        c = m['tgt_uv'][t].mean(axis=0)
        px = out[int((1 - c[1]) * size), int(c[0] * size)]
        want_c = (0.0, 0.0, 1.0) if part_name[t].endswith("HandsSecond") else (1.0, 0.0, 0.0)
        if np.allclose(px[:3], want_c):
            hits['b' if want_c[2] else 'r'] += 1
        else:
            hits['wrong'] += 1
    assert TT.is_true(hits['r'] > 50 and hits['b'] > 50 and hits['wrong'] == 0,
                      f"each material painted with its own colour: {hits}")


@TT.category('STARFIELD', 'SHADER')
def TEST_UV_TRANSFER_PAINT_SCRIPT():
    """Mapping writes a PowerShell script beside the map: a paint command for each texture layer,
    every part's texture the file its material uses.

    The commands went only to Blender's system console, hidden on Windows, so Bad Dog typed the
    script by hand and misnamed a part in one of its four commands."""
    import shlex
    import tempfile
    import numpy as np
    U = _uv_transfer()
    target, hands, eye, n_hand = _uv_transfer_rig()
    work = tempfile.mkdtemp()

    def png(name, value):
        """A flat grey file. 16 bits: Blender's Python has no Pillow, which 8 bits needs."""
        path = os.path.join(work, name)
        U.save_image(np.full((16, 16, 1), value, np.float32), path, bits=16)
        return path

    def textured(obj, *layers):
        """The object's only material: a layer group per dict of files feeding its inputs,
        stamped with its layer index the way import does (0 the base, then the detail layers)."""
        mat = bpy.data.materials.new(obj.name + "Mat")
        mat.use_nodes = True
        nt = mat.node_tree
        for index, files in enumerate(layers):
            grp = bpy.data.node_groups.new(f"{obj.name}Layer{index}", 'ShaderNodeTree')
            for sock in files:
                grp.interface.new_socket(sock, in_out='INPUT', socket_type='NodeSocketColor')
            g = nt.nodes.new('ShaderNodeGroup')
            g.node_tree = grp
            g['pyn_sf_layer'] = index
            for sock, path in files.items():
                tex = nt.nodes.new('ShaderNodeTexImage')
                tex.image = bpy.data.images.load(path)
                nt.links.new(tex.outputs['Color'], g.inputs[sock])
        obj.data.materials.clear()
        obj.data.materials.append(mat)

    # The hands are skin: a base layer, then a detail layer with its own normal and AO, as the
    # fox head and hands have (pores, cheeks, lips). The base layer's maps are the ones to use.
    hand_files = {'AO': png('hand_ao.png', 0.9), 'Albedo': png('hand_color.png', 0.8),
                  'Normal Tex': png('hand_normal.png', 0.5), 'Roughness': png('hand_rough.png', 0.7)}
    textured(hands, hand_files, {'AO': png('pore_ao.png', 0.6), 'Normal Tex': png('pore_normal.png', 0.4)})
    textured(eye, {'Albedo': png('eye_color.png', 0.2)})
    m = U.build_map(target, [hands, eye])
    map_path = os.path.join(work, "CrowdTarget.uvmap.npz")
    U.write_map(map_path, m)

    def commands(path):
        """{layer: argv from the script name on}, as PowerShell would hand them over."""
        with open(path, encoding='utf-8') as f:
            text = f.read().replace("`\n", " ")
        out, layer = {}, None
        for line in text.splitlines():
            if line.startswith('# ') and line.endswith(':'):
                layer = line[2:-1]
            elif line.startswith('python '):
                argv = shlex.split(line)
                assert TT.is_eq(argv[2], 'paint', "a paint command")
                out[layer] = argv[1:]
        return out

    def parts_of(argv):
        return dict(argv[i + 1].split('=', 1) for i, a in enumerate(argv) if a == '--part')

    script = U.write_paint_script(map_path, target, [hands, eye])
    assert TT.is_eq(script, os.path.join(work, "CrowdTarget.paint.ps1"), "script beside the map")
    cmds = commands(script)
    assert TT.is_eq(list(cmds), ['AO', 'Color', 'Normal', 'Rough'], "the four layers, no metal")
    for layer, sock in (('AO', 'AO'), ('Color', 'Albedo'), ('Normal', 'Normal Tex'), ('Rough', 'Roughness')):
        got = parts_of(cmds[layer])
        assert TT.is_eq(os.path.normcase(got[hands.name]), os.path.normcase(hand_files[sock]),
                        f"{layer}: the hands' file from their material")
        assert TT.is_eq(('--normal' in cmds[layer]), layer == 'Normal', f"{layer}: --normal only on normals")
    assert TT.is_eq(parts_of(cmds['Color'])[eye.name], os.path.join(work, 'eye_color.png'), "eye colour")
    assert TT.is_true(parts_of(cmds['AO'])[eye.name].startswith('<'), "a missing texture is a placeholder")

    # All filled in, every command runs, with ordinary Python as PowerShell would, and paints
    # from the files named.
    textured(eye, {'AO': png('eye_ao.png', 0.3), 'Albedo': png('eye_color.png', 0.2),
                   'Normal Tex': png('eye_normal.png', 0.5), 'Roughness': png('eye_rough.png', 0.4),
                   'Metallic': png('eye_metal.png', 0.1)})
    cmds = commands(U.write_paint_script(map_path, target, [hands, eye]))
    assert TT.is_eq(list(cmds), ['AO', 'Color', 'Normal', 'Rough', 'Metal'],
                    "metal too, once a part has a metal map")
    assert TT.is_true(parts_of(cmds['Metal'])[hands.name].startswith('<'), "hands have no metal map")
    del cmds['Metal']
    import shutil
    import subprocess
    python = shutil.which('python')
    assert TT.is_true(python, "a system python to run the commands")
    for layer, argv in cmds.items():
        r = subprocess.run([python, *argv], capture_output=True, text=True)
        assert TT.is_eq(r.returncode, 0, f"{layer} command runs: {r.stderr[-400:]}")
        out = argv[argv.index('--out') + 1]
        assert TT.is_true(os.path.isfile(out), f"{layer} written")
        if layer == 'Color':
            img = bpy.data.images.load(out)
            px = np.empty(img.size[0] * img.size[1] * 4, np.float32)
            img.pixels.foreach_get(px)
            assert TT.is_true(np.isclose(px, 0.8, atol=0.01).any() and np.isclose(px, 0.2, atol=0.01).any(),
                              "colour painted from the hands' and eye's files")
