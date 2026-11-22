"""The tests of sf_racecheck, sf_tintbake, uv_transfer and sf_texconv, moved here from PyNifly's
pynifly_tests.py with the scripts. Each test keeps its PyNifly name and style (assert TT.is_*)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import fsftools  # noqa: F401,E402 -- puts pyn and esplib on the path
from pyn.pynifly import NifFile  # noqa: E402,F401

import tt as TT  # noqa: E402

FIXTURES = str(ROOT / 'tests' / 'fixtures' / 'pynifly')
OUT = str(ROOT / 'tests' / 'out')
os.makedirs(OUT, exist_ok=True)


def TEST_SF_TEXCONV_FACE_FORMATS():
    """sf_texconv writes face-customization textures the way vanilla writes them.

    Starfield authors everything under a face `chargen` tree uncompressed, top level and
    postblenddetails alike -- measured over all 748 vanilla .dds under
    textures/actors/human/faces/chargen, every one 1024x1024 with a single mip:

        _color / _derm_color  259   DX10 R8G8B8A8_UNORM_SRGB
        _normal                62   LEGACY 32bpp, DDPF_BUMPDUDV (signed)
        _ao / _rough / _mask  312   LEGACY 8bpp, DDPF_RGB
        *_mask_1                5   DX10 BC4_UNORM -- the only compressed files there

    We used to claim only `_color` and `_mask`, and only under postblenddetails, so a face
    normal went out as BC5_SNORM. BC5 drops Z and makes the shader reconstruct it, which an
    over-driven map cannot survive; vanilla's uncompressed signed format stores Z outright.

    Outside a face tree the ordinary BCn rules still apply -- that is the control, since the
    two tables are chosen by folder and it would be easy to make the face rule swallow
    everything.
    """
    import struct
    import tempfile
    import sf_texconv

    def spec_for(path):
        fmt, spec = sf_texconv.texture_format(path, 'BC7_UNORM_SRGB')
        return fmt, tuple(spec.args), spec.vanilla_header, spec.dx10

    FACE = r'Data\Textures\Actors\FSFCanine\faces\chargen'
    PBD = FACE + r'\postblenddetails\dermaesthetic'
    LOOSE = r'Data\Textures\Actors\FSFCanine\body'

    one_mip = ('-m', '1')
    # (path, expected format, legacy-or-dx10) -- the whole chargen tree behaves alike.
    for folder in (FACE, PBD):
        assert TT.is_eq(spec_for(folder + r'\x_normal.png'),
                        ('R8G8B8A8_SNORM', one_mip, True, False),
                        f"face normal in {os.path.basename(folder)}")
        assert TT.is_eq(spec_for(folder + r'\x_color.png'),
                        ('R8G8B8A8_UNORM_SRGB', one_mip, True, True),
                        f"face colour in {os.path.basename(folder)}")
        for suffix in ('_ao', '_rough', '_metal', '_mask'):
            assert TT.is_eq(spec_for(folder + rf'\x{suffix}.png'),
                            ('R8_UNORM', one_mip, True, False),
                            f"face {suffix} in {os.path.basename(folder)}")

    # CONTROL: the same suffixes outside a face tree keep the compressed rules.
    assert TT.is_eq(spec_for(LOOSE + r'\x_normal.png'),
                    ('BC5_SNORM', (), False, True), "body normal stays BC5")
    assert TT.is_eq(spec_for(LOOSE + r'\x_ao.png'),
                    ('BC4_UNORM', (), False, True), "body ao stays BC4")
    assert TT.is_eq(spec_for(LOOSE + r'\x_metal.png'),
                    ('BC4_UNORM', (), False, True), "body metal is BC4, like rough")
    assert TT.is_eq(spec_for(LOOSE + r'\x_color.png'),
                    ('BC7_UNORM_SRGB', (), False, True), "body colour uses --color-format")
    # The rest of a texture set, in the format vanilla uses for each (census of 00StarfieldAssets:
    # _opacity 2756 of 2762 BC4, the others unanimous).
    for suffix, fmt in (('_opacity', 'BC4_UNORM'), ('_transmissive', 'BC4_UNORM'),
                        ('_height', 'BC4_UNORM'), ('_id', 'BC4_UNORM'),
                        ('_emissive', 'BC1_UNORM_SRGB')):
        assert TT.is_eq(spec_for(LOOSE + rf'\x{suffix}.png'), (fmt, (), False, True),
                        f"body {suffix} is {fmt}")
    # A dermaesthetic layer kept outside a face tree is still uncompressed: the game
    # insists on that one wherever it lives.
    assert TT.is_eq(spec_for(LOOSE + r'\x_derm_color.png'),
                    ('R8G8B8A8_UNORM_SRGB', one_mip, True, True), "loose derm stays raw")

    # --- the header rewrite for the signed 32bpp face normal --------------------------
    # texconv already writes DDPF_BUMPDUDV and the right channel masks; what differs from
    # vanilla is the same four fields the other formats need fixing.
    head = bytearray(148)
    head[0:4] = b'DDS '
    struct.pack_into('<I', head, 4, 124)
    struct.pack_into('<I', head, 8, 0x2100F)      # texconv's dwFlags
    struct.pack_into('<2I', head, 12, 256, 256)   # height, width
    struct.pack_into('<I', head, 20, 1024)        # texconv writes one row's pitch
    struct.pack_into('<I', head, 24, 1)           # depth
    struct.pack_into('<I', head, 28, 1)           # mipCount
    struct.pack_into('<I', head, 76, 32)          # pixelformat size
    struct.pack_into('<I', head, 80, 0x80000)     # DDPF_BUMPDUDV
    struct.pack_into('<I', head, 88, 32)          # bit count
    struct.pack_into('<4I', head, 92, 0xFF, 0xFF00, 0xFF0000, 0xFF000000)
    struct.pack_into('<I', head, 108, 0x1000)     # texconv's caps

    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, 'probe.dds')
        with open(p, 'wb') as f:
            f.write(head)
            f.write(b'\0' * (256 * 256 * 4))
        assert TT.is_eq(sf_texconv.match_vanilla_header(p), None,
                        "signed 32bpp header is handled, not skipped")
        got = open(p, 'rb').read(148)

    assert TT.is_eq(struct.unpack_from('<I', got, 8)[0], 0xA1007, "dwFlags becomes vanilla's")
    assert TT.is_eq(struct.unpack_from('<I', got, 20)[0], 256 * 256 * 4,
                    "size field becomes the whole image")
    assert TT.is_eq(struct.unpack_from('<I', got, 24)[0], 0, "depth becomes 0")
    assert TT.is_eq(struct.unpack_from('<I', got, 108)[0], 0x401008, "caps become vanilla's")
    # The pixel format must NOT be rewritten to DDPF_RGB the way the 8bpp masks are --
    # that would throw away the "these values are signed" marker.
    assert TT.is_eq(struct.unpack_from('<I', got, 80)[0], 0x80000, "DDPF_BUMPDUDV is kept")

    # --- a rule change has to invalidate the cache ------------------------------------
    # Without this the fix above lands on nothing: every existing face texture is newer
    # than its .png, so a mtime-only check skips them all and they stay BC5 forever.
    assert TT.is_eq(
        sf_texconv.wanted_encoding('BC5_SNORM', sf_texconv.SUFFIX_FORMATS['_normal']),
        ('dx10', 84), "what the old BC5 normal looks like on disk")
    assert TT.is_eq(
        sf_texconv.wanted_encoding('R8G8B8A8_SNORM', sf_texconv.FACE_FORMATS['_normal']),
        ('legacy', 32), "what a face normal should look like instead")
    # An arbitrary --color-format we can't name falls back to the mtime test rather than
    # re-converting the world on every run.
    assert TT.is_eq(
        sf_texconv.wanted_encoding('SOME_FUTURE_FORMAT', sf_texconv.SUFFIX_FORMATS['_color']),
        None, "an unknown format is not second-guessed")


@TT.requires_assets('SF')
def TEST_SF_RACECHECK_SHADER_SETTINGS():
    """sf_racecheck catches a shader model whose settings component is missing -- through
    the material's INHERITANCE CHAIN, not from the file alone.

    A few shader models are driven by a settings component that carries their whole reason
    to exist: `Eye1Layer` gets the iris parallax depths from `EyeSettingsComponent`. Without
    it the material still parses, still resolves every texture, and still previews correctly
    in the Creation Kit, but the part is invisible in game. That cost a full debugging
    session on the fox eyes.

    The pairings are measured over every vanilla `.mat` and each is exceptionless:

        Eye1Layer   -> EyeSettingsComponent     8/8
        1LayerMouth -> MouthSettingsComponent   2/2
        Hair1Layer  -> HairSettingsComponent   11/11

    The check has to follow inheritance or it is worse than useless: only 0.3% of authored
    materials name their own shader model, so reading the local file alone misses the model
    on nearly everything -- and would then condemn a derived material that correctly
    inherits both halves. Both directions are asserted here:

      * vanilla `left_eye.mat` inherits Eye1Layer from its template and must stay SILENT,
        even though the word `Eye1Layer` appears nowhere in it;
      * a FLAT material naming Eye1Layer with no settings -- exactly the shape PyNifly used
        to export -- must FAIL.
    """
    import json
    import tempfile
    import sf_racecheck

    faces = os.path.join(TT.SF_ASSETS, 'materials', 'Actors', 'Human', 'Faces')
    CASES = [
        (os.path.join(faces, 'left_eye.mat'), 'Eye1Layer', 'EyeSettingsComponent'),
        (os.path.join(faces, 'Teeth', 'NNTeeth.mat'), '1LayerMouth', 'MouthSettingsComponent'),
    ]

    def findings(mat_rel, data_dir):
        rep = sf_racecheck.Report()
        sf_racecheck.check_material(rep, [data_dir], mat_rel, None, set())
        return rep

    def said(rep, level, word):
        return [m for lv, _area, m, _d in rep.findings if lv == level and word in m]

    for src, model, comp in CASES:
        assert TT.is_eq(os.path.exists(src), True, f"authored fixture is there: {src}")
        doc = json.load(open(src, encoding='utf-8'))

        # The authored file does NOT name its shader model -- the template does. This is
        # what the flattened CDB dump used to hide.
        assert TT.is_eq(
            any(c['Type'].endswith('ShaderModelComponent')
                for c in doc['Objects'][0].get('Components', [])),
            False, f"{os.path.basename(src)} inherits its shader model")

        # CONTROL: the real material in its real tree, where the chain resolves.
        rel = os.path.relpath(src, TT.SF_ASSETS)
        assert TT.is_eq(said(findings(rel, TT.SF_ASSETS), sf_racecheck.FAIL, comp), [],
                        f"a correct {model} material is not flagged")

        # The failure case: flat, self-declared model, settings dropped.
        with tempfile.TemporaryDirectory() as d:
            probe = os.path.join('materials', 'probe.mat')
            os.makedirs(os.path.join(d, 'materials'))
            flat = {"Version": 1, "Objects": [{"Components": [
                {"Type": "BSComponentDB::CTName", "Index": 0, "Data": {"Name": "probe"}},
                {"Type": "BSMaterial::ShaderModelComponent", "Index": 0,
                 "Data": {"FileName": model}}]}]}
            with open(os.path.join(d, probe), 'w', encoding='utf-8') as f:
                json.dump(flat, f)
            hits = said(findings(probe, d), sf_racecheck.FAIL, comp)
            assert TT.is_eq(len(hits), 1, f"flat {model} with no {comp} is a FAIL")
            assert TT.is_eq(model in hits[0], True, "the message names the shader model")

    # CONTROL: a model that needs no settings block is never flagged, or every ordinary
    # material in the mod turns into a failure.
    with tempfile.TemporaryDirectory() as d:
        probe = os.path.join('materials', 'plain.mat')
        os.makedirs(os.path.join(d, 'materials'))
        with open(os.path.join(d, probe), 'w', encoding='utf-8') as f:
            json.dump({"Version": 1, "Objects": [{"Components": [
                {"Type": "BSMaterial::ShaderModelComponent",
                 "Index": 0, "Data": {"FileName": "BaseMaterial"}}]}]}, f)
        assert TT.is_eq(said(findings(probe, d), sf_racecheck.FAIL, 'SettingsComponent'), [],
                        "a model with no required settings block is left alone")


@TT.requires_assets('SF')
def TEST_SF_RACECHECK_SKIN_VERTEX_ALPHA():
    """sf_racecheck fails a skin material that takes its opacity from vertex colour.

    On a skin shader model, AlphaSettings `Blender { UseVertexColor true }` makes the whole
    shape invisible on a character -- even where vertex alpha is 1.0 -- while the Creation
    Kit's armor preview still draws it. Texture opacity on the same material works. Found in
    game on the fox race's body and tail (2026-10-12), twice, and vanilla agrees: no skin
    material has any alpha component, and vertex-colour opacity appears only on standard and
    decal models.

    A body material inherits its shader model, so the check follows the Import chain: the
    probe here is shaped like the fox body, deriving from vanilla `Naked_M_Body.mat`
    (BodySkin2Layer) and adding only an alpha component.
    """
    import json
    import tempfile
    import sf_racecheck

    body = r'Data\MATERIALS\Actors\Human\Naked_Body\Male\Naked_M_Body.mat'

    def alpha(use_vertex_color):
        return {"Type": "BSMaterial::AlphaSettingsComponent", "Index": 0, "Data": {
            "HasOpacity": "true", "AlphaTestThreshold": "0.5",
            "Blender": {"Type": "BSMaterial::AlphaBlenderSettings",
                        "Data": {"UseVertexColor": use_vertex_color,
                                 "VertexColorChannel": "Alpha"}}}}

    def fails(doc):
        with tempfile.TemporaryDirectory() as d:
            probe = os.path.join('materials', 'probe.mat')
            os.makedirs(os.path.join(d, 'materials'))
            with open(os.path.join(d, probe), 'w', encoding='utf-8') as f:
                json.dump(doc, f)
            rep = sf_racecheck.Report()
            sf_racecheck.check_material(rep, [d, TT.SF_ASSETS], probe, None, set())
            return [m for lv, _a, m, _d in rep.findings
                    if lv == sf_racecheck.FAIL and 'vertex' in m.lower()]

    def derived(use_vertex_color):
        return {"Version": 1, "Import": [body], "Objects": [{"Parent": body, "Components": [
            {"Type": "BSComponentDB::CTName", "Index": 0, "Data": {"Name": "probe"}},
            alpha(use_vertex_color)]}]}

    hits = fails(derived("true"))
    assert TT.is_eq(len(hits), 1, "skin material with vertex-colour opacity is a FAIL")
    assert TT.is_eq('BodySkin2Layer' in hits[0], True, "the message names the inherited model")

    # CONTROL: texture opacity on the same skin material works in game.
    assert TT.is_eq(fails(derived("false")), [], "texture opacity on skin is fine")

    # CONTROL: vertex-colour opacity is how vanilla decals work.
    decal = {"Version": 1, "Objects": [{"Components": [
        {"Type": "BSMaterial::ShaderModelComponent", "Index": 0,
         "Data": {"FileName": "1LayerStandard"}}, alpha("true")]}]}
    assert TT.is_eq(fails(decal), [], "vertex-colour opacity on a standard model is fine")


@TT.requires_assets('SF')
def TEST_SF_RACECHECK_MATERIAL_EXISTS():
    """sf_racecheck fails a body part whose material exists nowhere.

    A material that isn't a loose file used to get only an info line ("compiled into the
    .cdb?"), so a misnamed material on the hands or body passed silently. Vanilla materials
    really are compiled into the game's materialsbeta.cdb, so the check looks there too:

      * a vanilla material in the .cdb but not loose is fine -- no FAIL;
      * a material in neither is a FAIL;
      * with no .cdb to consult, a missing loose file can't be judged -- a WARN.
    """
    import tempfile
    import sf_racecheck

    cdb_src = os.path.join(TT.SF_ASSETS, 'materials', 'materialsbeta.cdb')
    assert TT.is_eq(os.path.exists(cdb_src), True, "vanilla materialsbeta.cdb is unpacked")
    vanilla = r'Materials\Actors\Human\Faces\left_eye.mat'
    nosuch = r'Materials\FSFTest\Hands\NoSuchHands.mat'

    def levels(data_dir, mat_rel):
        rep = sf_racecheck.Report()
        sf_racecheck.check_material(rep, [data_dir], mat_rel, None, set())
        return {lv for lv, _area, _m, _d in rep.findings}

    with tempfile.TemporaryDirectory() as tmp:
        # No loose materials here at all -- only the compiled database.
        os.makedirs(os.path.join(tmp, 'materials'))
        try:
            os.link(cdb_src, os.path.join(tmp, 'materials', 'materialsbeta.cdb'))
        except OSError:
            import shutil
            shutil.copy(cdb_src, os.path.join(tmp, 'materials', 'materialsbeta.cdb'))

        assert TT.is_eq(sf_racecheck.FAIL in levels(tmp, vanilla), False,
                        "a vanilla material compiled into the .cdb is not flagged")
        assert TT.is_eq(sf_racecheck.FAIL in levels(tmp, nosuch), True,
                        "a material that exists nowhere is a FAIL")

    with tempfile.TemporaryDirectory() as empty:
        found = levels(empty, nosuch)
        assert TT.is_eq((sf_racecheck.FAIL in found, sf_racecheck.WARN in found), (False, True),
                        "with no .cdb to consult, a missing loose material is a WARN")


@TT.requires_assets('SF')
def TEST_SF_RACECHECK_SKINNED():
    """sf_racecheck fails a head-part or body NIF with an unskinned shape.

    A Starfield head part is placed by its skin -- an eye rides its eye bone. Exported with
    no armature binding, the shape gets its position baked into its transform and no bones,
    and the game has nothing to attach it with: the fox female right eye simply didn't show.
    Every one of the 427 vanilla head-part and skin-addon NIFs is fully skinned, so an
    unskinned shape is always a mistake here.
    """
    import sf_racecheck

    data = [TT.SF_ASSETS]
    skinned = r"meshes\actors\human\characterassets\female\righteye.nif"
    unskinned = r"meshes\setdressing\outpost\harvesterflora\harvesterflora02\outpostharvesterflora01_dirt02.nif"

    def fails(rel):
        rep = sf_racecheck.Report()
        reader = sf_racecheck.make_nif_reader(None)
        reader(rep, data, os.path.join(TT.SF_ASSETS, rel), rel)
        return [m for lv, _area, m, _d in rep.findings if lv == sf_racecheck.FAIL and 'skinned' in m]

    assert TT.is_eq(fails(skinned), [], "a vanilla eye, skinned to its eye bone, passes")
    assert TT.is_eq(len(fails(unskinned)), 1, "an unskinned shape is a FAIL")


def TEST_SF_RACECHECK_SKIN_FLAG_SLOT():
    """sf_racecheck fails a skin addon whose skin flag doesn't match its slot.

    The skin-tone swap picks the texture by the addon's record flag: Is Skin (0x80) gets the
    race's body tone (BSTT), Is Skin Hands (0x100) the hands tone (HSTT). A fox tail flagged
    Is Skin Hands took the hands texture at body-texture UVs and showed the wrong colour in
    game; flagged Is Skin, like Felid's tails, it takes the body tone.

    Vanilla pairs them without exception: all 3 Is Skin Hands addons are in the hands slot
    (`BO64` bit 6), and none of the 14 Is Skin addons are.
    """
    import sf_racecheck as R

    def fails(flags, bo64):
        rep = R.Report()
        R.check_skin_flag_slot(rep, 'probe', flags, bo64)
        return [m for lv, _a, m, _d in rep.findings if lv == R.FAIL]

    # The fox tail as it was: Is Skin Hands, slots 15 and 31.
    assert TT.is_eq(len(fails(R.ARMA_IS_SKIN_HANDS, 0x80008000)), 1,
                    "a tail flagged Is Skin Hands is a FAIL")
    # A hands addon flagged as body skin would take the body texture.
    assert TT.is_eq(len(fails(R.ARMA_IS_SKIN, 0x40)), 1, "hands flagged Is Skin is a FAIL")
    # CONTROLS, as vanilla flags them: AA_Naked_Hands, AA_Naked_Body, a clothing skin part.
    assert TT.is_eq(fails(R.ARMA_IS_SKIN_HANDS, 0x40), [], "vanilla hands pass")
    assert TT.is_eq(fails(R.ARMA_IS_SKIN, 0x8), [], "vanilla body passes")
    assert TT.is_eq(fails(R.ARMA_IS_SKIN, 0x400), [], "a clothing skin part passes")
    assert TT.is_eq(fails(0, 0x40), [], "an unflagged addon isn't this check's business")


def TEST_SF_RACECHECK_VANILLA_MISMATCH():
    """sf_racecheck warns, not fails, on oddities a mod can't fix or does on purpose.

    - A body morph whose vertex count differs from its model is a FAIL when either is the mod's
      own: a remeshed body pointing at vanilla's morph. When both are in vanilla's human tree
      it's a WARN.
      FSFCanine_AA_Naked_Tail names vanilla's Naked_M_1st.nif (1582 verts) as its 1st person
      model, with vanilla's male chargen body morph (6464): Bethesda's pairing, not the mod's.
    - A head part with no MODL is a WARN: FSFCanine_MF_Hair_None has none on purpose, to blank
      the hair (Bad Dog, 2026-10-19)."""
    import tempfile
    import sf_racecheck as R

    class Sub:
        def __init__(self, s):
            self.s = s

        def get_string(self):
            return self.s

    class Rec:
        def __init__(self, edid, **subs):
            self.editor_id, self.subs = edid, subs

        def get_subrecord(self, sig):
            return Sub(self.subs[sig]) if sig in self.subs else None

    class Morph:
        num_vertices = 6464

    def levels(rep):
        return [lv for lv, _a, _m, _d in rep.findings]

    with tempfile.TemporaryDirectory() as d:
        for m in ('Meshes/Morphs/Human/Male/Chargen/Body', 'Meshes/Morphs/RC/Male/Body'):
            os.makedirs(os.path.join(d, m))
            open(os.path.join(d, m, 'morph.dat'), 'wb').close()
        saved = R.model_mesh_verts, R.MorphFile
        R.model_mesh_verts = lambda data, rel: 1582
        R.MorphFile = type('MF', (), {'from_file': staticmethod(lambda f: Morph())})
        try:
            def morph_check(model, morph_dir):
                rep = R.Report()
                R.check_body_morph(rep, [d], 'probe', 'male 1st person',
                                   Rec('m', TCMP=morph_dir), model)
                return levels(rep)

            assert TT.is_eq(morph_check('Actors\\Human\\Mesh\\Naked_Body\\Naked_M_1st.nif',
                                        'Meshes\\Morphs\\Human\\Male\\Chargen\\Body'),
                            [R.WARN], "vanilla model + vanilla morph is a WARN")
            assert TT.is_eq(morph_check('Actors\\RC\\Mesh\\Body_M.nif',
                                        'Meshes\\Morphs\\Human\\Male\\Chargen\\Body'),
                            [R.FAIL], "own model + vanilla morph is a FAIL")
            assert TT.is_eq(morph_check('Actors\\Human\\Mesh\\Naked_Body\\Naked_M_1st.nif',
                                        'Meshes\\Morphs\\RC\\Male\\Body'),
                            [R.FAIL], "vanilla model + own morph is a FAIL")
        finally:
            R.model_mesh_verts, R.MorphFile = saved

    rep = R.Report()
    R.check_head_nif(rep, 'unused', Rec('FSFCanine_MF_Hair_None'), None)
    assert TT.is_eq(levels(rep), [R.WARN], "a head part with no MODL is a WARN")


def TEST_SF_RACECHECK_ARMOR_RACE_FIT():
    """sf_racecheck passes a skin addon that fits the race only through its Armor Race.

    FSFFoxCrowdRace's skin carries vanilla AA_Clothes_Crowd_Sweater_01_NOTPLAYABLE, which lists
    HumanCrowdRace and MannequinRace but not the fox race. HumanCrowdRace is the fox race's Armor
    Race, and the crowd foxes render in game wearing that sweater (2026-10-18), so the match
    through the Armor Race is enough. An addon that fits neither is still a FAIL."""
    import sf_racecheck as R

    class Race:
        def __init__(self, edid):
            self.editor_id = self.form_id = edid

    class Arma:
        editor_id, flags = 'AA_Clothes_Crowd_Sweater_01_NOTPLAYABLE', 0

        def get_subrecord(self, sig):
            return None

    fox, crowd, mannequin = Race('FSFFoxCrowdRace'), Race('HumanCrowdRace'), Race('MannequinRace')

    def fails(armor_race, fits):
        saved = R.arma_races
        R.arma_races = lambda arma, plugins: fits
        try:
            rep = R.Report()
            R.check_body_addon(rep, [], fox, Arma(), armor_race, None, None, None, sexes=())
        finally:
            R.arma_races = saved
        return [m for lv, _a, m, _d in rep.findings if lv == R.FAIL]

    assert TT.is_eq(fails(crowd, [crowd, mannequin]), [], "fits through the Armor Race: passes")
    assert TT.is_eq(fails(crowd, [fox]), [], "fits the race itself: passes")
    assert TT.is_eq(len(fails(crowd, [mannequin])), 1, "fits neither: FAIL")
    assert TT.is_eq(len(fails(None, [crowd])), 1, "no Armor Race, not the race: FAIL")


def TEST_SF_RACECHECK_CROWD_RACE():
    """sf_racecheck doesn't hold a crowd race to the chargen rules.

    A crowd race is HumanCrowdRace, or a race whose Armor Race is HumanCrowdRace (FSFFoxCrowdRace).
    Its head, eyes and arms are one mesh carried by the head armor in the NPC's outfit, so it has
    no head parts, no separate hands, no tint layers, skin tones or face textures. Vanilla's own
    crowd skin, Skin_Crowd_Base_Body_NOTPLAYABLE, has a single addon (the sweater)."""
    import sf_racecheck as R

    class Sub:
        def get_form_id(self):
            return type('F', (), {'value': 1})()

    class Rec:
        def __init__(self, edid, subs=()):
            self.editor_id, self.form_id, self.subs, self.plugin = edid, edid, set(subs), None

        def get_subrecord(self, sig):
            return Sub() if sig in self.subs else None

        def get_subrecords(self, sig):
            return [Sub()] if sig in self.subs else []

    crowd = Rec('HumanCrowdRace')
    fox_crowd, fox, human = Rec('FSFFoxCrowdRace', ['RNAM', 'WNAM']), Rec('FSFFoxRace', ['RNAM']), \
        Rec('HumanRace')
    skin = Rec('FSFox_Skin_Crowd_Base_Body_NOTPLAYABLE', ['MODL'])

    class Plugins:
        def resolve_reference(self, rec, sig):
            return {('FSFFoxCrowdRace', 'RNAM'): crowd, ('FSFFoxRace', 'RNAM'): human,
                    ('FSFFoxCrowdRace', 'WNAM'): skin}.get((rec.editor_id, sig))

        def resolve_form_id(self, fid, plugin):
            return None

    plugins = Plugins()
    assert TT.is_true(R.is_crowd_race(crowd, plugins), "HumanCrowdRace is a crowd race")
    assert TT.is_true(R.is_crowd_race(fox_crowd, plugins), "Armor Race HumanCrowdRace: crowd")
    assert TT.is_true(not R.is_crowd_race(fox, plugins), "Armor Race HumanRace: not a crowd")
    assert TT.is_true(not R.is_crowd_race(human, plugins), "HumanRace: not a crowd")

    def one_addon_warnings(crowd_race):
        rep = R.Report()
        R.check_body(rep, [], fox_crowd, plugins, None, None, crowd=crowd_race)
        return [m for lv, _a, m, _d in rep.findings if lv == R.WARN and 'only 1' in m]

    assert TT.is_eq(len(one_addon_warnings(False)), 1, "a chargen race's one-addon skin warns")
    assert TT.is_eq(one_addon_warnings(True), [], "a crowd race's one-addon skin is normal")


def TEST_SF_RACECHECK_SPACESUIT_KEYWORD():
    """A race shows spacesuits only if it is HumanRace, HumanCorpseRace or ChildRace, or carries
    the keyword RaceAllowShowSpacesuit (Starfield.esm's ActorShouldShowSpacesuit condition). A
    custom race without it leaves every NPC dressed by a space outfit naked, and the player's suit
    invisible -- FSFFoxRace, found in game 2026-11-10. Crowd races don't wear spacesuits."""
    import sf_racecheck as R

    class Kw:
        def __init__(self, edid):
            self.editor_id = edid

    class Kwda:
        def __init__(self, ids):
            self.ids = ids

        def get_form_id_array(self):
            return self.ids

    class Race:
        def __init__(self, edid, keywords):
            self.editor_id, self.plugin = edid, None
            self.kwda = Kwda(keywords) if keywords is not None else None

        def get_subrecord(self, sig):
            return self.kwda if sig == 'KWDA' else None

    class Plugins:
        def resolve_form_id(self, fid, plugin):
            return Kw(fid) if fid != 'unresolvable' else None

    def fails(race, crowd=False):
        rep = R.Report()
        R.check_spacesuit(rep, race, Plugins(), crowd)
        return [m for lv, a, m, _d in rep.findings if lv == R.FAIL and a == 'spacesuit']

    assert TT.is_eq(len(fails(Race('FSFFoxRace', ['ActorTypeNPC', 'ActorTypeHuman']))), 1,
                    "a custom race without the keyword fails")
    assert TT.is_eq(len(fails(Race('FSFFoxRace', None))), 1, "no keywords at all fails")
    assert TT.is_eq(len(fails(Race('FSFFoxRace', ['unresolvable']))), 1,
                    "an unresolvable keyword is not the spacesuit one")
    assert TT.is_eq(fails(Race('FSFFoxRace', ['ActorTypeNPC', 'RaceAllowShowSpacesuit'])), [],
                    "the keyword passes")
    assert TT.is_eq(fails(Race('HumanRace', [])), [], "HumanRace passes by name")
    assert TT.is_eq(fails(Race('FSFFoxCrowdRace', []), crowd=True), [],
                    "crowd races aren't held to it")


def TEST_SF_RACECHECK_CROWD_HEADS():
    """sf_racecheck follows a crowd race's heads: NPC -> outfit -> leveled lists -> head armor ->
    addons -> NIFs, and checks their meshes, materials, textures and _faceBones companions.

    Found on the female fox crowd (2026-10-19): the heads named CrowdHeadF_normal/_rough/_ao.dds,
    which existed only as .png (no normal map in game), and the _faceBones companion was a
    chargen face rig with the arms weighted to the biceps only (no hands in game). The game
    draws a crowd head from its companion, which must be a plain copy of the head.

    A missing texture is a FAIL when it is neither loose nor in any BA2 of the data folders;
    one in an archive is vanilla's and fine. Problems shared by many heads (forty variants on one
    material set) are reported once, with the count."""
    import shutil
    import struct
    import tempfile
    import sf_racecheck as R
    from esplib import Plugin

    CROWD = 'Actors/RC_Crowd'
    fixture = FIXTURES

    def put(d, rel, data=b''):
        path = os.path.join(d, *rel.replace('\\', '/').split('/'))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, 'wb').write(data)
        return path

    def fake_ba2(path, names):
        table = b''.join(struct.pack('<H', len(n)) + n.encode() for n in names)
        open(path, 'wb').write(struct.pack('<4sI4sIQ', b'BTDX', 2, b'GNRL', len(names), 24) + table)

    def u32(v):
        return v.to_bytes(4, 'little')

    def fid(rec):
        return rec.form_id.value

    with tempfile.TemporaryDirectory() as d:
        crowd_nif = os.path.join(fixture, 'crowd_head_af_md1.nif')
        for name, src in (('Head_A', crowd_nif), ('Head_A_faceBones', crowd_nif),
                          ('Head_B', crowd_nif), ('Head_B_faceBones', 'felidmalehead.nif'),
                          ('Tail', crowd_nif)):
            dst = put(d, f'meshes/{CROWD}/{name}.nif')
            shutil.copyfile(src if os.sep in src else os.path.join(fixture, src), dst)
        for mp in NifFile(crowd_nif).shapes[0].mesh_paths():
            put(d, f'geometries/{mp}.mesh')
        tex = 'Data\\\\Textures\\\\Actors\\\\RC\\\\crowd\\\\'
        put(d, 'Materials/Actors/Human/Crowd/Crowd_af_md1.mat', (
            '{"Objects": [{"Components": ['
            '{"Type": "BSMaterial::MRTextureFile", "Data": {"FileName": "' + tex + 'head_color.dds"}},'
            '{"Type": "BSMaterial::MRTextureFile", "Data": {"FileName": "' + tex + 'head_normal.dds"}},'
            '{"Type": "BSMaterial::MRTextureFile", "Data": {"FileName": '
            '"Data\\\\Textures\\\\Actors\\\\Human\\\\crowd\\\\vanilla_metal.dds"}}]}]}').encode())
        put(d, 'Textures/Actors/RC/crowd/head_color.dds')
        fake_ba2(os.path.join(d, 'Starfield - Textures01.ba2'),
                 ['textures/actors/human/crowd/vanilla_metal.dds'])

        p = Plugin.new_plugin(os.path.join(d, 'RCCrowd.esm'), masters=[], game='fo4', is_esm=True)

        def rec(sig, edid, *subs):
            r = p.new_record(sig, edid)
            for s, data in subs:
                r.add_subrecord(s, data)
            return r

        def model(rel):
            return (rel.replace('/', '\\') + '\0').encode()

        head, tail = ('BO64', (1 << 2).to_bytes(8, 'little')), ('BO64', (1 << 15).to_bytes(8, 'little'))
        aa_a = rec('ARMA', 'AA_Head_A', head, ('MOD2', model(f'{CROWD}/Head_A.nif')),
                   ('MOD3', model(f'{CROWD}/Head_F.nif')))
        aa_b = rec('ARMA', 'AA_Head_B', head, ('MOD2', model(f'{CROWD}/Head_B.nif')))
        aa_t = rec('ARMA', 'AA_Tail', tail, ('MOD2', model(f'{CROWD}/Tail.nif')))
        arm_a = rec('ARMO', 'Head_A', head, ('MODL', u32(fid(aa_a))), ('MODL', u32(fid(aa_t))))
        arm_b = rec('ARMO', 'Head_B', head, ('MODL', u32(fid(aa_b))))
        sub = rec('LVLI', 'LL_Sub', ('LVLO', u32(1) + u32(fid(arm_b)) + u32(1)))
        heads = rec('LVLI', 'LL_Heads', ('LVLO', u32(1) + u32(fid(arm_a)) + u32(1)),
                    ('LVLO', u32(1) + u32(fid(sub)) + u32(1)))
        outfit = rec('OTFT', 'Outfit', ('INAM', u32(fid(heads))))
        rec('NPC_', 'Npc_M', ('ACBS', bytes(16)), ('DOFT', u32(fid(outfit))))
        rec('NPC_', 'Npc_F', ('ACBS', b'\1' + bytes(15)), ('DOFT', u32(fid(outfit))))
        p.save_as(os.path.join(d, 'RCCrowd.esm'))

        assert TT.is_eq(R.ba2_names(os.path.join(d, 'Starfield - Textures01.ba2')),
                        {'textures\\actors\\human\\crowd\\vanilla_metal.dds'},
                        "a BA2's names, lowercased with backslashes")

        plugins = R.load_plugins(R.Report(), [d], ['RCCrowd.esm'])
        npcs = R.winning_records(plugins, 'NPC_')
        models = R.crowd_head_models(plugins, npcs)
        found = {(sx, rel.replace('\\', '/').split('/')[-1], info['head'])
                 for (sx, rel), info in models.items()}
        assert TT.is_eq(found, {('MALE', 'Head_A.nif', True), ('MALE', 'Head_B.nif', True),
                                ('MALE', 'Tail.nif', False), ('FEMALE', 'Head_F.nif', True)},
                        "every addon of every head armor, nested lists too, by NPC sex")

        rep = R.Report()
        R.check_crowd_heads(rep, [d], models)
        fails = [f"{m} {dt}" for lv, _a, m, dt in rep.findings if lv == R.FAIL]
        assert TT.is_eq(len(fails), 3, f"three problems: {fails}")
        missing_tex = [f for f in fails if 'head_normal.dds' in f]
        assert TT.is_true(len(missing_tex) == 1 and '(3 crowd models)' in missing_tex[0],
                          f"one finding for a texture three models share: {missing_tex}")
        assert TT.is_true(any('face rig' in f and 'Head_B_faceBones' in f for f in fails),
                          f"a companion skinned to face bones fails: {fails}")
        assert TT.is_true(any('not on disk' in f and 'Head_F.nif' in f for f in fails),
                          f"a missing female head model fails: {fails}")
        assert TT.is_true(not any('vanilla_metal' in f for _l, _a, m, dt in rep.findings
                                  for f in [f"{m} {dt}"]),
                          "a texture in a BA2 is vanilla's: not reported")


@TT.requires_assets('SF')
def TEST_UV_TRANSFER_IMAGE_IO():
    """uv_transfer reads the textures it's given and writes what it paints.

    Starfield colour textures are sRGB block-compressed DDS, which Pillow refuses outright; the
    blocks are the same as the plain formats, so the reader relabels them. 16-bit PNG output,
    used for normals, is written by hand since Pillow can't write it."""
    import numpy as np
    import uv_transfer as U

    crowd = os.path.join(TT.SF_ASSETS, 'textures', 'actors', 'human', 'crowd')
    color = U.load_image(os.path.join(crowd, 'crowd_af_md1_color.dds'))   # BC1 sRGB
    assert TT.is_eq(color.shape[:2], (1024, 1024), "sRGB colour DDS read")
    assert TT.is_true(0.05 < color[..., :3].mean() < 0.95, f"with real pixels: {color.mean():.3f}")
    ao = U.load_image(os.path.join(crowd, 'crowd_af_md1_ao.dds'))
    assert TT.is_eq(ao.shape, (1024, 1024, 1), "single-channel DDS read as one channel")

    # 16-bit round trip: grey exactly (Pillow reads it at 16 bits), RGB to 8-bit precision.
    os.makedirs(OUT, exist_ok=True)
    ramp = (np.arange(64 * 64, dtype=np.float32) / (64 * 64 - 1)).reshape(64, 64, 1)
    U.save_image(ramp, os.path.join(OUT, r"TEST_UV_TRANSFER_grey16.png"), bits=16)
    back = U.load_image(os.path.join(OUT, r"TEST_UV_TRANSFER_grey16.png"))
    assert TT.is_true(np.abs(back - ramp).max() < 1 / 65535 + 1e-7, "16-bit grey round trip")
    rgb = np.concatenate([ramp, ramp[::-1], ramp[:, ::-1]], axis=-1)
    U.save_image(rgb, os.path.join(OUT, r"TEST_UV_TRANSFER_rgb16.png"), bits=16)
    back = U.load_image(os.path.join(OUT, r"TEST_UV_TRANSFER_rgb16.png"))
    assert TT.is_true(np.abs(back - rgb).max() < 1 / 255 + 1e-6, "16-bit RGB round trip")

    # Flat colours, and every part accounted for.
    assert TT.is_eq(U.parse_flat('#ff8000'), (1.0, 128 / 255, 0.0), "flat colour")
    assert TT.is_eq(U.parse_flat('#80'), (128 / 255,), "flat grey")
    m = {'parts': np.array(['Head', 'Eye']), 'part': np.zeros(0, np.int16),
         'tgt_uv': np.zeros((0, 3, 2)), 'src_uv': np.zeros((0, 3, 2))}
    for textures, why in (({'Head': (1, 1, 1)}, "a part left out"),
                          ({'Head': (1, 1, 1), 'Eye': (1, 1, 1), 'Ear': (1, 1, 1)}, "a stray part")):
        try:
            U.paint(m, textures, size=8)
            assert False, f"{why} must be refused"
        except ValueError:
            pass


def TEST_UV_TRANSFER_CLI_PAINT():
    """`uv_transfer.py paint` paints from the command line even where a `bpy` module imports.

    Bad Dog's Python has a stray `bpy` folder in site-packages, an empty namespace package. The
    script took "bpy imports" to mean "running in Blender" and tried to build a map from the
    Blender selection instead of painting."""
    import subprocess
    import numpy as np
    scripts = str(ROOT)
    sys.path.insert(0, scripts)
    import uv_transfer as U

    work = os.path.abspath(os.path.join(OUT, r"TEST_UV_TRANSFER_CLI"))
    os.makedirs(os.path.join(work, 'bpy'), exist_ok=True)     # the stray namespace package
    mp = os.path.join(work, 'one.uvmap.npz')
    tri = np.array([[[0, 0], [1, 0], [0, 1]]], np.float64)
    U.write_map(mp, {'parts': np.array(['Part']), 'part': np.zeros(1, np.int16),
                     'tgt_uv': tri, 'src_uv': tri, 'target': np.array('Joined')})
    out = os.path.join(work, 'painted.png')
    if os.path.exists(out):
        os.remove(out)

    env = dict(os.environ, PYTHONPATH=work)
    r = subprocess.run([sys.executable, os.path.join(scripts, 'uv_transfer.py'), 'paint',
                        '--map', mp, '--out', out, '--part', 'Part=#ff0000', '--size', '8'],
                       env=env, capture_output=True, text=True)
    assert TT.is_eq(r.returncode, 0, f"paint ran: {r.stderr.strip()[-300:]}")
    img = U.load_image(out)
    assert TT.is_eq(tuple(np.round(img[7, 0, :3], 3)), (1.0, 0.0, 0.0),
                    "the triangle's corner pixel is painted")


def _tintbake():
    import sf_tintbake
    return sf_tintbake


def _fake_sf_mesh(weights):
    """A Starfield .mesh whose skin is `weights`: one [(bone, u16 weight)...] per vertex. Only
    what the readers look at is real: the header, empty uv/colour/normal/tangent sections, the
    weights."""
    import struct
    nv, wpv = len(weights), len(weights[0])
    out = struct.pack('<II', 2, 3) + struct.pack('<3H', 0, 1, 2)
    out += struct.pack('<fII', 1.0, wpv, nv) + bytes(nv * 6)
    for _section in ('uv1', 'uv2', 'color', 'normal', 'tangent'):
        out += struct.pack('<I', 0)
    out += struct.pack('<I', nv * wpv) + b''.join(struct.pack('<HH', b, w) for v in weights for b, w in v)
    return out


def _unweighted_crowd_head(d):
    """A crowd head NIF and its _faceBones companion under d, as sf_racecheck and sf_tintbake
    read them, on a mesh with 3 of 5 vertices weighted (the 2 others: no weight at all). Returns
    the head's path under Meshes."""
    import shutil
    src = os.path.join(FIXTURES, 'crowd_head_af_md1.nif')
    rel = 'Actors/UW_Crowd/Head.nif'
    for name in ('Head', 'Head_faceBones'):
        dst = os.path.join(d, 'meshes', 'Actors', 'UW_Crowd', name + '.nif')
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
    full = [(1, 65535), (0, 0)]
    mesh = _fake_sf_mesh([full, full, [(0, 0), (0, 0)], full, [(0, 0), (0, 0)]])
    for mp in NifFile(src).shapes[0].mesh_paths():
        path = os.path.join(d, 'geometries', *mp.replace('\\', '/').split('/')) + '.mesh'
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, 'wb').write(mesh)
    return rel


def TEST_SF_RACECHECK_UNWEIGHTED():
    """sf_racecheck fails a crowd head whose mesh -- its own or its _faceBones companion's -- has
    vertices with no skin weight."""
    import tempfile
    import sf_racecheck as R
    with tempfile.TemporaryDirectory() as d:
        rel = _unweighted_crowd_head(d)
        rep = R.Report()
        R.check_crowd_heads(rep, [d], {('FEMALE', rel): {'head': True, 'armors': {'Head'}}})
        hits = [f"{m} {dt}" for lv, _a, m, dt in rep.findings if lv == R.FAIL and 'skin weight' in m]
        assert TT.is_eq(len(hits), 1, f"one finding: {hits}")
        assert TT.is_true('2 of 5' in hits[0], f"says how many: {hits[0]}")


def TEST_SF_TINTBAKE_UNWEIGHTED():
    """sf_tintbake warns, before baking, about a head whose mesh or _faceBones companion's mesh
    has vertices with no skin weight: every variant would inherit them."""
    import tempfile
    B = _tintbake()
    with tempfile.TemporaryDirectory() as d:
        rel = _unweighted_crowd_head(d)
        said = []
        B.check_head_weights({'data': [d]}, [os.path.join(d, 'meshes', *rel.split('/'))], said.append)
        assert TT.is_eq(len(said), 2, f"the head and its companion: {said}")
        assert TT.is_true(all('2 of 5' in s for s in said), f"says how many: {said}")
        assert TT.is_true(any('faceBones' in s for s in said), f"names the companion: {said}")


def TEST_SF_TINTBAKE_COMPOSITE():
    """sf_tintbake lays tint layers over a skin tone the way the chargen face does, in linear space.

    A full-colour layer goes on by its own alpha. A mask blends one colour in by mask x intensity
    x the colour's alpha. A layer at another resolution is resized to the skin tone's."""
    import numpy as np
    B = _tintbake()
    base = np.full((4, 4, 3), 0.5, np.float32)
    color = np.zeros((4, 4, 4), np.float32)
    color[..., 0] = 1.0                    # red ...
    color[0, :, 3] = 1.0                   # ... opaque on the top row
    color[1, :, 3] = 0.25                  # ... a quarter on the next
    out = B.composite(base, [(color, None, 1.0)])
    assert TT.is_eq(tuple(np.round(out[0, 0], 4)), (1.0, 0.0, 0.0), "opaque colour replaces")
    assert TT.is_eq(tuple(np.round(out[1, 0], 4)), (0.673, 0.4373, 0.4373), "alpha blends in linear")
    assert TT.is_eq(tuple(np.round(out[3, 0], 4)), (0.5, 0.5, 0.5), "zero alpha lets the tone through")

    mask = np.zeros((2, 2, 1), np.float32)     # half-size: resized to the tone's 4x4
    mask[...] = 1.0
    out = B.composite(base, [(mask, (0.0, 0.0, 1.0, 0.5), 1.0)])
    assert TT.is_eq(out.shape, (4, 4, 3), "a smaller layer is resized")
    assert TT.is_eq(tuple(np.round(out[2, 2], 4)), (0.3608, 0.3608, 0.8019),
                    "a mask blends its colour by the colour's alpha, in linear")
    out = B.composite(base, [(color, None, 1.0), (mask, (0.0, 0.0, 1.0, 1.0), 1.0)])
    assert TT.is_eq(tuple(np.round(out[0, 0], 4)), (0.0, 0.0, 1.0), "later layers paint over earlier ones")


def TEST_SF_TINTBAKE_BODY_TYPES():
    """sf_tintbake treats a head's body types as one head.

    Vanilla ships every crowd head three times: <head>.nif (average), <head>_thin.nif and
    <head>_overweight.nif, each with a _facebones companion. PyNifly writes one nif per '_' shape
    key, so Bad Dog's export gives _Thin, _average and _Overweight; _average, or no suffix, is the
    average. A variant is baked once -- one texture, one material -- and written out as a nif per
    body type, named the vanilla way, each pointing at that material."""
    import shutil
    import tempfile
    B = _tintbake()
    heads = [r"x\crowdf_fox_md1_average.nif", r"x\crowdf_fox_md1_Thin.nif",
             r"x\crowdf_fox_md1_Overweight.nif", r"x\Crowd_Head_Fox_md1.nif", r"x\Other_thin.nif"]
    assert TT.is_eq(B.group_heads(heads), {
        'crowdf_fox_md1': {'': heads[0], '_thin': heads[1], '_overweight': heads[2]},
        'Crowd_Head_Fox_md1': {'': heads[3]},
        'Other': {'_thin': heads[4]}}, "grouped by name without the body suffix")

    opts = B.Options(tones=[('f0', 'h0')], slots={}, derm=[[('x', 'd0_derm_color.dds')]],
                     eyes=[('Blue', 'blue.dds')], stack=['Dermaesthetic'])
    r = {'_dir': os.getcwd(), 'eyes': {'code': 'e'},
         'layers': [{'slot': 'Dermaesthetic', 'code': 'd'}]}
    space = B.variant_space(r, opts, heads[:3])
    assert TT.is_eq([v['name'] for v in space], ['crowdf_fox_md1_sk0_d1e1'],
                    "one variant for the three body types, named without a body suffix")
    assert TT.is_eq(space[0]['bodies'], {'': heads[0], '_thin': heads[1], '_overweight': heads[2]},
                    "the variant carries every body type's nif")

    src = os.path.join(FIXTURES, 'crowd_head_af_md1.nif')
    new = r"Materials\Actors\FSFFox\Crowd\Variants\V1.mat"
    with tempfile.TemporaryDirectory() as d:
        bodies = {}
        for body, fn in (('', 'H_average'), ('_thin', 'H_Thin'), ('_overweight', 'H_Overweight')):
            bodies[body] = os.path.join(d, 'in', fn + '.nif')
            os.makedirs(os.path.dirname(bodies[body]), exist_ok=True)
            shutil.copyfile(src, bodies[body])
        shutil.copyfile(src, os.path.join(d, 'in', 'H_Thin_faceBones.nif'))
        written = B.write_body_nifs(bodies, os.path.join(d, 'out'), r"Actors\Fox\Variants", 'V1', new)
        assert TT.is_eq(written, {'average': r"Actors\Fox\Variants\V1.nif",
                                  'thin': r"Actors\Fox\Variants\V1_thin.nif",
                                  'overweight': r"Actors\Fox\Variants\V1_overweight.nif"},
                        "a nif per body type, named the vanilla way, by body type")
        for rel in list(written.values()) + [r"Actors\Fox\Variants\V1_thin_facebones.nif"]:
            path = os.path.join(d, 'out', 'Meshes', *rel.split('\\'))
            assert TT.is_eq(B.nif_material(path), new, f"{rel} points at the variant's material")
        assert TT.is_true(not os.path.exists(os.path.join(d, 'out', 'Meshes', 'Actors', 'Fox',
                                                          'Variants', 'V1_facebones.nif')),
                          "no companion where the source had none")


def TEST_SF_TINTBAKE_BEARDS():
    """sf_tintbake's beards: each variant gets one of its head's fitted beards, or none.

    A crowd head's jaw and chin are baked into its mesh (no chargen morphs on a crowd actor), so
    a beard is exported per head and body type, into the heads folder's Beards\\ beside them:
    <head>_<beard>[_thin|_overweight].nif. How many variants have one is the race's choice:
    `percent`, 100 always and 0 never, in between a stable pick by name. The beard is a
    record-level choice -- its colour comes from its addon's AVM group, not the face texture --
    so a variant's texture, material and nif are named by its beard-less base."""
    import tempfile
    B = _tintbake()
    opts = B.Options(tones=[('f0', 'h0')], slots={}, derm=[[('x', 'd0_derm_color.dds')]],
                     eyes=[('Blue', 'blue.dds')], stack=['Dermaesthetic'])

    def recipe(**beards):
        return {'_dir': os.getcwd(), 'eyes': {'code': 'e'}, 'seed': 1,
                'layers': [{'slot': 'Dermaesthetic', 'code': 'd'}],
                'beards': {'code': 'b', 'percent': 100, 'folder': 'Beards', **beards}}

    with tempfile.TemporaryDirectory() as d:
        heads = []
        for name in ('Fox_md1', 'Fox_md1_thin', 'Fox_md10'):
            heads.append(os.path.join(d, name + '.nif'))
            open(heads[-1], 'wb').close()
        os.makedirs(os.path.join(d, 'Beards'))
        for name in ('Fox_md1_Ruff01', 'Fox_md1_Ruff01_thin', 'Fox_md1_Ruff01_faceBones',
                     'Fox_md10_Ruff02'):
            open(os.path.join(d, 'Beards', name + '.nif'), 'wb').close()

        found = B.find_beards(d, recipe()['beards'], ['Fox_md1', 'Fox_md10'])
        assert TT.is_eq({h: {b: sorted(bodies) for b, bodies in bs.items()} for h, bs in found.items()},
                        {'Fox_md1': {'Ruff01': ['', '_thin']}, 'Fox_md10': {'Ruff02': ['']}},
                        "paired by the longest head name; companions skipped; body types split off")

        space = B.variant_space(recipe(), opts, heads, found)
        names = sorted(v['name'] for v in space)
        assert TT.is_eq(names, ['Fox_md10_sk0_d1e1bRuff02', 'Fox_md1_sk0_d1e1bRuff01'],
                        "percent 100: one variant per base, every one with its head's beard")
        v = next(v for v in space if v['name'] == 'Fox_md1_sk0_d1e1bRuff01')
        assert TT.is_eq((v['base'], v['beard']), ('Fox_md1_sk0_d1e1', 'Ruff01'),
                        "the beard-less base names the texture, material and nifs")
        assert TT.is_eq(sorted(v['beard_nifs']), ['', '_thin'], "the beard's nif per body type")

        never = B.variant_space(recipe(percent=0), opts, heads, found)
        assert TT.is_eq(sorted(v['name'] for v in never),
                        ['Fox_md10_sk0_d1e1b0', 'Fox_md1_sk0_d1e1b0'], "percent 0: no beards")
        none = never[0]
        assert TT.is_eq((none['base'][-8:], none['beard'], none['beard_nifs']),
                        ('sk0_d1e1', None, {}), "no beard")

        many = B.Options(tones=[('f0', 'h0')], slots={}, derm=[[('x', 'd0_derm_color.dds')]],
                         eyes=[(f'E{i}', f'e{i}.dds') for i in range(40)], stack=['Dermaesthetic'])
        half = B.variant_space(recipe(percent=50), many, heads, found)
        bearded = [v for v in half if v['beard']]
        assert TT.is_eq(len(half), 80, "still one variant per base")
        assert TT.is_true(20 <= len(bearded) <= 60, f"percent 50: a mix ({len(bearded)} of 80)")
        assert TT.is_eq([v['name'] for v in B.variant_space(recipe(percent=50), many, heads, found)],
                        [v['name'] for v in half], "the same pick every run")

        os.makedirs(os.path.join(d, 'bare'))
        bare = os.path.join(d, 'bare', 'Fox_md2.nif')
        open(bare, 'wb').close()
        said = []
        mixed = B.variant_space(recipe(), opts, heads + [bare], found, log=said.append)
        assert TT.is_true(mixed and all(v['beard'] for v in mixed),
                          "percent 100: a head with no beard is left out, the rest baked")
        assert TT.is_true(not any('Fox_md2' in v['name'] for v in mixed), "Fox_md2 left out")
        assert TT.is_true(any('Fox_md2' in s for s in said), f"and a warning names it: {said}")
        try:
            B.variant_space(recipe(), opts, [bare], found, log=said.append)
            raise AssertionError("no head with a beard at all should be refused")
        except B.RecipeError as e:
            assert TT.is_true('beard' in str(e), f"says why: {e}")
        assert TT.is_true(all(v['beard'] is None
                              for v in B.variant_space(recipe(percent=99), opts, [bare], found)),
                          "under 100, a head with no beards just goes without")
        for bad in (-1, 101, 'lots'):
            try:
                B.check_beards_cfg({'code': 'b', 'percent': bad, 'folder': 'Beards'})
                raise AssertionError(f"percent {bad!r} should be refused")
            except B.RecipeError:
                pass

        no_beards = {k: v for k, v in recipe().items() if k != 'beards'}
        assert TT.is_eq(B.variant_space(no_beards, opts, heads[:2])[0]['name'], 'Fox_md1_sk0_d1e1',
                        "no [beards]: no beard dimension, names as before")

        os.remove(os.path.join(d, 'Beards', 'Fox_md1_Ruff01_thin.nif'))
        try:
            B.variant_space(recipe(), opts, heads, B.find_beards(d, recipe()['beards'],
                                                                 ['Fox_md1', 'Fox_md10']))
            raise AssertionError("a beard missing a body type its head has should be refused")
        except B.RecipeError as e:
            assert TT.is_true('thin' in str(e) and 'Ruff01' in str(e), f"says which: {e}")

        open(os.path.join(d, 'Beards', 'Wolf_md1_Ruff01.nif'), 'wb').close()
        try:
            B.find_beards(d, recipe()['beards'], ['Fox_md1', 'Fox_md10'])
            raise AssertionError("a beard for no known head should be refused")
        except B.RecipeError as e:
            assert TT.is_true('Wolf_md1_Ruff01' in str(e), f"names the file: {e}")


def TEST_SF_TINTBAKE_TEETH():
    """sf_tintbake's teeth: a part painted "teeth" takes an option from the race's
    TeethCustomization group, a dimension like the eyes, named _t<n>.

    The mouth used to be one fixed texture named in [parts]; the fox offers Teeth_Clean and
    Teeth_Dirty. With no part painted "teeth" there's no teeth dimension and names don't change."""
    B = _tintbake()
    opts = B.Options(tones=[('f0', 'h0')], slots={}, derm=[[('x', 'd0_derm_color.dds')]],
                     eyes=[('Blue', 'blue.dds'), ('Green', 'green.dds')], stack=['Dermaesthetic'],
                     teeth=[('Teeth_Clean', 'clean.dds'), ('Teeth_Dirty', 'dirty.dds')])
    r = {'_dir': os.getcwd(), 'eyes': {'code': 'e'},
         'teeth': {'code': 't'},
         'layers': [{'slot': 'Dermaesthetic', 'code': 'd'}],
         'parts': {'Head': 'face', 'Mouth': 'teeth', 'Tongue': 'teeth'}}
    space = B.variant_space(r, opts, [r"x\Crowd_Fox_md1.nif"])
    assert TT.is_eq(sorted(v['name'] for v in space),
                    ['Crowd_Fox_md1_sk0_d1e1t1', 'Crowd_Fox_md1_sk0_d1e1t2',
                     'Crowd_Fox_md1_sk0_d1e2t1', 'Crowd_Fox_md1_sk0_d1e2t2'],
                    "eyes x teeth, teeth after the eyes")
    v = next(v for v in space if v['name'].endswith('e2t2'))
    assert TT.is_eq(v['teeth'], 'dirty.dds', "the variant carries its teeth texture")

    r['teeth']['weights'] = {'teeth_dirty': 0}
    assert TT.is_eq(sorted(v['name'] for v in B.variant_space(r, opts, [r"x\Crowd_Fox_md1.nif"])),
                    ['Crowd_Fox_md1_sk0_d1e1t1', 'Crowd_Fox_md1_sk0_d1e2t1'],
                    "weight 0 by label, case-insensitive: never used; numbers keep their places")

    r['teeth']['weights'] = {'Teeth_Clean': 0, 'Teeth_Dirty': 0}
    try:
        B.variant_space(r, opts, [r"x\Crowd_Fox_md1.nif"])
        raise AssertionError("a teeth part with no teeth options should be refused")
    except B.RecipeError:
        pass

    r['parts'] = {'Head': 'face', 'Mouth': 'mouth.dds'}
    names = sorted(v['name'] for v in B.variant_space(r, opts, [r"x\Crowd_Fox_md1.nif"]))
    assert TT.is_eq(names, ['Crowd_Fox_md1_sk0_d1e1', 'Crowd_Fox_md1_sk0_d1e2'],
                    "no part painted 'teeth': no teeth dimension, names as before")


def TEST_SF_TINTBAKE_MASK_COLORS():
    """A mask layer's colours: a list of #rrggbb, a Modulation group named by TNAM or EDID, or --
    `colors` left out -- the game's rule, the Modulation group with the slot's name.

    A group name used to be split into one-letter "colours" and the bake died with "not a
    colour: l" after the variants had been listed."""
    B = _tintbake()
    # Modulation NNAM is x, B, G, R, already linear; vanilla's Pink is 00 59 4E A6.
    pink = B.nnam_color(bytes([0, 89, 78, 166]))
    assert TT.is_equiv([float(x) for x in B.srgb_to_linear(pink[:3])],(166 / 255, 78 / 255, 89 / 255),
                       "NNAM read as linear R, G, B (bytes 3, 2, 1)", e=1e-4)
    assert TT.is_eq(pink[3], 1.0, "byte 0 is not alpha")

    group = [('Black', (0.1, 0.1, 0.1, 1.0)), ('Brown', (0.4, 0.2, 0.1, 1.0)),
             ('Tan', (0.7, 0.5, 0.3, 1.0))]
    colors = {'ComplexionMask1': group, 'Modulation_ComplexionMask1': group}
    opts = B.Options(tones=[('f0', 'h0')], slots={'ComplexionMask1': [('Spots', 'spots_mask.dds')]},
                     derm=[[('x', 'd0_derm_color.dds')]], eyes=[('Blue', 'blue.dds')],
                     stack=['Dermaesthetic', 'ComplexionMask1'], teeth=[], colors=colors)
    heads = [r"x\Crowd_Fox_md1.nif"]
    r = {'_dir': os.getcwd(), 'eyes': {'code': 'e'},
         'layers': [{'code': 'c', 'files': ['spots_mask.dds'], 'colors': ['#402010', '#000000']}],
         'parts': {'Head': 'face'}}
    names = sorted(v['name'] for v in B.variant_space(r, opts, heads))
    assert TT.is_eq(names, ['Crowd_Fox_md1_sk0_c1ae1', 'Crowd_Fox_md1_sk0_c1be1'],
                    "a list of colours: one option per colour")

    three = ['Crowd_Fox_md1_sk0_c1ae1', 'Crowd_Fox_md1_sk0_c1be1', 'Crowd_Fox_md1_sk0_c1ce1']
    for name in ('Modulation_ComplexionMask1', 'ComplexionMask1'):
        r['layers'][0]['colors'] = name
        space = B.variant_space(r, opts, heads)
        assert TT.is_eq(sorted(v['name'] for v in space), three, f"group {name!r}: its colours")
    tan = next(v for v in space if v['name'].endswith('c1ce1'))
    assert TT.is_eq(tan['layers'][0][2], group[2][1], "the variant carries the group's colour")

    r['layers'] = [{'code': 'c', 'slot': 'ComplexionMask1'}]
    assert TT.is_eq(sorted(v['name'] for v in B.variant_space(r, opts, heads)), three,
                    "no `colors`: the slot's own Modulation group")

    r['layers'] = [{'code': 'c', 'files': ['spots_mask.dds']}]
    try:
        B.variant_space(r, opts, heads)
        raise AssertionError("a mask with no colours and no slot should be refused")
    except B.RecipeError as e:
        assert TT.is_true('colors' in str(e), f"says why: {e}")

    for bad in ("Modulation_Nothing", "modulation_complexionmask1", ['#402010', 'brownish'], []):
        r['layers'][0]['colors'] = bad
        try:
            B.variant_space(r, opts, heads)
            raise AssertionError(f"colors = {bad!r} should be refused")
        except B.RecipeError as e:
            assert TT.is_true('colors' in str(e) and 'layer c' in str(e), f"says where: {e}")

    many = [(f"C{i}", (0.0, 0.0, 0.0, 1.0)) for i in range(29)]   # vanilla ComplexionMask2 has 29
    opts.colors['Many'] = many
    r['layers'][0]['colors'] = 'Many'
    codes = sorted(v['name'].split('_')[-1] for v in B.variant_space(r, opts, heads))
    assert TT.is_eq(len(set(codes)), 29, "more colours than letters still name apart")
    assert TT.is_true('c1aae1' in codes, f"the 27th is 'aa': {codes[:4]}...")


def TEST_SF_TINTBAKE_RECIPE_KEYS():
    """sf_tintbake refuses a recipe table or key it doesn't know, naming the likely one.

    Unknown names were ignored: a recipe with [beard] for [beards] baked with no beards, and
    nothing said why."""
    import tempfile
    B = _tintbake()
    head = '''race = "R"\nphenotype = "male_fox_md1"\ndata = ["."]\nheads = "h"\nuvmap = "u.npz"
parts = { "Head" = "face" }\n'''

    def load(text):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'r.toml')
            with open(p, 'w', encoding='utf-8') as f:
                f.write(head + text)
            return B.load_recipe(p)

    r = load('[eyes]\ncode = "e"\nweights = { Dead = 0 }\n[[layers]]\nslot = "S"\ncode = "d"\n'
             'optional = true\n[beards]\npercent = 40\ncolors = "C"\n[tail]\nslot = 15\n')
    assert TT.is_eq(r['beards']['percent'], 40, "a recipe using only known names loads")

    for text, bad, hint in (('[beard]\npercent = 100\n', 'beard', 'beards'),
                            ('[eyes]\nexlcude = ["Dead"]\n', 'exlcude', None),
                            ('[[layers]]\nslot = "S"\ncode = "d"\noptinal = true\n', 'optinal', 'optional'),
                            ('limt = 40\n', 'limt', 'limit')):
        try:
            load(text)
            raise AssertionError(f"{bad!r} should be refused")
        except B.RecipeError as e:
            assert TT.is_true(bad in str(e), f"names {bad!r}: {e}")
            if hint:
                assert TT.is_true(hint in str(e), f"suggests {hint!r}: {e}")


def TEST_SF_TINTBAKE_OUT_FOLDER():
    """sf_tintbake writes to --out, or the game's Data folder (the recipe's first `data`) without it.

    A folder in the recipe meant every bake went wherever the recipe last said."""
    import tempfile
    B = _tintbake()
    head = '''race = "R"\nphenotype = "male_fox_md1"\nheads = "h"\nuvmap = "u.npz"
data = ["C:/Game/Data", "C:/Assets"]\nparts = { "Head" = "face" }\n'''

    def load(text='', **kw):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, 'r.toml')
            with open(p, 'w', encoding='utf-8') as f:
                f.write(head + text)
            return B.load_recipe(p, **kw)

    assert TT.is_eq(load()['out'], 'C:/Game/Data', "no --out: the game's Data folder")
    assert TT.is_eq(load(out=r'C:\Mods\Test')['out'], r'C:\Mods\Test', "--out wins")
    assert TT.is_eq(load(out='rel')['out'], os.path.abspath('rel'),
                    "a relative --out is from where you ran it")
    try:
        load('out = "C:/Mods/Test"\n')
        raise AssertionError("`out` in a recipe should be refused")
    except B.RecipeError as e:
        assert TT.is_true('--out' in str(e), f"says what replaced it: {e}")


def TEST_SF_TINTBAKE_TINT_PLUGIN():
    """sf_tintbake reads a race's tint groups from its own tint plugin, whichever player plugin is
    active.

    The player plugins (one per race) replace the GLOBAL tint groups (Complexion1...) under the
    same names, and only one is deployed. With the hyena's active, the fox recipe found the
    hyena's empty Complexion1 and stopped: "layer c has no options for skin tone 0". Every race's
    tint_plugin (from the race TOMLs beside race_config) leaves the load order, and the recipe's
    race's own is laid over the rest."""
    import tempfile
    B = _tintbake()
    import sf_racecheck as R
    with tempfile.TemporaryDirectory() as d:
        for name, plugin in (('FoxRace', 'C:/Mods/Fox/FSFPlayer_FOX.esm'), ('HyenaRace', 'FSFPlayer_HYENA.esm'),
                             ('PlainRace', None)):
            with open(os.path.join(d, name + '.toml'), 'w') as f:
                f.write('[race]\neditorid = "%s"\n' % name + (f'tint_plugin = "{plugin}"\n' if plugin else ''))
        own, every = B.race_tint_plugins(os.path.join(d, 'FoxRace.toml'))
        assert TT.is_eq(own, 'C:/Mods/Fox/FSFPlayer_FOX.esm', "the recipe's race's own tint plugin")
        assert TT.is_eq(every, {'fsfplayer_fox.esm', 'fsfplayer_hyena.esm'}, "every race's, by file name")
        assert TT.is_eq(B.race_tint_plugins(os.path.join(d, 'PlainRace.toml'))[0], None, "none given: None")

    class Sub:
        def __init__(self, v):
            self.v = v
            self.size = 4 if isinstance(v, int) else len(v) + 1

        def get_string(self):
            return self.v

        def get_uint32(self):
            return self.v

    class Rec:
        def __init__(self, edid, kind, tnam):
            self.editor_id, self.subs = edid, {'TNAM': Sub(tnam), 'MNAM': Sub(kind)}

        def get_subrecord(self, sig):
            return self.subs.get(sig)

    class Plug:
        def __init__(self, *recs):
            self.recs = recs

        def get_records_by_signature(self, sig):
            return list(self.recs) if sig == 'AVMD' else []

    avm = R.AvmIndex()
    hyena = Rec('SimpleGroup_Complexion1', R.AVM_SIMPLE, 'Complexion1')
    avm[(R.AVM_SIMPLE, 'Complexion1')] = hyena
    avm.by_edid[hyena.editor_id] = hyena
    fox = Rec('SimpleGroup_Complexion1', R.AVM_SIMPLE, 'Complexion1')
    B.overlay_avm(avm, Plug(fox))
    assert TT.is_true(avm[(R.AVM_SIMPLE, 'Complexion1')] is fox, "the race's own group wins by name")
    assert TT.is_true(avm.by_edid['SimpleGroup_Complexion1'] is fox, "and by editor ID")


def TEST_SF_TINTBAKE_RACE_CONFIG():
    """sf_tintbake's `race_config`: the furrifier's race file says which breed each head belongs
    to and that breed's tones, and the bake makes only those variants.

    The bake made every head in every tone; the plugin build then dropped the variants no breed
    takes, so most of the fennec head's sample was fox tones, thrown away. A head is a breed's
    when its crowd_heads globs match the variant names, and the tones are the furrifier's: the
    breed's skin_tone_override_female (female), its skin_tone_override, else the race's
    skin_tones_female (female) or skin_tones."""
    import tempfile
    B = _tintbake()
    race = '''[race]
editorid = "R"
skin_tones = [0, 1, 2]
skin_tones_female = [0, 1]
[[breeds]]
name = "red"
weight = 90
crowd_heads = ["Crowd_Fox_*", "crowdf_fox_*"]
[[breeds]]
name = "fennec"
weight = 0
crowd_heads = ["crowdf_fennec_*"]
skin_tone_override = [3, 4]
skin_tone_override_female = [4]
[[breeds]]
name = "arctic"
weight = 0
skin_tone_override = [0]
'''
    opts = B.Options(tones=[(f'f{t}', f'h{t}') for t in range(5)], slots={},
                     derm=[[('x', 'd0_derm_color.dds')]] * 5, eyes=[('Blue', 'blue.dds')],
                     stack=['Dermaesthetic'])
    heads = [r"x\crowdf_fox_01.nif", r"x\crowdf_fennec_01.nif"]

    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, 'FoxRace.toml'), 'w', encoding='utf-8') as f:
            f.write(race)

        def load(sex, extra=''):
            p = os.path.join(d, 'r.toml')
            with open(p, 'w', encoding='utf-8') as f:
                f.write(f'race = "R"\nphenotype = "{sex}_fox_md1"\ndata = ["."]\nheads = "h"\n'
                        f'uvmap = "u.npz"\nrace_config = "FoxRace.toml"\n{extra}'
                        '[eyes]\ncode = "e"\n[[layers]]\nslot = "Dermaesthetic"\ncode = "d"\n'
                        '[parts]\n"Head" = "face"\n')
            return B.load_recipe(p)

        def tones(r, hs=heads):
            out = {}
            for v in B.variant_space(r, opts, hs):
                out.setdefault(v['stem'], set()).add(v['tone'])
            return out

        assert TT.is_eq(tones(load('female')), {'crowdf_fox_01': {0, 1}, 'crowdf_fennec_01': {4}},
                        "female: the race's female tones, and the fennec breed's female override")
        assert TT.is_eq(tones(load('male')), {'crowdf_fox_01': {0, 1, 2}, 'crowdf_fennec_01': {3, 4}},
                        "male: the race's tones, and the fennec breed's override")
        assert TT.is_eq(tones(load('male', 'tones = [1, 3]\n')),
                        {'crowdf_fox_01': {1}, 'crowdf_fennec_01': {3}}, "the recipe's tones narrow them")
        v = B.variant_space(load('female'), opts, heads)
        assert TT.is_eq({x['stem']: x['breed'] for x in v},
                        {'crowdf_fox_01': 'red', 'crowdf_fennec_01': 'fennec'}, "each variant knows its breed")

        try:
            B.variant_space(load('female'), opts, heads + [r"x\crowdf_wolf_01.nif"])
            raise AssertionError("a head no breed takes should be refused")
        except B.RecipeError as e:
            assert TT.is_true('crowdf_wolf_01' in str(e) and 'crowd_heads' in str(e), f"names it: {e}")

        try:
            B.variant_space(load('male', 'tones = [0]\n'), opts, heads)
            raise AssertionError("a head left with no tones should be refused")
        except B.RecipeError as e:
            assert TT.is_true('crowdf_fennec_01' in str(e), f"names it: {e}")

        no_cfg = load('male').copy()
        no_cfg.pop('breeds')
        assert TT.is_eq(tones(no_cfg), {'crowdf_fox_01': {0, 1, 2, 3, 4}, 'crowdf_fennec_01': {0, 1, 2, 3, 4}},
                        "without race_config, every tone, as before")

        with open(os.path.join(d, 'r2.toml'), 'w', encoding='utf-8') as f:
            f.write('race = "R"\nphenotype = "male_fox_md1"\ndata = ["."]\nheads = "h"\n'
                    'uvmap = "u.npz"\nrace_config = "Missing.toml"\n[parts]\n"Head" = "face"\n')
        try:
            B.load_recipe(os.path.join(d, 'r2.toml'))
            raise AssertionError("a race_config that isn't there should be refused")
        except B.RecipeError as e:
            assert TT.is_true('Missing.toml' in str(e), f"names it: {e}")


def TEST_SF_TINTBAKE_HEADS_PATTERN():
    """sf_tintbake's `heads` is a folder (every head nif in it) or a pattern on the nif names.

    A recipe paints one UV layout, and the female fox md1, md2 and fennec heads are three meshes
    in one folder, so each recipe has to pick its own heads out of it. Beards are found beside
    the heads either way."""
    import tempfile
    B = _tintbake()
    with tempfile.TemporaryDirectory() as d:
        for n in ('crowdf_fox_01', 'crowdf_fox_01_thin', 'crowdf_fox_01_facebones', 'crowdf_fox_02',
                  'crowdf_fennec_01', 'crowdf_fennec_01_overweight'):
            open(os.path.join(d, n + '.nif'), 'wb').close()

        def names(paths):
            return sorted(os.path.basename(p) for p in paths)
        assert TT.is_eq(names(B.find_heads(d)),
                        ['crowdf_fennec_01.nif', 'crowdf_fennec_01_overweight.nif', 'crowdf_fox_01.nif',
                         'crowdf_fox_01_thin.nif', 'crowdf_fox_02.nif'], "a folder: every head")
        assert TT.is_eq(names(B.find_heads(os.path.join(d, 'CrowdF_Fennec_*.nif'))),
                        ['crowdf_fennec_01.nif', 'crowdf_fennec_01_overweight.nif'],
                        "a pattern: its heads, any case, body types included")
        assert TT.is_eq(names(B.find_heads(os.path.join(d, 'crowdf_fox_01*'))),
                        ['crowdf_fox_01.nif', 'crowdf_fox_01_thin.nif'], "no companions")
        assert TT.is_eq(B.heads_folder(os.path.join(d, 'crowdf_fox_01*')), d, "beards look beside them")
        assert TT.is_eq(B.heads_folder(d), d, "a folder is its own")

        # The heads share their Beards folder: a recipe takes its own heads' beards, passes
        # over the others', and still refuses a beard that fits no head at all.
        os.mkdir(os.path.join(d, 'Beards'))
        for n in ('crowdf_fox_01_Ruff01', 'crowdf_fennec_01_Ruff02'):
            open(os.path.join(d, 'Beards', n + '.nif'), 'wb').close()
        cfg = {'folder': 'Beards'}
        pattern = os.path.join(d, 'crowdf_fennec_*.nif')
        found = B.find_beards(B.heads_folder(pattern), cfg, list(B.group_heads(B.find_heads(pattern))))
        assert TT.is_eq({h: sorted(b) for h, b in found.items()}, {'crowdf_fennec_01': ['Ruff02']},
                        "its own heads' beards; the fox's passed over")
        open(os.path.join(d, 'Beards', 'crowdf_wolf_01_Ruff01.nif'), 'wb').close()
        try:
            B.find_beards(B.heads_folder(pattern), cfg, list(B.group_heads(B.find_heads(pattern))))
            raise AssertionError("a beard for no head in the folder should be refused")
        except B.RecipeError as e:
            assert TT.is_true('crowdf_wolf_01_Ruff01' in str(e), f"names it: {e}")

        try:
            B.find_heads(os.path.join(d, 'crowdf_wolf_*.nif'))
            raise AssertionError("a pattern matching nothing should be refused")
        except B.RecipeError as e:
            assert TT.is_true('crowdf_wolf_' in str(e), f"names it: {e}")


def TEST_SF_TINTBAKE_WEIGHTS():
    """sf_tintbake's option weights: `weights = { Label = n }` in an option table makes an option
    more or less likely in the sample; unlisted options weigh 50; 0 is never.

    A variant weighs the product of its options' weights, and the sample is a weighted pick that
    stays stable -- same recipe and seed, same set. All weights equal picks exactly the set the
    unweighted pick did, so recipes without weights don't reshuffle."""
    import hashlib
    B = _tintbake()
    opts = B.Options(tones=[('f0', 'h0'), ('f1', 'h1')], slots={'Complexion1': [('A', 'a.dds'), ('B', 'b.dds')]},
                     derm=[[('x', 'd0.dds')], [('y', 'd1.dds')]],
                     eyes=[(f'E{i}', f'e{i}.dds') for i in range(10)] + [('Dead', 'dead.dds')],
                     stack=['Dermaesthetic', 'Complexion1'],
                     teeth=[('Teeth_Clean', 'clean.dds'), ('Teeth_Dirty', 'dirty.dds'),
                            ('Teeth_Weird', 'weird.dds')])
    heads = [rf"x\Crowd_Fox_md{i}.nif" for i in range(4)]

    def recipe(**kw):
        r = {'_dir': os.getcwd(), 'eyes': {'code': 'e'}, 'teeth': {'code': 't'}, 'seed': 1,
             'layers': [{'slot': 'Dermaesthetic', 'code': 'd'},
                        {'slot': 'Complexion1', 'code': 'c', 'optional': True}],
             'parts': {'Head': 'face', 'Mouth': 'teeth'}}
        for k, v in kw.items():
            r[k]['weights'] = v
        return r

    # Unweighted: same pick as the plain hash-lowest pick.
    space = B.variant_space(recipe(), opts, heads)
    assert TT.is_true(all(v['weight'] == 50 ** 4 for v in space), "unlisted options weigh 50 each")
    plain = sorted(sorted(space, key=lambda v: hashlib.sha256(f"1:{v['name']}".encode()).digest())[:40],
                   key=lambda v: v['name'])
    assert TT.is_eq([v['name'] for v in B.pick(space, 40, 1)], [v['name'] for v in plain],
                    "equal weights: the unweighted sample, unchanged")

    # 80 / 20 / 0.
    space = B.variant_space(recipe(teeth={'Teeth_Clean': 80, 'Teeth_Dirty': 20, 'Teeth_Weird': 0}),
                            opts, heads)
    assert TT.is_true(not any(v['name'].endswith('t3') for v in space), "weight 0: not in the space")
    chosen = B.pick(space, 40, 1)
    clean = sum(v['name'].endswith('t1') for v in chosen)
    assert TT.is_true(clean >= 26, f"80/20 teeth: mostly clean ({clean} of 40)")
    assert TT.is_eq([v['name'] for v in B.pick(space, 40, 1)], [v['name'] for v in chosen], "stable")

    # Dead = 0 alone: the rest stay equal at 50; 'none' weighs an optional layer's no-option.
    space = B.variant_space(recipe(eyes={'Dead': 0}), opts, heads)
    assert TT.is_true(not any('e11' in v['name'].split('_')[-1] for v in space), "Dead never")
    assert TT.is_true(all(v['weight'] == 50 ** 4 for v in space), "the other eyes stay at 50")
    r = recipe()
    r['layers'][1]['weights'] = {'none': 0}
    assert TT.is_true(not any('c0' in v['name'].split('_')[-1] for v in B.variant_space(r, opts, heads)),
                      "'none' is an optional layer's label")

    for bad, why in (({'Teeth_Clen': 80}, "a label the race doesn't offer"),
                     ({'Teeth_Clean': -1}, "a negative weight"),
                     ({'Teeth_Clean': 'lots'}, "a weight that isn't a number")):
        try:
            B.variant_space(recipe(teeth=bad), opts, heads)
            raise AssertionError(f"{why} should be refused")
        except B.RecipeError:
            pass
    r = recipe()
    r['eyes']['exclude'] = ['Dead']
    try:
        B.variant_space(r, opts, heads)
        raise AssertionError("exclude should be refused, pointing at weights")
    except B.RecipeError as e:
        assert TT.is_true('weights' in str(e), f"says what to use instead: {e}")


def TEST_SF_TINTBAKE_VARIANTS():
    """sf_tintbake's variant space and its stable sample.

    Every tone x every layer option x every eye colour, with the dermaesthetic's options taken
    from the tone's own chargen filter. Option numbers are places in the race's own lists, so
    excluding one doesn't renumber the rest. The sample keeps the names that hash lowest: the
    same set every run, and a bigger space only swaps in names that hash lower."""
    B = _tintbake()
    opts = B.Options(tones=[('f0', 'h0'), ('f1', 'h1')],
                     slots={'Complexion1': [('A', 'c1_color.dds'), ('B', 'c2_color.dds')],
                            'ComplexionMask1': [('M', 'spots_mask.dds')]},
                     derm=[[('x', 'd0_derm_color.dds')], [('y', 'd1a_color.dds'), ('z', 'd1b_color.dds')]],
                     eyes=[('Dead', 'dead.dds'), ('Blue', 'blue.dds'), ('Green', 'green.dds')],
                     stack=['Dermaesthetic', 'ComplexionMask1', 'Complexion1'])
    r = {'_dir': os.getcwd(), 'eyes': {'code': 'e', 'weights': {'dead': 0}},
         'layers': [{'slot': 'Dermaesthetic', 'code': 'd'},
                    {'slot': 'Complexion1', 'code': 'c', 'optional': True}]}
    space = B.variant_space(r, opts, [r"x\Crowd_Head_Fox_md1.nif"])
    names = [v['name'] for v in space]
    # tone 0: 1 derm x 3 complexions x 2 eyes; tone 1: 2 x 3 x 2
    assert TT.is_eq(len(space), 6 + 12, "tone x layer options x eyes")
    assert TT.is_true('Crowd_Head_Fox_md1_sk1_d2c0e3' in names, f"named by place: {names[:4]}")
    assert TT.is_true(not any(n.endswith('_e1') for n in names), "an excluded eye is never used")
    v = next(v for v in space if v['name'] == 'Crowd_Head_Fox_md1_sk0_d1c2e2')
    assert TT.is_eq(v['layers'], [('Dermaesthetic', 'd0_derm_color.dds', None),
                                  ('Complexion1', 'c2_color.dds', None)], "the layers it composites")
    assert TT.is_eq(v['eye'], 'blue.dds', "its eye colour")
    assert TT.is_true(not next(v for v in space if 'c0e' in v['name'])['layers'][1:],
                      "'none' composites nothing")

    r['layers'].append({'slot': 'ComplexionMask1', 'code': 'm', 'colors': ['#ff0000', '#00ff00']})
    masked = B.variant_space(r, opts, [r"x\H.nif"])
    assert TT.is_true(any(v['name'].endswith('m1be2') for v in masked), "a mask x its colours")
    r['layers'].pop()

    first = B.pick(space, 5, seed=1)
    assert TT.is_eq([v['name'] for v in B.pick(space, 5, seed=1)], [v['name'] for v in first],
                    "the same sample every run")
    assert TT.is_true([v['name'] for v in B.pick(space, 5, seed=2)] != [v['name'] for v in first],
                      "another seed, another sample")
    bigger = B.variant_space(r, opts, [r"x\Crowd_Head_Fox_md1.nif", r"x\Crowd_Head_Fox_md2.nif"])
    kept = {v['name'] for v in B.pick(bigger, 5, seed=1)} & {v['name'] for v in first}
    new = [v for v in B.pick(bigger, 5, seed=1) if v['name'] not in kept]
    assert TT.is_true(all('_md2_' in v['name'] for v in new),
                      "adding a head only swaps in some of the new head's variants")


def TEST_SF_TINTBAKE_PER_SEX():
    """A race lists its hands (HSTT) and body (BSTT) skin-tone groups once per sex, male first,
    then female. A female recipe must take the female one: the first is the male's hands."""
    B = _tintbake()
    assert TT.is_eq(B.for_sex(['FSFFox_Male_Hands', 'FSFFox_Female_Hands'], 'female'),
                    'FSFFox_Female_Hands', "female takes the second")
    assert TT.is_eq(B.for_sex(['FSFFox_Male_Hands', 'FSFFox_Female_Hands'], 'male'),
                    'FSFFox_Male_Hands', "male takes the first")
    assert TT.is_eq(B.for_sex(['Shared_Hands'], 'female'), 'Shared_Hands',
                    "a race with one group uses it for both sexes")
    assert TT.is_eq(B.for_sex([], 'male'), None, "none at all")


def TEST_SF_TINTBAKE_RETARGET_NIF():
    """A variant nif is the crowd head's nif pointing at another material, and nothing else.

    The material is named twice: a header string, and the shape's MaterialID, a CRC of the
    path. The copy must carry both, and keep the rest -- skin, mesh path, BoneTrn -- intact."""
    from pyn.sf_materials import material_id
    B = _tintbake()
    src = os.path.join(FIXTURES, "crowd_head_af_md1.nif")
    old = B.nif_material(src)
    assert TT.is_eq(old.lower(), r"materials\actors\human\crowd\crowd_af_md1.mat",
                    "the head's material, from the header strings")
    new = r"Materials\Actors\FSFFox\Crowd\Variants\Crowd_Head_Fox_md1_sk2_d1c3e5.mat"
    dst = os.path.join(OUT, r"TEST_SF_TINTBAKE_RETARGET.nif")
    B.retarget_nif(src, dst, old, new)

    a, b = NifFile(src), NifFile(dst)
    assert TT.is_eq(b.shapes[0].shader.name, new, "the shape names the new material")
    ids = {ed.name: ed.integer_data for ed in b.shapes[0].extra_data()}
    assert TT.is_eq(ids['MaterialID'], material_id(new), "MaterialID follows the path")
    assert TT.is_eq(b.shapes[0].mesh_paths(), a.shapes[0].mesh_paths(), "same .mesh files")
    assert TT.is_eq(b.shapes[0].bone_names, a.shapes[0].bone_names, "same skin")
    bt = [e for e in b.rootNode.extra_data() if e.blockname == 'BoneTranslations']
    assert TT.is_eq([n for n, _ in bt[0].translations], ['L_Eye', 'R_Eye'], "BoneTrn kept")
    raw_a, raw_b = open(src, 'rb').read(), open(dst, 'rb').read()
    assert TT.is_eq(len(raw_b) - len(raw_a), len(new) - len(old), "only the string changed size")


@TT.requires_assets('SF')
def TEST_SF_TINTBAKE_TAIL_TONES():
    """A tail's tones come from the recipe's sex, whichever group its material's texture is in.

    The male fox tail's material holds a female body texture, and the male tones outnumber the
    female ones."""
    B = _tintbake()
    male = [rf"Textures\M_sk{i}.dds" for i in range(13)]
    female = [rf"Textures\F_sk{i}.dds" for i in range(6)]
    slot0 = [r"Data\textures\f_SK1.dds", r"Data\Textures\Hands_Mask.dds"]

    old, group = B.tail_tones(slot0, [male, female], 'male', 'Tail.mat')
    assert TT.is_eq(old, slot0[0], "the texture to replace is found in either group")
    assert TT.is_eq(group, male, "male tones for a male tail")

    old, group = B.tail_tones(slot0, [male, female], 'female', 'Tail.mat')
    assert TT.is_eq(old, slot0[0], "the same texture for a female tail")
    assert TT.is_eq(group, female, "female tones for a female tail")

    old, group = B.tail_tones(slot0, [female], 'female', 'Tail.mat')
    assert TT.is_eq(group, female, "one group serves both sexes")

    try:
        B.tail_tones([r"Data\Textures\Other.dds"], [male, female], 'male', 'Tail.mat')
    except B.RecipeError as e:
        assert TT.is_true('Tail.mat' in str(e), f"names the material: {e}")
    else:
        assert TT.is_true(False, "a texture in no group is refused")


def TEST_SF_TINTBAKE_MATERIAL():
    """A variant material is the head's crowd material with another colour texture.

    Its own objects get new res: ids in the same namespace, the way vanilla's crowd materials
    differ from each other; references into the imported templates are left alone."""
    import json
    B = _tintbake()
    src = os.path.join(TT.SF_ASSETS, 'materials', 'actors', 'human', 'crowd', 'Crowd_af_md1.mat')
    with open(src, encoding='utf-8') as f:
        doc = json.load(f)
    fn = r"Materials\Actors\FSFFox\Crowd\Variants\V1.mat"
    color = r"Data\Textures\Actors\FSFFox\crowd\variants\V1_color.dds"
    out = B.derive_material(doc, fn, color)

    assert TT.is_eq(out['Filename'], fn, "filename")
    assert TT.is_eq(B.colour_texture(out), color, "colour texture swapped")
    own = [o['ID'] for o in doc['Objects'] if 'ID' in o]
    new = [o['ID'] for o in out['Objects'] if 'ID' in o]
    assert TT.is_true(own and not set(own) & set(new), f"own ids renewed: {own} -> {new}")
    assert TT.is_eq([i.split(':')[2:] for i in new], [i.split(':')[2:] for i in own],
                    "in the same namespace")
    text_in, text_out = json.dumps(doc), json.dumps(out)
    refs = {t for t in text_in.split('"') if t.startswith('res:')} - set(own)
    assert TT.is_true(refs and all(t in text_out for t in refs), "template references kept")
    for i, o in zip(own, new):
        assert TT.is_eq(text_in.count(i), text_out.count(o), f"every use of {i} follows it")
    assert TT.is_true(B.derive_material(doc, fn, color) == out, "deterministic")
    other = B.derive_material(doc, fn.replace('V1', 'V2'), color)
    assert TT.is_true(not {o['ID'] for o in other['Objects'] if 'ID' in o} & set(new),
                      "two variants don't share ids")

    # A body material has two slot-0 textures (the skin colour, and a mask in a second layer),
    # so the one to swap is named by path. Case and slashes don't matter.
    body = os.path.join(TT.SF_ASSETS, 'materials', 'actors', 'human', 'naked_body', 'Female',
                        'Naked_F_Body.mat')
    with open(body, encoding='utf-8') as f:
        doc = json.load(f)
    tone2 = r"Data\Textures\Actors\human\Naked_Body\NakedBodyF_sk2_color.dds"
    out = B.derive_material(doc, r"Materials\Test\Body_sk2.mat", tone2,
                            old=r"data/textures/actors/human/naked_body/nakedbodyf_sk3_color.dds")
    slot0 = [c['Data']['FileName'] for o in out['Objects'] for c in o.get('Components', [])
             if c.get('Type') == 'BSMaterial::MRTextureFile' and c.get('Index') == 0]
    assert TT.is_eq(slot0, [tone2, r"Data\Textures\Actors\Human\naked_body\NakedBodyF_mask.dds"],
                    "only the named colour texture changes")
    try:
        B.derive_material(doc, r"Materials\Test\X.mat", tone2)
        assert False, "an ambiguous colour slot must be refused"
    except B.RecipeError:
        pass


def TEST_SF_RACECHECK_OFFICIAL_PLUGINS():
    """sf_racecheck loads every official plugin the game does, in xEdit's order.

    The list is xEdit's wbOfficialDLC (wbDefinitionsSF1.pas). Ours was a copy from before
    SFBGS00D, SFBGS047, SFBGS050 and BlueprintShips-SFBGS050 joined it. SFBGS047 is light, so
    the plugin builder counted one light plugin too few ahead of FSFNPC_Fox.esm and wrote
    FE006800 to the batch file where the game has FE007800 (Bad Dog, 2026-10-20)."""
    import tempfile
    import sf_racecheck

    xedit = ['ShatteredSpace.esm', 'Constellation.esm', 'OldMars.esm', 'SFBGS003.esm',
             'SFBGS004.esm', 'SFBGS006.esm', 'SFBGS007.esm', 'SFBGS008.esm', 'SFBGS00D.esm',
             'SFBGS047.esm', 'SFBGS050.esm', 'BlueprintShips-Starfield.esm',
             'BlueprintShips-SFBGS050.esm']
    with tempfile.TemporaryDirectory() as d:
        for name in ['Starfield.esm'] + xedit + ['FSFNPC_Fox.esm']:
            open(os.path.join(d, name), 'wb').close()
        plugins_txt = os.path.join(d, 'Plugins.txt')
        with open(plugins_txt, 'w') as f:
            f.write('# comment\n*FSFNPC_Fox.esm\n')
        order = sf_racecheck.load_order_names([d], plugins_txt=plugins_txt, ccc_file='')
    assert TT.is_eq(order, ['Starfield.esm'] + xedit + ['FSFNPC_Fox.esm'],
                    "the game's own plugins in xEdit's order, then Plugins.txt's")


def TEST_SF_RACECHECK_LOAD_ORDER():
    """sf_racecheck reads a whole load order, and the latest override of a record wins.

    Two ways to say what to load:
      * --plugin P: P and every master it needs, RECURSIVELY. A patch that names only the mod
        as its master still needs the mod's own master, or nothing the mod overrides resolves.
      * no --plugin: the game's active load order from Plugins.txt, implicit masters first.

    And every lookup -- --race included -- goes by the winning override across that whole
    order. Before this, the race had to live in --plugin itself, so a player plugin that only
    overrides a race defined elsewhere could not be checked at all.

    The plugins are tiny ones built here with esplib: a race in a master, overridden by a mod,
    then by a second mod later in the load order. Each copy marks itself in FCTP. They are
    written in Fallout 4's record format because esplib has no Starfield writer; this test is
    about load order and overrides, which work the same way, not about record layouts.
    """
    import tempfile
    import sf_racecheck
    from esplib import Plugin, Record
    from esplib.utils import FormID

    def write(d, name, masters, race_mark, is_esm=False, extra=None):
        p = Plugin.new_plugin(os.path.join(d, name), masters=masters, game='fo4', is_esm=is_esm)
        if race_mark is not None:
            if masters:
                # An override: the race's formID in its master's index slot (master 0).
                rec = Record('RACE', FormID(0x000800))
                rec.add_subrecord('EDID', 'RCTestRace')
                p.add_record(rec)
            else:
                rec = p.new_record('RACE', 'RCTestRace', form_id=0x800)
            rec.add_subrecord('FCTP', race_mark.encode('cp1252') + b'\0')
        if extra:
            extra(p)
        p.save_as(os.path.join(d, name))

    def mark(rec):
        return sf_racecheck.text(rec, 'FCTP')

    with tempfile.TemporaryDirectory() as d:
        write(d, 'RCMaster.esm', [], 'master', is_esm=True)
        write(d, 'RCMod.esm', ['RCMaster.esm'], 'mod', is_esm=True)
        # The patch names ONLY the mod -- RCMaster must be found through RCMod's header.
        write(d, 'RCPatch.esp', ['RCMod.esm'], None,
              extra=lambda p: p.new_record('GLOB', 'RCPatchMarker'))
        write(d, 'RCOther.esp', ['RCMaster.esm'], 'other')

        # --- --plugin: the plugin and its masters, recursively, masters first ----------
        order = sf_racecheck.load_order_names([d], plugin='RCPatch.esp')
        assert TT.is_eq(order, ['RCMaster.esm', 'RCMod.esm', 'RCPatch.esp'],
                        "the patch's masters, found recursively")
        rep = sf_racecheck.Report()
        plugins = sf_racecheck.load_plugins(rep, [d], order)
        race = sf_racecheck.find_race(plugins, 'RCTestRace')
        assert race is not None, "a race defined in a master is found by EDID"
        assert TT.is_eq(mark(race), 'mod', "the latest override in this order wins")

        # --- no --plugin: the active load order from Plugins.txt -------------------------
        txt = os.path.join(d, 'Plugins.txt')
        with open(txt, 'w', encoding='utf-8') as f:
            f.write("# a comment\n*RCMaster.esm\n*RCMod.esm\nRCDisabled.esp\n"
                    "*RCPatch.esp\n*RCOther.esp\n")
        order = sf_racecheck.load_order_names([d], plugins_txt=txt)
        assert TT.is_eq(order[0], 'Starfield.esm', "the implicit master leads")
        assert TT.is_eq(order[1:], ['RCMaster.esm', 'RCMod.esm', 'RCPatch.esp', 'RCOther.esp'],
                        "active plugins in Plugins.txt order; inactive ones left out")
        rep = sf_racecheck.Report()
        plugins = sf_racecheck.load_plugins(rep, [d], order)
        race = sf_racecheck.find_race(plugins, 'RCTestRace')
        assert TT.is_eq(mark(race), 'other', "the last plugin to override the race wins")

        # Every winning RACE, once each, however many plugins override it.
        races = sf_racecheck.winning_records(plugins, 'RACE')
        assert TT.is_eq([mark(r) for r in races], ['other'], "one winner per record")

        # CONTROL: an EDID nobody defines is not found.
        assert sf_racecheck.find_race(plugins, 'NoSuchRace') is None, "unknown race -> None"


def TEST_SF_RACECHECK_AVM_GROUPS():
    """sf_racecheck checks every AVMD group a mod defines or overrides: each entry of a Complex
    group must name a group that exists, and each texture a Simple group names must exist.

    These are global lists found by name, so a broken entry fails silently for everyone. Bad
    Dog's override of ComplexGroup_PostBlendFaceCustomizationLayers pointed the Dermaesthetic
    slot at SimpleGroup_FSFFoxDermaesthetic, which no plugin defines.

    Vanilla ships 4 of the stack's 26 entries unresolvable (TattooColorMap, ...), so an entry
    the same group's vanilla copy also can't resolve is not the mod's fault: noted, not failed.
    Textures only vanilla's own records name are in BA2s and aren't looked for."""
    import tempfile
    import sf_racecheck as R
    from esplib import Plugin

    TEX = 'textures/actors/rctest/present_color.dds'

    def group(p, edid, kind, name, entries):
        rec = p.new_record('AVMD', edid)
        rec.add_subrecord('MNAM', kind.to_bytes(4, 'little'))
        rec.add_subrecord('TNAM', name.encode() + b'\0')
        for key, target in entries:
            rec.add_subrecord('LNAM', key.encode() + b'\0')
            if target is not None:
                rec.add_subrecord('VNAM', target.encode() + b'\0')

    def findings(rep, level):
        return [m + ' ' + str(d) for lv, _a, m, d in rep.findings if lv == level]

    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, *TEX.split('/')[:-1]))
        open(os.path.join(d, *TEX.split('/')), 'wb').close()

        base = Plugin.new_plugin(os.path.join(d, 'RCBase.esm'), masters=[], game='fo4',
                                 is_esm=True)
        group(base, 'SimpleGroup_Dermaesthetic', R.AVM_SIMPLE, 'Dermaesthetic',
              [('derm_vanilla', 'textures/actors/human/in_a_ba2_color.dds')])
        group(base, 'ComplexGroup_Stack', R.AVM_COMPLEX, 'Stack',
              [('Dermaesthetic', 'SimpleGroup_Dermaesthetic'),
               ('TattooTint', 'SimpleGroup_TattooTint')])           # broken in "vanilla" too
        base.save_as(os.path.join(d, 'RCBase.esm'))

        mod = Plugin.new_plugin(os.path.join(d, 'RCMod.esm'), masters=['RCBase.esm'],
                                game='fo4', is_esm=True)
        group(mod, 'ComplexGroup_Stack', R.AVM_COMPLEX, 'Stack',     # replaces it by name
              [('Dermaesthetic', 'SimpleGroup_FoxDermaesthetic'),     # the mod's own break
               ('TattooTint', 'SimpleGroup_TattooTint'),
               ('Complexion1', None)])                                # no VNAM: by LNAM
        group(mod, 'SimpleGroup_Complexion1', R.AVM_SIMPLE, 'Complexion1',
              [('present', TEX), ('gone', 'textures/actors/rctest/gone_color.dds'),
               ('vanilla_path', 'textures/actors/human/in_a_ba2_color.dds')])
        group(mod, 'ComplexGroup_Good', R.AVM_COMPLEX, 'Good',
              [('a', 'SimpleGroup_Complexion1'), ('b', 'SimpleGroup_Dermaesthetic')])
        mod.save_as(os.path.join(d, 'RCMod.esm'))

        rep = R.Report()
        plugins = R.load_plugins(rep, [d], ['RCBase.esm', 'RCMod.esm'])
        official = {'rcbase.esm'}
        own = [r for r in R.winning_records(plugins, 'AVMD') if R.plugin_name(r) not in official]
        r = R.Report()
        R.check_avm_groups(r, [d], plugins, own, official)

        fails = findings(r, R.FAIL)
        assert TT.is_eq(len(fails), 2, f"two problems the mod made: {fails}")
        assert TT.is_true(any('SimpleGroup_FoxDermaesthetic' in f and 'Stack' in f
                              and 'SimpleGroup_Dermaesthetic' in f for f in fails),
                          f"the broken stack entry, and what vanilla has there: {fails}")
        assert TT.is_true(any('gone_color.dds' in f for f in fails),
                          f"the Simple group's missing texture: {fails}")
        allfound = ' '.join(findings(r, R.FAIL) + findings(r, R.WARN))
        assert TT.is_true('TattooTint' not in allfound,
                          "an entry vanilla's copy can't resolve either is not the mod's fault")
        assert TT.is_true('in_a_ba2' not in allfound, "a texture vanilla names is in a BA2")
        assert TT.is_true('Good' not in allfound, "a group whose entries all resolve is clean")


def TEST_SF_RACECHECK_AVM_VNAM_IS_EDID():
    """A Complex entry's VNAM names its target group by EDITOR ID, not by '<Kind>_' + TNAM.

    Vanilla can't tell the two apart: its EDIDs are always '<Kind>_' + TNAM where anything points
    at them. Bad Dog's fox dermaesthetic filter pointed at SimpleGroup_..._SkinTone1..9 -- the
    TNAMs -- while the groups' EDIDs were zero-padded ...SkinTone01..09. In game, tones 2-10
    had no dermaesthetic options at all, while 1 and 11-13 (whose EDIDs matched) did; pointing
    the filter at the EDIDs fixed every tone. sf_racecheck passed it, resolving by TNAM."""
    import tempfile
    import sf_racecheck as R
    from esplib import Plugin

    def group(p, edid, kind, name, entries):
        rec = p.new_record('AVMD', edid)
        rec.add_subrecord('MNAM', kind.to_bytes(4, 'little'))
        rec.add_subrecord('TNAM', name.encode() + b'\0')
        for key, target in entries:
            rec.add_subrecord('LNAM', key.encode() + b'\0')
            rec.add_subrecord('VNAM', target.encode() + b'\0')

    with tempfile.TemporaryDirectory() as d:
        p = Plugin.new_plugin(os.path.join(d, 'RCMod.esm'), masters=[], game='fo4', is_esm=True)
        group(p, 'SimpleGroup_chargen_FoxDermTone0', R.AVM_SIMPLE, 'chargen_FoxDermTone0', [])
        group(p, 'SimpleGroup_chargen_FoxDermTone01', R.AVM_SIMPLE, 'chargen_FoxDermTone1', [])
        group(p, 'ComplexGroup_Chargen_Dermaesthetic', R.AVM_COMPLEX, 'Chargen_Dermaesthetic',
              [('chargen_DermaestheticSkinTone0', 'SimpleGroup_chargen_FoxDermTone0'),
               ('chargen_DermaestheticSkinTone1', 'SimpleGroup_chargen_FoxDermTone1')])  # TNAM
        p.save_as(os.path.join(d, 'RCMod.esm'))

        rep = R.Report()
        plugins = R.load_plugins(rep, [d], ['RCMod.esm'])
        avm = R.avm_index(plugins)
        filt = avm[(R.AVM_COMPLEX, 'Chargen_Dermaesthetic')]

        kids = R.complex_children(filt, avm)
        assert TT.is_eq(kids['chargen_DermaestheticSkinTone0'].editor_id,
                        'SimpleGroup_chargen_FoxDermTone0', "EDID == <Kind>_TNAM resolves")
        assert TT.is_true(kids['chargen_DermaestheticSkinTone1'] is None,
                          "a VNAM naming only the target's TNAM resolves to nothing")

        r = R.Report()
        R.check_avm_groups(r, [d], plugins, R.winning_records(plugins, 'AVMD'), set())
        fails = [m + ' ' + str(det) for lv, _a, m, det in r.findings if lv == R.FAIL]
        assert TT.is_eq(len(fails), 1, f"one broken filter entry: {fails}")
        assert TT.is_true('chargen_DermaestheticSkinTone1' in fails[0]
                          and 'SimpleGroup_chargen_FoxDermTone01' in fails[0],
                          f"names the entry and the EDID it should use: {fails}")


def TEST_SF_RACECHECK_FACE_TEXTURE_SIZES():
    """sf_racecheck fails a face whose textures aren't all one size.

    The creator re-composites the face whenever a tint layer changes, from the race's FCTP base
    maps and the tint options the stack's slots offer. Bad Dog, in game 2026-10-18: base maps
    and overlays at mixed sizes turned the face black on the first dermaesthetic change; all at
    1024 worked, and all at 2048 worked too. So the rule is one size, any size -- vanilla's are
    all 1024 only because they match. An option in a stack slot's Chargen_ twin counts too."""
    import struct
    import tempfile
    import sf_racecheck as R
    from esplib import Plugin

    FCTP = 'actors/rc/faces/chargen'

    def dds(d, rel, size):
        path = os.path.join(d, *rel.split('/'))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        head = bytearray(128)
        head[:4] = b'DDS '
        struct.pack_into('<5I', head, 4, 124, 0, size, size, 0)    # size, flags, height, width
        open(path, 'wb').write(bytes(head))

    def group(p, edid, kind, name, entries):
        rec = p.new_record('AVMD', edid)
        rec.add_subrecord('MNAM', kind.to_bytes(4, 'little'))
        rec.add_subrecord('TNAM', name.encode() + b'\0')
        for key, target in entries:
            rec.add_subrecord('LNAM', key.encode() + b'\0')
            rec.add_subrecord('VNAM', target.encode() + b'\0')

    def run(d, derm_size, chargen_size):
        for m in ('sk0_color', 'normal', 'rough', 'ao'):
            dds(d, f'textures/{FCTP}/male_rc_md1_{m}.dds', 2048)
        dds(d, 'textures/actors/rc/derm/a_derm_color.dds', derm_size)
        dds(d, 'textures/actors/rc/derm/b_derm_color.dds', chargen_size)
        p = Plugin.new_plugin(os.path.join(d, 'RCFace.esm'), masters=[], game='fo4', is_esm=True)
        group(p, 'ComplexGroup_Stack', R.AVM_COMPLEX, R.STACK_TNAM,
              [('Dermaesthetic', 'SimpleGroup_Dermaesthetic')])
        group(p, 'SimpleGroup_Dermaesthetic', R.AVM_SIMPLE, 'Dermaesthetic',
              [('a', 'textures/actors/rc/derm/a_derm_color.dds')])
        group(p, 'SimpleGroup_Chargen_Dermaesthetic', R.AVM_SIMPLE, 'Chargen_Dermaesthetic',
              [('b', 'textures/actors/rc/derm/b_derm_color.dds')])
        p.save_as(os.path.join(d, 'RCFace.esm'))
        plugins = R.load_plugins(R.Report(), [d], ['RCFace.esm'])
        rep = R.Report()
        R.check_face_texture_sizes(rep, [d], FCTP, R.avm_index(plugins))
        return rep

    with tempfile.TemporaryDirectory() as d:
        rep = run(d, 2048, 2048)
        assert TT.is_eq([f for f in rep.findings if f[0] == R.FAIL], [],
                        "base maps and options all 2048: clean")
    with tempfile.TemporaryDirectory() as d:
        rep = run(d, 4096, 2048)
        fails = [m + ' ' + str(dt) for lv, _a, m, dt in rep.findings if lv == R.FAIL]
        assert TT.is_eq(len(fails), 1, f"a 4096 dermaesthetic among 2048 base maps: {fails}")
        assert TT.is_true("SimpleGroup_Dermaesthetic (" in fails[0] and '4096' in fails[0]
                          and '2048' in fails[0],
                          f"names the group, its size, and the face maps' size: {fails}")
    with tempfile.TemporaryDirectory() as d:
        rep = run(d, 2048, 1024)
        fails = [m + ' ' + str(dt) for lv, _a, m, dt in rep.findings if lv == R.FAIL]
        assert TT.is_true(fails and 'SimpleGroup_Chargen_Dermaesthetic' in fails[0],
                          f"an option offered only through the Chargen_ twin counts: {fails}")
    with tempfile.TemporaryDirectory() as d:
        dds(d, f'textures/{FCTP}/female_rc_md1_normal.dds', 1024)
        rep = run(d, 2048, 2048)
        fails = [m + ' ' + str(dt) for lv, _a, m, dt in rep.findings if lv == R.FAIL]
        assert TT.is_true(any('FCTP' in f and 'normal' in f for f in fails),
                          f"the race's own face maps must agree with each other: {fails}")


def TEST_SF_RACECHECK_FOLLICLE_MASK():
    """sf_racecheck checks that a hair or beard head part's NAM3 mask resolves to a texture.

    NAM3 is not a filename. It is a KEY: the Simple AVMD group `HairFollicleMask` (hair, PNAM
    3) or `BeardFollicleMask` (facial hair, PNAM 4) lists `LNAM key / VNAM texture path`
    pairs, and the engine looks the part's NAM3 up there. A mask that's only a .dds on disk
    -- however vanilla-like its folder and name -- does nothing. That's how FSFFox's
    `JawRuff_mask` silently failed.

    Vanilla extends a group without overriding it: Shattered Space adds a separate Simple
    group `HairFollicleMask_AVMDEXT`, and its DLC hair parts' keys resolve ONLY there. So
    `<group>_AVMDEXT` counts as part of the group.

    Measured over every vanilla hair/beard part: 115 NAM3 keys, all exact-case matches, all
    in the group for their part type. Eyebrows (PNAM 6) use NAM3 for a colour group instead,
    and are left alone.
    """
    import tempfile
    import sf_racecheck
    from esplib import Plugin

    HAIR, BEARD, BROW = 3, 4, 6
    MASK_REL = 'textures/actors/rctest/scalp/present_mask.dds'

    def group(p, edid, name, entries):
        rec = p.new_record('AVMD', edid)
        rec.add_subrecord('MNAM', (1).to_bytes(4, 'little'))      # Simple
        rec.add_subrecord('TNAM', name.encode() + b'\0')
        for key, path in entries:
            rec.add_subrecord('LNAM', key.encode() + b'\0')
            rec.add_subrecord('VNAM', path.encode() + b'\0')

    def part(p, edid, pnam, nam3):
        rec = p.new_record('HDPT', edid)
        rec.add_subrecord('PNAM', pnam.to_bytes(4, 'little'))
        if nam3 is not None:
            rec.add_subrecord('NAM3', nam3.encode() + b'\0')

    def findings(rep, level):
        return [(m, d) for lv, _area, m, d in rep.findings if lv == level]

    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, *MASK_REL.split('/')[:-1]))
        open(os.path.join(d, *MASK_REL.split('/')), 'wb').close()

        p = Plugin.new_plugin(os.path.join(d, 'RCHair.esm'), masters=[], game='fo4',
                              is_esm=True)
        group(p, 'SimpleGroup_HairFollicleMask', 'HairFollicleMask',
              [('Hair_Present_Mask', MASK_REL), ('Hair_Missing_Mask', 'textures/rctest/gone.dds'),
               ('Hair_WrongGroup_Mask', MASK_REL)])
        group(p, 'SimpleGroup_BeardFollicleMask_AVMDEXT', 'BeardFollicleMask_AVMDEXT',
              [('Beard_Ext_Mask', MASK_REL)])
        part(p, 'RCHairGood', HAIR, 'Hair_Present_Mask')
        part(p, 'RCBeardViaExt', BEARD, 'Beard_Ext_Mask')
        part(p, 'RCHairNoFile', HAIR, 'Hair_Missing_Mask')
        part(p, 'RCBeardWrongGroup', BEARD, 'Hair_WrongGroup_Mask')
        part(p, 'RCBeardUnlisted', BEARD, 'JawRuff_mask')
        part(p, 'RCHairCase', HAIR, 'hair_present_mask')
        part(p, 'RCHairNone', HAIR, ' NONE')
        part(p, 'RCHairNoNam3', HAIR, None)
        part(p, 'RCBrow', BROW, 'EyebrowColor')
        p.save_as(os.path.join(d, 'RCHair.esm'))

        rep = sf_racecheck.Report()
        plugins = sf_racecheck.load_plugins(rep, [d], ['RCHair.esm'])
        avm = sf_racecheck.avm_index(plugins)
        parts = {h.editor_id: h for h in sf_racecheck.winning_records(plugins, 'HDPT')}

        def check(edid):
            r = sf_racecheck.Report()
            sf_racecheck.check_follicle_mask(r, [d], parts[edid], avm, official=set())
            return r

        r = check('RCHairGood')
        assert TT.is_eq(findings(r, sf_racecheck.FAIL) + findings(r, sf_racecheck.WARN), [],
                        "a hair key in HairFollicleMask with its texture on disk is clean")
        r = check('RCBeardViaExt')
        assert TT.is_eq(findings(r, sf_racecheck.FAIL) + findings(r, sf_racecheck.WARN), [],
                        "a beard key found only in BeardFollicleMask_AVMDEXT resolves")

        r = check('RCBeardUnlisted')
        fails = findings(r, sf_racecheck.FAIL)
        assert TT.is_eq(len(fails), 1, "a NAM3 key no group lists is a FAIL")
        assert 'JawRuff_mask' in fails[0][0] and 'BeardFollicleMask' in str(fails[0]), \
            f"the failure names the key and the group to add it to: {fails}"

        r = check('RCBeardWrongGroup')
        fails = findings(r, sf_racecheck.FAIL)
        assert TT.is_eq(len(fails), 1, "a beard key listed only in the HAIR group is a FAIL")
        assert 'HairFollicleMask' in str(fails[0]), \
            f"the failure says where the key actually is: {fails}"

        r = check('RCHairNoFile')
        fails = findings(r, sf_racecheck.FAIL)
        assert TT.is_eq(len(fails), 1, "a mod's mask entry pointing at a missing file is a FAIL")
        assert 'textures/rctest/gone.dds' in str(fails[0]), f"names the missing path: {fails}"

        r = check('RCHairCase')
        assert TT.is_eq(len(findings(r, sf_racecheck.FAIL)), 0, "case-only match isn't a FAIL")
        assert TT.is_eq(len(findings(r, sf_racecheck.WARN)), 1,
                        "but vanilla always matches case exactly, so it's a WARN")

        for edid in ('RCHairNone', 'RCHairNoNam3', 'RCBrow'):
            r = check(edid)
            assert TT.is_eq(r.findings, [], f"{edid}: no mask to check, nothing reported")

    # CONTROL, on the real game: every vanilla hair and beard part resolves, the Shattered
    # Space ones through HairFollicleMask_AVMDEXT. Vanilla textures are in BA2s, so the
    # official plugins' entries are not looked for on disk.
    if os.path.exists(os.path.join(TT.SF_DATA, 'Starfield.esm')):
        order = ['Starfield.esm'] + sf_racecheck.OFFICIAL_MASTERS
        rep = sf_racecheck.Report()
        plugins = sf_racecheck.load_plugins(rep, [TT.SF_DATA], order)
        avm = sf_racecheck.avm_index(plugins)
        official = sf_racecheck.official_plugins(order)
        checked = 0
        for h in sf_racecheck.winning_records(plugins, 'HDPT'):
            r = sf_racecheck.Report()
            sf_racecheck.check_follicle_mask(r, [TT.SF_DATA], h, avm, official)
            assert TT.is_eq(findings(r, sf_racecheck.FAIL) + findings(r, sf_racecheck.WARN),
                            [], f"vanilla {h.editor_id} is clean")
            checked += bool(r.findings)
        assert TT.is_ge(checked, 115, "every vanilla hair/beard mask was actually checked")


def TEST_SF_RACECHECK_COLOR_KEYS():
    """sf_racecheck checks a hair or beard colour group's keys against the vanilla colour names.

    A part's NAM2 names a Simple AVMD group of colours. Bad Dog's fox beard group had White,
    Platinum and Aqua: the first two rendered, Aqua rendered black. Changing its path from
    backslashes to forward slashes did nothing; renaming the key to AquaPurple fixed it, with
    the same texture. Platinum points at his own texture, so the key matters and the texture
    doesn't. Vanilla's Modulation_FacialHair_Shared is the reference list.
    """
    import tempfile
    import sf_racecheck
    from esplib import Plugin

    HAIR, BEARD, BROW = 3, 4, 6
    TEX = 'textures/rctest/colour.dds'

    def simple(p, name, keys):
        rec = p.new_record('AVMD', 'SimpleGroup_' + name)
        rec.add_subrecord('MNAM', (1).to_bytes(4, 'little'))
        rec.add_subrecord('TNAM', name.encode() + b'\0')
        for key in keys:
            rec.add_subrecord('LNAM', key.encode() + b'\0')
            rec.add_subrecord('VNAM', TEX.encode() + b'\0')

    def part(p, edid, pnam, nam2):
        rec = p.new_record('HDPT', edid)
        rec.add_subrecord('PNAM', pnam.to_bytes(4, 'little'))
        rec.add_subrecord('NAM2', nam2.encode() + b'\0')

    def findings(rep, level):
        return [(m, d) for lv, _area, m, d in rep.findings if lv == level]

    with tempfile.TemporaryDirectory() as d:
        p = Plugin.new_plugin(os.path.join(d, 'RCColor.esm'), masters=[], game='fo4', is_esm=True)
        mod = p.new_record('AVMD', 'Modulation_FacialHair_Shared')
        mod.add_subrecord('MNAM', (3).to_bytes(4, 'little'))
        mod.add_subrecord('TNAM', b'FacialHair_Shared\0')
        for key in ('White', 'Platinum', 'AquaPurple'):
            mod.add_subrecord('LNAM', key.encode() + b'\0')
            mod.add_subrecord('NNAM', (0).to_bytes(4, 'little'))
        simple(p, 'RCBeardGood', ['White', 'Platinum', 'AquaPurple'])
        simple(p, 'RCBeardBad', ['White', 'Platinum', 'Aqua'])
        simple(p, 'RCHairBad', ['Mauve'])
        simple(p, 'RCBeardCase', ['aquapurple'])
        simple(p, 'RCBrowOdd', ['Mauve'])
        part(p, 'RCGood', BEARD, 'RCBeardGood')
        part(p, 'RCBad1', BEARD, 'RCBeardBad')
        part(p, 'RCBad2', BEARD, 'RCBeardBad')
        part(p, 'RCHair', HAIR, 'RCHairBad')
        part(p, 'RCCase', BEARD, 'RCBeardCase')
        part(p, 'RCBrow', BROW, 'RCBrowOdd')
        part(p, 'RCNoGroup', BEARD, 'RCNoSuchGroup')
        p.save_as(os.path.join(d, 'RCColor.esm'))

        rep = sf_racecheck.Report()
        plugins = sf_racecheck.load_plugins(rep, [d], ['RCColor.esm'])
        avm = sf_racecheck.avm_index(plugins)
        parts = {h.editor_id: h for h in sf_racecheck.winning_records(plugins, 'HDPT')}

        def check(*edids, index=avm, official=frozenset()):
            r = sf_racecheck.Report()
            sf_racecheck.check_color_keys(r, [parts[e] for e in edids], index, official)
            return r

        r = check('RCGood')
        assert TT.is_eq(findings(r, sf_racecheck.FAIL) + findings(r, sf_racecheck.WARN), [],
                        "a group using only listed keys is clean")

        r = check('RCBad1', 'RCBad2')
        fails = findings(r, sf_racecheck.FAIL)
        assert TT.is_eq(len(fails), 1, "a bad key is reported once, however many parts share it")
        assert "'Aqua'" in fails[0][0] and 'RCBeardBad' in fails[0][0], \
            f"the failure names the key and the group: {fails}"
        assert 'Modulation_FacialHair_Shared' in str(fails[0]), f"names the list: {fails}"
        assert 'RCBad1' in str(fails[0]) and 'RCBad2' in str(fails[0]), f"names the parts: {fails}"

        r = check('RCHair')
        assert TT.is_eq(len(findings(r, sf_racecheck.FAIL)), 1, "hair uses the same list")

        r = check('RCCase')
        assert TT.is_eq(len(findings(r, sf_racecheck.FAIL)), 0, "case-only match isn't a FAIL")
        assert TT.is_eq(len(findings(r, sf_racecheck.WARN)), 1, "but it is a WARN")

        r = check('RCBrow')
        assert TT.is_eq(r.findings, [], "eyebrows aren't covered")

        r = check('RCBad1', official={'rccolor.esm'})
        assert TT.is_eq(findings(r, sf_racecheck.FAIL), [], "the game's own groups aren't judged")

        r = check('RCNoGroup')
        warns = findings(r, sf_racecheck.WARN)
        assert TT.is_eq(len(warns), 1, "a NAM2 naming no Simple group can't be checked: WARN")
        assert 'RCNoSuchGroup' in warns[0][0], f"the warning names the group: {warns}"

        without = {k: v for k, v in avm.items() if k[0] != sf_racecheck.AVM_MODULATION}
        r = check('RCBad1', 'RCHair', index=without)
        assert TT.is_eq(findings(r, sf_racecheck.FAIL), [], "no reference list, nothing to fail")
        assert TT.is_eq(len(findings(r, sf_racecheck.WARN)), 1, "says so once")

    # CONTROL, on the real game: every vanilla hair and beard part's group passes, judged as if
    # it were a mod's.
    if os.path.exists(os.path.join(TT.SF_DATA, 'Starfield.esm')):
        order = ['Starfield.esm'] + sf_racecheck.OFFICIAL_MASTERS
        rep = sf_racecheck.Report()
        plugins = sf_racecheck.load_plugins(rep, [TT.SF_DATA], order)
        avm = sf_racecheck.avm_index(plugins)
        r = sf_racecheck.Report()
        sf_racecheck.check_color_keys(r, sf_racecheck.winning_records(plugins, 'HDPT'), avm, set())
        assert TT.is_eq(findings(r, sf_racecheck.FAIL) + findings(r, sf_racecheck.WARN), [],
                        "vanilla hair and beard colour groups are clean")
        assert TT.is_ge(len(findings(r, sf_racecheck.OK)), 9, "vanilla groups were really checked")


def TEST_SF_RACECHECK_PART_MORPHS():
    """sf_racecheck checks every head part's morphs, not just the face's.

    A morph.dat whose keys are all empty has zero records and crashes the CK
    (MorphRenderPass "invalid buffers"); FSFFox_Ruff01 shipped one and nothing caught it, because
    only the race's Face part was checked. Some empty keys among real ones are normal on a
    beard or hair (vanilla beards have 9+), so those aren't reported.
    """
    import tempfile
    import sf_racecheck
    from esplib import Plugin
    from pyn.sf_morph import MorphFile

    BEARD, FACE = 4, 1

    def morph(d, rel, names, deltas):
        full = os.path.join(d, *rel.split('\\'))
        os.makedirs(full)
        MorphFile.from_deltas(names, 4, deltas).to_file(os.path.join(full, 'morph.dat'))

    def part(p, edid, pnam, chargen=None, perf=None):
        rec = p.new_record('HDPT', edid)
        rec.add_subrecord('PNAM', pnam.to_bytes(4, 'little'))
        if chargen or perf:
            m = p.new_record('MRPH', edid + 'Morph')
            if chargen:
                m.add_subrecord('TCMP', chargen.encode() + b'\0')
            if perf:
                m.add_subrecord('TMPP', perf.encode() + b'\0')
            rec.add_subrecord('MNAM', m.form_id.value.to_bytes(4, 'little'))

    def findings(rep, level):
        return [(m, dt) for lv, _area, m, dt in rep.findings if lv == level]

    real = {'jawOpen': {0: (0.0, 0.0, 1.0)}}
    with tempfile.TemporaryDirectory() as d:
        morph(d, 'Meshes\\Morphs\\RC\\chargen\\Empty', ['Overweight', 'Thin'], {})
        morph(d, 'Meshes\\Morphs\\RC\\performance\\Partial', ['jawOpen', 'lipPress'], real)
        morph(d, 'Meshes\\Morphs\\RC\\chargen\\Partial', ['Overweight', 'Thin'],
              {'Thin': {1: (1.0, 0.0, 0.0)}})
        os.makedirs(os.path.join(d, 'Meshes', 'Morphs', 'RC', 'chargen', 'NoDat'))

        p = Plugin.new_plugin(os.path.join(d, 'RCMorph.esm'), masters=[], game='fo4',
                              is_esm=True)
        part(p, 'RCRuffEmpty', BEARD, chargen='Meshes\\Morphs\\RC\\chargen\\Empty',
             perf='Meshes\\Morphs\\RC\\performance\\Partial')
        part(p, 'RCRuffPartial', BEARD, chargen='Meshes\\Morphs\\RC\\chargen\\Partial',
             perf='Meshes\\Morphs\\RC\\performance\\Partial')
        part(p, 'RCRuffNoDat', BEARD, chargen='Meshes\\Morphs\\RC\\chargen\\NoDat')
        part(p, 'RCRuffNoMorph', BEARD)
        part(p, 'RCFace', FACE, chargen='Meshes\\Morphs\\RC\\chargen\\Empty')
        p.save_as(os.path.join(d, 'RCMorph.esm'))

        rep = sf_racecheck.Report()
        plugins = sf_racecheck.load_plugins(rep, [d], ['RCMorph.esm'])
        parts = {h.editor_id: h for h in sf_racecheck.winning_records(plugins, 'HDPT')}

        def check(edid):
            r = sf_racecheck.Report()
            sf_racecheck.check_part_morphs(r, [d], parts[edid], plugins)
            return r

        r = check('RCRuffEmpty')
        fails = findings(r, sf_racecheck.FAIL)
        assert TT.is_eq(len(fails), 1, f"a zero-record chargen morph.dat is one FAIL: {fails}")
        assert 'RCRuffEmpty' in str(fails[0]) and 'CK' in str(fails[0]), \
            f"the failure names the part and says it crashes the CK: {fails}"

        r = check('RCRuffPartial')
        assert TT.is_eq(findings(r, sf_racecheck.FAIL) + findings(r, sf_racecheck.WARN), [],
                        "some empty keys among real ones are normal on a beard")

        r = check('RCRuffNoDat')
        fails = findings(r, sf_racecheck.FAIL)
        assert TT.is_eq(len(fails), 1, f"a TCMP folder with no morph.dat is a FAIL: {fails}")

        for quiet in ('RCRuffNoMorph', 'RCFace'):
            r = check(quiet)
            assert TT.is_eq(r.findings, [], f"{quiet}: nothing to check here "
                                            f"(no morph; the face has its own check)")

        # The face's own check catches a zero-record file too, not only its empty keys.
        r = sf_racecheck.Report()
        sf_racecheck.check_morphs(r, [d], plugins.resolve_reference(parts['RCFace'], 'MNAM'),
                                  None, None)
        assert 'CK' in str(findings(r, sf_racecheck.FAIL)), \
            f"the face's zero-record morph.dat says it crashes the CK: {r.findings}"

        # A face with SOME empty keys renders: the fox heads ship 2 empty squint keys and are
        # visible. Only a zero-record file was ever proven fatal. Warn, naming the keys.
        face = p.new_record('MRPH', 'RCFacePartialMorph')
        face.add_subrecord('TCMP', b'Meshes\\Morphs\\RC\\chargen\\Partial\0')
        face.add_subrecord('TMPP', b'Meshes\\Morphs\\RC\\performance\\Partial\0')
        r = sf_racecheck.Report()
        sf_racecheck.check_morphs(r, [d], face, None, None)
        assert TT.is_eq(findings(r, sf_racecheck.FAIL), [],
                        "some empty keys on a face are not a failure")
        w = str(findings(r, sf_racecheck.WARN))
        assert 'lipPress' in w and 'Overweight' in w and 'INVISIBLE' not in w, \
            f"one warning per file naming the empty keys, without the invisibility claim: {w}"


def TEST_SF_RACECHECK_CHARGEN_OPTIONS():
    """sf_racecheck warns about a playable head part chargen never offers.

    The creator lists only what's on HeadPartsChargenOptionsMale [FLST:0003D9AF] / ...Female
    [0003D9B0]; a part's own Valid Races list just says who may wear it. FSFFox_Male_Ruff04
    rendered fine and couldn't be picked, because it wasn't on the male list. Extra parts (pulled
    in by another part) and types the creator doesn't list (faces, teeth) aren't expected there.
    """
    import tempfile
    import sf_racecheck
    from esplib import Plugin

    HAIR, BEARD, FACE = 3, 4, 1
    PLAYABLE, MALE, FEMALE, EXTRA = 0x01, 0x02, 0x04, 0x10

    def part(p, edid, pnam, flags):
        rec = p.new_record('HDPT', edid)
        rec.add_subrecord('DATA', bytes([flags]))
        rec.add_subrecord('PNAM', pnam.to_bytes(4, 'little'))
        return rec

    def warns(rep):
        return [(m, d) for lv, _area, m, d in rep.findings if lv == sf_racecheck.WARN]

    with tempfile.TemporaryDirectory() as d:
        p = Plugin.new_plugin(os.path.join(d, 'RCOpts.esm'), masters=[], game='fo4', is_esm=True)
        listed = part(p, 'RCRuffListed', BEARD, PLAYABLE | MALE)
        part(p, 'RCRuffUnlisted', BEARD, PLAYABLE | MALE)
        part(p, 'RCHairFemUnlisted', HAIR, PLAYABLE | FEMALE)
        part(p, 'RCRuffXP', BEARD, PLAYABLE | MALE | EXTRA)
        part(p, 'RCRuffNotPlayable', BEARD, MALE)
        part(p, 'RCFace', FACE, PLAYABLE | MALE)
        male = p.new_record('FLST', 'HeadPartsChargenOptionsMale')
        male.add_subrecord('LNAM', listed.form_id.value.to_bytes(4, 'little'))
        p.new_record('FLST', 'HeadPartsChargenOptionsFemale')
        p.save_as(os.path.join(d, 'RCOpts.esm'))

        rep = sf_racecheck.Report()
        plugins = sf_racecheck.load_plugins(rep, [d], ['RCOpts.esm'])
        parts = sf_racecheck.winning_records(plugins, 'HDPT')

        r = sf_racecheck.Report()
        sf_racecheck.check_chargen_options(r, parts, plugins)
        w = warns(r)
        assert TT.is_eq(len(w), 2, f"one warning per sex with something missing: {w}")
        text = str(w)
        assert 'RCRuffUnlisted' in text and 'HeadPartsChargenOptionsMale' in text, text
        assert 'RCHairFemUnlisted' in text and 'HeadPartsChargenOptionsFemale' in text, text
        for quiet in ('RCRuffListed', 'RCRuffXP', 'RCRuffNotPlayable', 'RCFace'):
            assert quiet not in text, f"{quiet} isn't expected on the list: {text}"

        r = sf_racecheck.Report()
        sf_racecheck.check_chargen_options(r, parts, plugins, sexes=('MALE',))
        assert 'RCHairFemUnlisted' not in str(warns(r)), "--sex male leaves the female list alone"


def TEST_SF_RACECHECK_PHENOTYPE_MAPS():
    """sf_racecheck names the missing face maps of a non-default phenotype.

    Each phenotype needs <phenotype>_normal/_rough/_ao.dds in the race's FCTP folder, found by
    filename only. The warning used to say only "3 map(s) missing ... 1 phenotypes affected",
    which left the user to work out which phenotype and which files (FSFFox's fennec)."""
    import tempfile
    import sf_racecheck
    from esplib import Plugin

    fctp = r'actors\rctest\faces\chargen'
    with tempfile.TemporaryDirectory() as d:
        face = os.path.join(d, 'textures', *fctp.split('\\'))
        os.makedirs(face)
        have = [f"{p}{s}" for p in ('male_default', 'male_fox_md1')
                for s in sf_racecheck.FCTP_SUFFIXES]
        have += ['male_fennec_md1_rough.dds', 'FCT_null_mask.dds']
        for f in have:
            open(os.path.join(face, f), 'wb').close()

        p = Plugin.new_plugin(os.path.join(d, 'RCFace.esm'), masters=[], game='fo4', is_esm=True)
        rec = p.new_record('RACE', 'RCFaceRace')
        rec.add_subrecord('FCTP', fctp.encode() + b'\0')
        p.save_as(os.path.join(d, 'RCFace.esm'))
        plugins = sf_racecheck.load_plugins(sf_racecheck.Report(), [d], ['RCFace.esm'])
        race = sf_racecheck.find_race(plugins, 'RCFaceRace')

        rep = sf_racecheck.Report()
        sf_racecheck.check_face_textures(
            rep, [d], race, {'male_default', 'male_fox_md1', 'male_fennec_md1'}, set())
        warns = [(m, d_) for lv, _a, m, d_ in rep.findings if lv == sf_racecheck.WARN
                 and 'non-default phenotype' in m]
        assert TT.is_eq(len(warns), 1, "one warning for the missing phenotype maps")
        text = str(warns[0])
        for f in ('male_fennec_md1_normal.dds', 'male_fennec_md1_ao.dds'):
            assert f in text, f"the warning names {f}: {warns[0]}"
        assert 'male_fennec_md1_rough.dds' not in text, "a map that exists isn't listed"
        assert 'male_fox_md1' not in text, "a complete phenotype isn't listed"
        assert TT.is_eq([m for lv, _a, m, _d in rep.findings if lv == sf_racecheck.FAIL], [],
                        "the default phenotype is complete, so nothing fails")
