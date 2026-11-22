# Starfield Furrifier — Project Plan

A single tool that turns Starfield's human NPCs into furry NPCs — crowd and individual
together, designed for multiple species.

## What "furrification" means in Starfield

An individual NPC in Starfield is much more complex than in FO4 or Skyrim. A furrified NPC
needs:

1. **Race swap** — RNAM → furry race (e.g. FSFFoxRace). This gives the NPC the furry
   skeleton, head parts, and body skin.
2. **Skin tone** — STON index must be valid for the target race's BSTT/HSTT/FSTT groups.
   A fox has 8 skin tones (6 fox-red, 2 fennec sand); a wolf might have different ones.
   The human's STON index is meaningless on a furry race.
3. **Face morphs** — FMRI/FMRG/FMRS entries reference phenotype IDs that are per-race and
   per-sex. Human phenotype 3 is not fox phenotype 3. These must be rewritten.
4. **Face dials** — FMSI/FMRS sculpt sliders. Same problem: the IDs are per-race.
5. **Morph groups** — BMPN keys like `male_eu_md1_Cheeks` must become
   `male_fox_md1_Cheeks`. The phenotype component changes.
6. **Tint layers** — AVMD subrecords (TNAM/QNAM/VNAM/NNAM/INTV) reference tint options
   by name. Human dermaesthetics don't exist on a fox. These need replacing with
   species-appropriate options — or clearing.
7. **Head parts** — HEAD entries on the NPC override the race defaults. Human hair doesn't
   fit a fox skull. These need remapping or clearing.
8. **FaceGen bake** — the engine composites skin tone + tints + morphs into a per-NPC
   texture at a specific path. Furrified NPCs need fresh bakes. (The CK can do this, or
   we can bake offline like `sf_tintbake` does for crowds.)

A **crowd NPC** is simpler: it's an anonymous actor with a merged head mesh and baked
texture, no chargen morphs, no tints, no FaceGen. Crowd furrification means injecting
furry crowd NPCs into the CrowdRegion GBFM proportion lists.

## User-facing design

### Single operation, one config file

The user runs one command:
```
python sf_furrify.py --config foxes.toml --output FSF_Furrified.esm
```

This produces a plugin that:
- Overrides individual NPCs with furry races
- Overrides CrowdRegion GBFM records to inject furry crowd NPCs
- Includes (or references) the crowd variant manifest from `sf_tintbake`

### Configuration (TOML)

```toml
title = "Furry Starfield - Foxes"

# What plugins to read NPCs from. Default: full active load order.
# sources = ["Starfield.esm"]

[races.fox]
race_edid = "FSFFoxRace"
crowd_race_edid = "FSFFoxCrowdRace"
crowd_manifest = "fox_heads.variants.json"   # from sf_tintbake
source_plugin = "FSF.esm"                    # where the race is defined

# Phenotype mapping: which fox phenotype to assign.
# Each entry is a phenotype EDID prefix and its relative weight.
[races.fox.phenotypes]
fox_md1 = 60
fox_ol1 = 10
fennec_md1 = 20
fennec_ol1 = 10

# Skin tone weights (index into the race's BSTT/HSTT/FSTT).
# Names are cosmetic labels; indices are positional.
[races.fox.skin_tones]
"Red"        = { index = 0, weight = 30 }
"Dark Red"   = { index = 1, weight = 20 }
"Golden"     = { index = 2, weight = 20 }
"Cream"      = { index = 3, weight = 10 }
"Silver"     = { index = 4, weight = 5 }
"Black"      = { index = 5, weight = 5 }
"Sand"       = { index = 6, weight = 5 }
"Pale Sand"  = { index = 7, weight = 5 }

# Tint layer defaults for furrified NPCs.
# "clear" removes the human tint; "random" picks from the race's options.
[races.fox.tints]
Dermaesthetic = "random"
Complexion1 = "clear"
Scars = "keep"          # scars look fine on fur
Lipstick1 = "clear"     # no lipstick on foxes
Lipstick2 = "random"    # fox face markings live here

# Head part remapping. Keys are human HDPT types; values are fox equivalents.
# "clear" removes the part. "default" uses the race's default.
[races.fox.head_parts]
Hair = "default"         # use race's default hair list
FacialHair = "default"
Eyebrows = "clear"       # foxes have no eyebrows

# Selection rules — who gets furrified. Processed top to bottom; first match wins.
# "probability" is 0-100. "race" filters source race (default: HumanRace).
[[rules]]
match = "name"
pattern = "SarahMorgan"
race = "fox"
probability = 100

[[rules]]
match = "name"
pattern = "BarrettOrtiz"
race = "fox"
probability = 100

[[rules]]
match = "faction"
pattern = "CrimsonFleetFaction"
race = "fox"
probability = 40

[[rules]]
match = "keyword"
pattern = "ActorTypePirate"
race = "fox"
probability = 30

# Catch-all for everyone else
[[rules]]
match = "all"
race = "fox"
probability = 20

# Crowd injection. Proportion = what fraction of crowd spawns are furry.
[crowd]
proportion = 0.25        # 25% of crowd actors are furry
# Per-region overrides (CrowdRegion EDID stems):
# [crowd.regions]
# Akila = 0.4
# NewAtlantis = 0.2
```

### Selection mechanics

Like the FO4/Skyrim furrifiers, assignment is **deterministic** — same config + same load
order = same result every run. The NPC's FormID is hashed with a seed to produce a
stable 0-100 roll; if it's under the rule's probability, the NPC is furrified.

Rules are processed top to bottom. First match wins. This lets the user pin specific NPCs
("Sarah is always a fox"), bias factions, and set a global fallback.

Match types:
- `name` — NPC EDID or FULL name substring
- `faction` — NPC belongs to a faction by EDID
- `keyword` — NPC has a keyword by EDID
- `voice` — NPC's voice type EDID (useful for grouping by archetype)
- `class` — NPC's class EDID
- `template` — NPC uses a specific template
- `all` — catch-all

### Multi-race support

The config can define multiple `[races.*]` sections. Rules reference a race by key. Future
species (wolf, cat, bear) add a `[races.wolf]` section and rules targeting them. The tool
doesn't care about species semantics — it just maps source NPCs to target races with
species-specific phenotype/tone/tint tables.

## Architecture

### Inputs

1. **Active load order** — read via esplib `PluginSet`. Provides all NPC_, RACE, FACT,
   KYWD, FLST, AVMD, HDPT records.
2. **Config TOML** — races, phenotypes, tones, tints, rules, crowd settings.
3. **Crowd manifest JSON** — from `sf_tintbake.py` (already exists).
4. **Source plugin(s)** — where furry races/headparts/AVMDs are defined (e.g. FSF.esm).

### Processing pipeline

```
1. Load plugins (esplib PluginSet, partial parse)
2. Load config + crowd manifests
3. Resolve races: read BSTT/HSTT/FSTT/phenotype tables from each furry race
4. Enumerate NPCs: every NPC_ with RNAM = HumanRace (or other source races)
5. Apply rules: for each NPC, find the first matching rule, roll probability
6. For matched NPCs:
   a. Set RNAM to furry race
   b. Pick phenotype (weighted random, seeded on FormID)
   c. Pick skin tone (weighted random, seeded on FormID)
   d. Rewrite face morphs (FMRI -> target race's phenotype IDs)
   e. Rewrite face dials (FMSI -> target race's sculpt IDs, or zero)
   f. Rewrite morph groups (BMPN phenotype component)
   g. Rewrite tint layers per config (clear/random/keep)
   h. Remap or clear head parts
7. Build crowd injection:
   a. Read existing CrowdRegion GBFM records
   b. Add furry crowd NPCs at the configured proportion
8. Write output plugin
```

### Key design decisions to resolve

**Q1: FaceGen baking — offline or CK?**

Individual NPCs need FaceGen bakes. Options:
- (a) **CK batch bake** — the user runs CK after the furrifier produces the plugin.
  Simplest to implement; CK handles the FSTT->texture pipeline natively. Downside: requires
  CK, slow, can't automate fully.
- (b) **Offline bake** — extend `sf_tintbake`'s compositor to handle individual NPCs.
  We already composite skin tone + tint layers for crowds. For individuals we'd need to
  also apply morphs (or accept that the baked texture is "flat" — morphs are geometric,
  the texture is just color). This is what the FO4 furrifier does.
- (c) **Hybrid** — ship a "bake" subcommand that reads the output plugin and bakes
  FaceGen textures without CK.

**Recommendation:** Start with (a) — CK bake. Document the workflow. Move to (c) later
if the CK step is too painful. The crowd path already bakes offline; individual bake is
an extension of the same code.

**Q2: Face morph strategy — species shapes or zeroed?**

When we rewrite face morphs, we can:
- (a) **Zero all morphs** — every furrified NPC gets the race's default face. Simple,
  guaranteed correct, but every fox looks the same.
- (b) **Map morphs to species equivalents** — if the human has "strong jaw", map it to
  the fox equivalent. Preserves some character diversity. Requires a morph equivalence
  table per species.
- (c) **Random from presets** — pick a random chargen preset from the furry race's
  preset list (RPRM/RPRF). Each NPC gets a pre-validated face. Most variety for least
  authoring effort.

**Recommendation:** (c) for the first pass. Presets are guaranteed valid. Seed on FormID
for determinism. Fall back to (a) if no presets exist.

**Q3: Head part remapping — remap or use defaults?**

Human hair doesn't fit furry heads. Options:
- (a) **Clear and use race defaults** — every fox gets whatever hair the race defines.
  Safe but uniform.
- (b) **Remap table** — human hair X maps to fox hair Y. Preserves "this NPC has short
  hair" intent. Requires an equivalence table per species.
- (c) **Random from race's chargen options** — pick a random hair from the race's
  `HeadPartsChargenOptions` list.

**Recommendation:** (c) for hair, (a) for everything else initially. Hair is the most
visible; other parts (eyebrows, facial hair) can start as "use race default" and get
equivalence tables later.

**Q4: Armor and outfit handling?**

When an NPC's race changes, their armor addons must support the new race, or the NPC
appears naked/invisible. The furry race's Armor Race (RNAM on RACE) controls which
ARMA addons are used. If the furry race shares an Armor Race with HumanRace (or lists
HumanRace as an additional race on its ARMAs), vanilla armor just works.

If not, the furrifier may need to:
- Override ARMA records to add the furry race to their Additional Races list
- Or override the furry RACE to set its Armor Race to HumanRace

**Recommendation:** This is an asset/race-design decision, not a furrifier decision.
The furrifier should WARN if a furrified NPC's outfit contains ARMOs whose ARMAs don't
list the target race, but not try to fix it.

## Implementation phases

### Phase 1: Core NPC furrification (MVP)

- [ ] Config parser (TOML)
- [ ] NPC enumeration from load order (esplib)
- [ ] Rule matching engine (name/faction/keyword/all)
- [ ] Deterministic probability (FormID-seeded hash)
- [ ] Race swap (RNAM)
- [ ] Skin tone assignment (STON, weighted)
- [ ] Face morph rewrite (preset-based)
- [ ] Tint layer handling (clear/keep)
- [ ] Head part handling (clear to defaults)
- [ ] Plugin writer (esplib)
- [ ] Armor compatibility warnings

**Output:** A plugin that furrifies individual NPCs. User runs CK to bake FaceGen.

### Phase 2: Crowd integration

- [ ] Read crowd manifests from `sf_tintbake`
- [ ] GBFM proportion list injection
- [ ] Merge crowd and individual into one plugin
- [ ] Per-region crowd proportion overrides

**Output:** One plugin handles both crowd and individual.

### Phase 3: Polish

- [ ] Offline FaceGen bake (extend `sf_tintbake` compositor)
- [ ] Morph equivalence tables (Q2 option b)
- [ ] Head part remapping tables (Q3 option b)
- [ ] Tint layer randomization (pick random dermaesthetic etc.)
- [ ] Validation pass (sf_racecheck integration)
- [ ] Dry-run mode (report what would change without writing)

### Phase 4: Multi-species

- [ ] Multiple `[races.*]` sections in config
- [ ] Per-species rule chains
- [ ] Species-weighted catch-all ("20% fox, 10% wolf, 70% human")
- [ ] Shared crowd plugin with multiple species

## File structure

```
scripts/
  sf_furrify.py          -- main furrifier script
  sf_furrify_config.py   -- TOML parser, rule engine, config dataclasses
  sf_furrify_npc.py      -- NPC rewriting logic (morphs, tints, headparts)
  sf_furrify_crowd.py    -- GBFM injection, crowd manifest reader
  sf_tintbake.py         -- (existing) crowd variant baker
  sf_racecheck.py        -- (existing) validation tool
configs/
  foxes.toml             -- fox furrification config (ships as example)
```

## Open questions for Bad Dog

1. **Where does the output plugin go?** Same pattern as FSFNPC_Fox.esm (a separate
   plugin), or should it be a patch ESP?

2. **Crowd GBFM automation** — you mentioned this is done by hand in CK currently. Is the
   GBFM record structure documented enough to automate, or do we need a spike?

3. **FaceGen bake priority** — is CK baking acceptable for the MVP, or is offline bake
   a hard requirement from day one? (The crowd bake path exists; extending it to
   individuals is work but not research.)

4. **Preset availability** — how many fox chargen presets exist today? If zero, the
   "random preset" face strategy falls back to zeroed morphs and every fox looks identical.

5. **Outfit strategy** — does FSFFoxRace already set its Armor Race to share with
   HumanRace, or will we need ARMA overrides?

6. **Per-NPC WNAM (skin/body override)** — do you want the furrifier to set WNAM, or
   is the race's default skin always correct?

7. **Scope of "individual" NPCs** — is the target every NPC_ with RNAM=HumanRace, or
   only non-crowd NPCs? (Crowd NPCs have HumanCrowdRace, so they're naturally excluded,
   but there may be edge cases.)

8. **The existing `build_female.py` for foxes** — should the furrifier subsume this, or
   does that script serve a different purpose (building the race definition itself vs.
   applying the race to NPCs)?
