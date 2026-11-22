# Furry Race Plan

Plan for using Starfield's mechanisms for furry races.

# Vanilla setup

- One human race
- European, asian, and african subraces selected with different textures

## Applying textures and morphs

- **AVMD SimpleGroup** 
  - LNAM/VNAM pairs
    - LNAM = NakedBodyM_sk0_color
    - VNAM = textures/actors/human/naked_body/nakedbodym_sk0_color.dds
  - Human male body has only 9 ranging from pale to dark skin colors
  - Or, for face post blend detail layers
    - AVMD = SimpleGroup_Dermaesthetic
      - LNAM = Asian_Male_Ol1_Sk1
      - VNAM =
        textures/actors/human/faces/chargen/postblenddetails/dermaesthetic/male_as_ol1_sk1_derm_color.dds
  - Or, for scars
    - AVMD = SimpleGroup_Scars_color
      - LNAM = Scar_AcrossNose
      - VNAM = textures/actors/human/faces/chargen/postblenddetails/scars/scar_acrossnose_color.dds
    - AVMD = SimpleGroup_Scars_normal
      - LNAM = Scar_AcrossNose
      - VNAM = textures/actors/human/faces/chargen/postblenddetails/scars/scar_acrossnose_normal.dds
    - AVMD = SimpleGroup_scars_ao
      - LNAM = Scar_AcrossNose
      - VNAM = textures/actors/human/faces/chargen/postblenddetails/scars/scar_acrossnose_ao.dds
    - AVMD = SimpleGroup_scars_rough
      - LNAM = Scar_AcrossNose
      - VNAM = textures/actors/human/faces/chargen/postblenddetails/scars/scar_acrossnose_rough.dds

- **AVMD Complex Group** 
  - A complex group defines face skin tones
    - AVMD = ComplexGroup_FaceSkinTones
    - LNAM/VNAM pairs
      - LNAM = female_af_md1
      - VNAM = SimpleGroup_FaceSkinTones_female_af_md1
    - Male has 11 (includes male_default)
    - Each FaceSkinTones simple group has 9 or so textures. So 99 facial textures for male
      humans? 
  - A complex group also defines the post-blend customization layers. 
    - The order is logical. Read bottom-to-top as paint layers: 
      - skin detail → complexion → scars → accents → tattoos → makeup base → blush → lips → eyeshadow → eyeliner → environmental weathering last, over everything
    - AVMD = ComplexGroup_PostBlendFaceCustomizationLayers
      - YNAM = TNAM = PostBlendFaceCustomizationLayers
      - Entries:
        - LNAM = Dermaesthetic
        - VNAM = SimpleGroup_Dermaesthetic
  - Complex groups define the layers for a post-blend layer that needs more than one file.
    - AVMD = ComplexGroup_Scars
      - YNAM = TNAM = Scars
      - Entries:
        - LNAM = Scars_color
        - VNAM = SimpleGroup_Scars_color
        - LNAM = Scars_normal
        - VNAM = SimpleGroup_Scars_normal
  
- **AVMD Modulation Group**
  - A modulation group provides color options. Modulation groups can be referenced by Complex Groups but for characters, seem to be paired with Simple Groups.
    - AVMD = Modulation_Lipstick1 (paired with SimpleGroup_Lipstick1)
      - YNAM = TNAM = Lipstick1
      - Entries: Name/Color pairs

- **Race**
  - BSTT - Body Skin Tones = Male_Naked_Body_Skin_Tones (AVMD keyed by TNAM)
  - HSTT - Hand Skin Tones similar
  - FCTP - Face custom textures base path (omitted for HumanRace)
  - FSTT - Face skin tones = FaceSkinTones (ComplexGroup; male & female)
  - Morph groups 
    - MPGN - Group name (Eyes)
      - MPGM - Morph `<sex>_<ethnicity>_<age>n_<region>` - e.g. female_eu_md2_Eyes - this is a chargen morph key
  - Face Morph Phenotypes 
    - FMRI - Index into the facialboneregions file (SculptRegion:false) - so these move
      facebones
    - FMRU/FMRN/FMRS - Name (all the same) - `<sex>_<ethnicity>_<age>n`. (FMRN is
      localized, the rest literal.)
    - Optionally a list of regions (Possibly these are not under the FMRI - that may be an
        artifact of how xEdit shows them)
      - FMSR - Index into facialboneregions file (SculptRegion:true)
      - FMRU / FMRN - Name (Mouth / Ears / Eyes / Nose / Jaw / Head Shapes / Neck /
        Forehead / Eyebrows / Cheeks / Chin)
      -  
  - Face Dials 
    - FDSI - Skin index
    - FDSL - label (back - forward)

- **NPC**
  - In CK, NPCs have
    - Post Blend Face Customization
      - AVMS
        - Type (Dermaesthetic, ComplexionMask1, Complexion1, Complexion2, Scars, ...)
          - Subtype (African_Male_md1_sk3) - Subtype options depend on type.
        - Intensity
        - Color
  - AVMD (xEdit)
    - MNAM - AVM Group Type (SimpleGroup or ComplexGroup)
    - TNAM - Tint Group (string) - Dermaesthetic, Complexion1, ...
    - QNAM - Tint Name (European_Male_Md1_Sk1)
    - VNAM - Tint texture (filepath)
    - NNAM - Tint color
    - INTV - Intensity
  - STON - Skin tone; index into BSTT, HSTT, & FSTT
  - Face dial positions  (Face-bone regions)
    - List of 
      - FMSI - index - slider ID moves bones e.g. `024 down - up`
      - FMRS - value
  - Face morphs (Face-bone regions)
    - Face morph phenotype
      - FMRI - Index matching race
      - Repeating
        - FMRG - Morph group (string) - matches region from race?
        - FMRS - Blend intensity
    - So a face is "blend toward phenotype FMRI by x in the Cheeks, by y in the Jaw…"
  - Morph groups
    - List of morph blend
      - BMPN - blend name - `<sex>_<ethnicity>_<age><index>_<region>` e.g.
        male_af_yo1_Nose - which is a chargen morph key
      - BMPV - intensity

### External files

- `humanracefacialboneregionsmapping.csv` - maps face bones to sculpt regions (cheeks, chin, ears, etc). Grid has a value for each pair - how much each bone affects each region. Sculpt regions are a superset of "blend groups". Check what that means.
- `<race>facialboneregions<sex>.txt` - JSON file defining regions, both phenotypes and sculpt regions.

### Head morphs

- Heads may supply morphs for each phenotype and region named `<sex>_<phenotype>_<region>`. Sex = "male" / "female".
- Regions are Eyes, Cheeks, Chin, Ears, Forehead, Jaw, Mouth, Neck, Nose

### Body & Hand colors

- Set via simple groups. Each entry corresponds to a STON index. Naming convention is
  `DefaultHands<sex>_sk<STON>_color.dds`. Sex = "m" or "f". 
- Other layers are found as `DefaultHands<sex>_<layer>.dds`. Layer = "ao", "normal",
  "rough". 
- There is also a `_mask` layer. On the body this masks off the underwear, nipples, and
  neck seam. It's used to mask pore details, which are blended in as a separate layer in
  vanilla.
- These layers are identified in the hand/body materials files. 

## Applying skin tone to an NPC

- STON on the NPC record is an index into BSTT, HSTT, FSTT
- BSTT & HSTT are simple groups listing aldebo textures. STON is an index into the group.
- FSTT is a complex group. Each entry is a "phenotype" - sex_ethnicity_age. (There can be
  multiple entries for an age, e.g. male_eu_md1 and male_eu_md2.) Phenotypes are defined
  in the race.
- The phenotype is used to select an entry in the complex group. STON is used to index the
  referenced simple group.
- The aldebo texture path is found from the simple group. They follow the convention `<FCTP>/<sex>_<phenotype>_sk<STON>_color.dds` but this doesn't seem to be necessary.
- Normal, roughness, and AO textures are built from the phenotype as `<FCTP>/<sex>_<phenotype>_normal.dds` (and `_ao`, `_rough`).

Consequences:
- There can be as many skin tone (STON) layers as you like, but they have to have a
  matching entry across BSTT, HSTT, and *all* FSTT simple group entries.
- Each entry in a face simple group must match the corresponding BSTT & HSTT entry. If the
  skin tone is pink, *all* pink face options have to match that one body. 

## Skin tone layers

Layers defined by <ComplexGroup_PostBlendFaceCustomizationLayers>. There is no differentiation between male and female.

Texture layers may be define as:

- COLOR - Layer references a simple groupo which lists aldebo texture files.
- MOD - Layer references a modulation group, a list of colors
- CNRA - Layer defined by a complex group which references a coordinated set of simple
groups defining color, normal, roughness, and ambient occlusion.
- GRAY - Textures are grayscale masks, DXGI_FORMAT_R8_UNORM, linear gamma

Only Dermaesthetic, Complexion1, and Complexion2 are painted below scars. Everything above
is conceived of (in vanilla) as makeup, paint, or dirt,  Accent layers, apparently, are
allowed to show through the scar. Dermaesthetic has full color but we don't know how it's
mixed. The complexions have color and can be additionally modulated by the mask colors. 

All layers affect the head only. They have to merge into the body correctly.

Questions:
- Can we add tint layers? Can we add a Complexion3? 
- Can we add totally new tint layers?
- Can we reorder tint layers? Put accents before scars?
- What is the blend mode? Does it depend on layer?

**Layers**

Face texture layers, defined in "ComplexGroup_PostBlendFaceCustomizationLayers".

Some simple groups come paired with modulation groups. One or the other will be listed in
PostBlendFaceCustomizationLayers and the other will be found by name, e.g.
SimpleGroup_ComplexionMask1 is paired with Modulation_ComplexionMask1 and found with it.

Blend mode is "Normal" unless otherwise stated - that is the layering color at alpha 1
will replace the underlying color - no blending except as provided by alpha.

- **Skin detail**
  - **Dermaesthetic** - (COLOR) Texture on top of the FSST texture. Filename ends with
    "_derm_color". Format is DXGI_FORMAT_R8G8B8A8_UNORM_SRGB (full color, no compression,
    alpha). Vanilla sized at 1024x. Blend mode is Normal. The list is keyed as `<ethnicity>_<sex>_<age><n>_sk<n>` - but "ethnicity" is "Asian"/"Eurpoean"/"African", "sex" is "male"/"female", and not all skin tones are represented (n does not fill 0..8).
- **Complexion**
  - **ComplexionMask1** - (MOD + MASK) In the UI as "Complexion Blemishes". Paired with
    SimpleGroup_ComplexionMask1 and provides colors for that slot - available through a
    slider in the UI.
  - **Complexion1** - (COLOR) "Complexion Color Temp" in the UI. This primarily shades the
    skin tone in vanilla. Alpha layer sets the strength. Despite the name, blend is Normal
    -- the color can completely replace the underlying color. 
  - **Complexion2** - (COLOR) Duplicates Complexion1 - does not seem to be accessible in
    the UI. 
  - **ComplexionMask2** - (MOD + MASK) Duplicates ComplexionMask1 - not available in the UI.
- **Scars**
  - **Scars** - (CNRA) Complex group lists color, AO, normal, roughness - simple groups
    are coordinated across the 4 layers. Color has transparency, presumably to pick out
    the scar area.
- **Accents**
  - **Accents1** - (CNRA) "Facial Forms 1" in game. Complex group lists the 4 layers,
    simple group has the options. Color layer has alpha. NPCs never use the "tint" NNAM
    value so any color is picked up from the aldebo.
  - **Accents2** - (CNRA) "Facial Forms 2" in game, same options as Accents1. Allows
    picking up to 2 accents.
  - **ColorlessAccents1** - (CNRA) Same accents as above. Not sure why "colorless". Not in UI.
  - **ColorlessAccents2** - (CNRA) Same accents as above. Not in UI.
- **Tattoos** 
  - **TattooColorMap** - References SimpleGroup_TattooColorMap, which doesn't exist.
  - **TattooTint** - References SimpleGroup_TattooTint, which doesn't exist.
  - **TattooMask** - (GRAY/MOD) References Modulation_TattooMask for color options for
    SimpleGroup_TattooMask. 
- **Makeup base / face paint**
  - **MakeupFullPaintMask** - References SimpleGroup_MakeupFullPaintMask, which doesn't
    exist
  - **MakeupFullPaintMask1** - (MOD/COLOR) References Modulation_MakeupFullPaintMask1,
    which is paired with SimpleGroup_MakeupFullPaintMask1. Masks are grayscale, no alpha.
  - **MakeupFullPaintMask2** - Same as 1
- **Blush**
  - **Cheeks1** - (GRAY/MOD) References a simple group which is a list of grayscale masks,
    paired with a modulation group.
  - **Cheeks2** - (GRAY/MOD) Does NOT duplicate Cheeks1
- **Lips**
  - **Lipstick1** - (GRAY/MOD) References a simple group listing grayscale masks, paired
    with a modulation group.
  - **Lipstick1** - (GRAY/MOD) does NOT duplicate Lipstick1
- **Eyes**
  - **Eyeshadow1** - (GRAY/MOD) Upper eye shadow. References a simple group listing masks.
    Has a twinned modulation group.
  - **Eyeshadow2** - (GRAY/MOD) Lower eye shadow.
  - **Eyeliner1** - (GRAY/MOD) Upper and lower. References simple group listing masks,
    with a twinned modulation group.
  - **Eyeliner2** - (GRAY/MOD) Upper and lower, overlapping but not identical to
    Eyeliner1.
- **Environmental weathering**
  - **EnvironmentColor** - References SimpleGroup_EnvironmentColor, which is empty. No
    twinned modulation group.
  - **EnvironmentMask** - (GRAY/MOD)  References SimpleGroup_EnvironmentMask, with a
    twinned modulation group. Masks are named "female" but there's no indication this is
    female only.

A bit unknown is whether the blend mode for the different layers is different. We'll test that before committing.

# Furrification Scheme

## Race allocation and customization

Every species gets a separate race record, same as FFO and Furry Skyrim.

- We explored having one "canine" race with the species being phenotypes. That was
  rejected because the STON skin tone list cuts across all bodyparts, and bodies and hands
  don't have phenotype variants. The result is 6 species X 6 fur tints per species x 6
  phenotypes (assuming none of the species share body textures). 

## Textures

### Base face, body, hands

**Species and skin tone**

Phenotypes select breeds/variants. They allow us to pick facebones adjustment and chargen
morphs. Each breed has a separate phenotype. Within breeds we can use at least two
phenotypes: "md" (middle-aged, regular adult) and "ol" (old). No need for a young variant.

Skin tone selects fur aldebo, and are set independently of phenotype. There can be as many
skin tones as needed. We build fur pattern into the aldebo (white belly, dark hands/feet,
stripes). Fur pattern is *not* separate from color. 

Consequently there will be (number of species) X (colors per species) skin tones. That's
roughly 6 x 6, 36 options. Further, every species must provide aldebo textures for every
skin tone, whether it makes sense on the race or not. 

**Face tint layers**

- We don't know if we can muck with the tint layers defined by the platform. Even if the
  engine allows it, chargen in game may not. so start with the vanilla system.
- Scars should layer on any fur patterns. Above scars can be tattoos, paint, makeup, dirt.
  Cheeks, for example, are a natural slot for cheek fur patches but they layer over scars
  as though they were blush makeup. 
- The only layers below scars are dermaesthetic, Complexion1 (full color), and Complexion2
  (mask + one color). This is not very many layers to do customization with. Either we
  build a lot of variants into the derm and custom1 layers or we don't worry about putting
  fur color over scars.

## Lykaios Race

**Phenotypes**
- lyk_md1 - base simple head with minimal color variation
- lyk_md2 - head built from wolf fur photos

**STON** - standard wolfy colors.

## Fox Race

**Phenotypes** - each matches to a head shape morph
- fox_md1 - Ears, Nose (muzzle)
- fox_ol1
- fennec_md1
- fennec_ol1

**STON**
- 8 colors - 6 variants of fox red, 2 of fennec sand color

### Tint Layers - Fox

We need white face markings with different extents; a dark muzzle or two and white nostril fur or two; dark ears; pale eye spots.

- **Skin detail**
  - **Dermaesthetic** - Base white face fur patterns. Need (# of patterns) * (# of skin tints) of these. 
- **Complexion**
  - **ComplexionMask1**/Complexion Blemishes - Face fur shading. Eye spot, lighter cheeks.
  - **Complexion1**/Complexion Color Temp - Muzzle and ear tints
  - **Complexion2** - Second layer duplicating Complexion1. Not available in the UI, not used. 
  - **ComplexionMask2** - Not available in UI, not used.
- **Scars**
  - **Scars** - (CNRA) Complex group lists color, AO, normal, roughness - simple groups
    are coordinated across the 4 layers. Color has transparency, presumably to pick out
    the scar area.
- **Accents**
  - **Accents1** - (CNRA) Complex group lists the 4 layers, simple group has the options.
    Color layer has alpha. NPCs never use the "tint" NNAM value so any color is picked up
    from the aldebo.
  - **Accents2** - (CNRA) Same as Accents1. Allows picking up to 2 accents.
  - **ColorlessAccents1** - (CNRA) Same accents as above. Not sure why "colorless".
  - **ColorlessAccents2** - (CNRA) Same accents as above.
- **Tattoos** 
  - **TattooColorMap** - References SimpleGroup_TattooColorMap, which doesn't exist.
  - **TattooTint** - References SimpleGroup_TattooTint, which doesn't exist.
  - **TattooMask** - References Modulation_TattooMask for color options. There is a
    SimpleGroup_TattooMask, which is maybe found by name? TattooMask is grayscale,
    DXGI_FORMAT_R8_UNORM, linear gamma.
- **Makeup base / face paint**
  - **MakeupFullPaintMask** - References SimpleGroup_MakeupFullPaintMask, which doesn't
    exist
  - **MakeupFullPaintMask1** - References Modulation_MakeupFullPaintMask1, which is paired
    with SimpleGroup_MakeupFullPaintMask1. Masks are grayscale, no alpha.
  - **MakeupFullPaintMask2** - Duplicates 1
- **Blush**
  - **Cheeks1** - References a simple group which is a list of grayscale masks, paired with
    a modulation group.
  - **Cheeks2** - Does NOT duplicate Cheeks1
- **Lips**
  - **Lipstick1** - References a simple group listing grayscale masks, paired with a
    modulation group.
  - **Lipstick1** - does NOT duplicate Lipstick1
- **Eyes**
  - **Eyeshadow1** - Upper eye shadow. References a simple group listing masks. Has a
    twinned modulation group.
  - **Eyeshadow2** - Lower eye shadow.
  - **Eyeliner1** - Upper and lower. References simple group listing masks, with a twinned
    modulation group.
  - **Eyeliner2** - Upper and lower, overlapping but not identical to Eyeliner1.
- **Environmental weathering**
  - **EnvironmentColor** - References SimpleGroup_EnvironmentColor, which is empty. No
    twinned modulation group.
  - **EnvironmentMask** -  References SimpleGroup_EnvironmentMask, with a twinned
    modulation group. Masks are named "female" but there's no indication this is female
    only.

## Player race

- The races are defined in one plugin. The player's race is defined in a second plugin,
  similar to FFO. Any records such as ComplexGroup_PostBlendFaceCustomizationLayers can be
  overridden there.

# Testing Tint Layers

Setup
- scar_nosegouges_color replaced with plain red tint - will cover whole face
- accents_undereyebagssmall_color replaced with blue - will cover whole face
- Testing CF_NaevaMora - has both

## Tests

1. Vanilla order

   1. Both present, intensity 0 - face flesh
   2. Scar 1, accent 0 - face red (have to save NPC before baking)
   3. Scar 1, accent 1 - face blue

2. Reversed order in NPC record - accent before scar
   1. CK shows scar before accent in post-blend list
   2. Face is BLUE in CK and generated texture - accent won. Reversing the order failed.

3. Reversed order in ComplexGroup_PostBlendFaceCustomizationLayers
   1. CK shows scar before accents1
   2. Face is BLUE. 
   3. Repeated after shutting down and reloading CK (not just reloading the files). Same
      result. 

CONCLUSION: ComplexGroup_PostBlendFaceCustomizationLayers doesn't matter, order in the NPC
record doesn't matter. Layers are composed in a fixed order, built in.

# Issues 2026-09-25

- Heads have no normal
  - Export with simplified material
- Eyes are not picking up the canine irises
  - Added magenta slash to make issue visible
  - "IrisDepthTransitionRatio": "0.1599999964237213" - this sets how much of the eye comes from the iris texture (?)
    - 0.16 (default) - only red circle visible
    - 0.2 - out to the green ring
    - 0.3 - out to magenta circle
    - 0.5 - out to outer gold circle visible
- FIXED: Record #3 has gray body (skin tone is 1 on that body)
  - Cleaned up presets
- FIXED: Record #9 has fennec body tint, fox head tint - but the "Face" panel knows it's skin tone 5
- Teeth are bad - looks like still has blue gums, doesn't look like teeth are present
- Skin tone 2 has 3 derma options - the 4th appears present but unselectable
- 