# FSFTools changes

## Unreleased

The tools have a home of their own: `sf_racecheck`, `sf_tintbake`, `uv_transfer` and
`sf_texconv` came here from PyNifly's `scripts` folder, joining the furrifier. They find PyNifly
through `fsftools/deps.py`: the `PYNIFLY` environment variable, a development checkout, or the
PyNifly extension installed in Blender. esplib comes from pip.

- **The hair plugin's records are numbered for a light plugin.** FSFHair.esm numbered its new
  records after vanilla's chargen lists, which it overrides (3D9B1 and up). A light plugin's own
  records must be 800-FFF, so the game and the CK read the NPCs' hair as other records: no hair
  in the CK, a REFR in xEdit. A rerun renumbers an existing plugin's records into the range, and
  the NPCs furrified in the same run use the new numbers. After `--hair-only`, rerun the
  furrifier so the NPCs follow.
- **`--hair` puts the fitted hair on the NPCs.** It now implies `--keep-hair`. Alone it used to
  fit the hair and leave every furrified NPC bald.
- **Facial hair has a chance, and stays within its race.** A race's TOML can set
  `facial_hair_male` and `facial_hair_female` (0-1) in `[race]`. An NPC who misses gets no
  facial-hair part, and loses any vanilla beard. Unset is always, as before. A part is a candidate
  only if its RNAM lists the race or its crowd race, so a part with no RNAM is never picked, and a
  hyena no longer draws parts made for the fox alone. A chance above 0 with no parts to pick stops
  the run at startup.
  - The crowd heads follow the same chance: sf_tintbake reads `facial_hair_<sex>` from the
    recipe's `race_config` as its `[beards] percent` (0.7 is 70). Set there, the recipe must not
    set `percent` as well. Unset, the recipe's `percent` works as before.
- **sf_furrify's output goes in one folder.** `--out` is that folder, or a plugin in it: a folder
  gets `FSFNPC.esm`, a plugin name alone still goes in Data, and no `--out` is Data as before.
  Everything a run writes goes there. So **`--facegen` and `--crowd-skeleton` no longer take a
  folder**: they're switches, and write into the output folder. A name without a plugin extension
  is now a folder, not a plugin to add `.esm` to.
- **`--hair` fits the human hair to each race's head** before the NPCs are furrified (`--hair-only`
  stops there). Each hair is reshaped so it sits on the new head as it sat on the human one, with
  its `_facebones` companion. It gets a morph key for each of the head's keys that moves it:
  Bethesda's own key plus the difference between the heads where both have it, otherwise the head's
  key copied onto the hair. The ears move the hair under every key (`--ears-fixed` stops that); the
  hair's own shape is fitted with the ears hidden.
  - Races sharing a head share the hairs: `Human_Female_Hair_Bob` becomes
    `FSFCanine_Female_Hair_Bob`, in `FSFHair.esm` in the output folder.
  - A race's TOML picks its hairs: `[hair] include = [...]`, `exclude = [...]`, EditorID globs.
  - Hairs from mods in the load order are fitted too.
  - A rerun fits only the hairs whose sources changed, and rewrites records in place under their
    FormIDs, so a player's chosen hair survives. A hair no longer wanted loses its records.
  - A hair's cloth moves with it: each particle by its nearby hair's offset, each bone plane
    with its particle, and each collision capsule's radius by how far its particles moved from
    its axis (never so far that one starts inside). The cloth bones stay at their binds, so at
    rest the hair shows as fitted.
  - The fitted hairs are offered in the character creator. The hair plugin overrides
    `HeadPartsChargenOptionsMale`/`Female` with what the active player plugin's lists hold, plus
    each sex's fitted hairs. It takes in every race's player plugin's changes but masters none, as
    only one is active, so **load the hair plugin after the player plugins**.
  - A hair's extra parts (a hair tie, beads, the buzz cut's front) are fitted with it, as one
    piece, so a tie stays on its ponytail. The fitted hair names the fitted parts.
  - A part with no morph keys of a kind gets no morph file for it: an empty `morph.dat` crashes
    the CK.
  - **Crowd hair and hats are fitted too**, when the crowds are furry. Each breed's first crowd
    head of each sex (md1 before md2) gets every crowd hair and hat, every LOD; breeds with the same
    first heads share the fit, and the breed's other heads wear it. The source is vanilla's first
    crowd head. Crowd heads have no HideEar morph, so the fit folds their ears as the race's own
    head's HideEar folds its ears, and leaves out the arms. With `--keep-hair`, each breed's heads come with
    its own copy of the outfit's hair list, of copies of the armors naming the fitted nifs.
    `[hair] crowd_include` / `crowd_exclude` pick the armors (EditorID globs). Files go in
    `Meshes\Actors\<crowd head folder>\Hair\<head>`.
- **`--log FILE`** (sf_furrify) writes everything printed to a file as well, errors and tracebacks
  included, headed by the command line.
- **The FaceGen bake finds vanilla textures in `--assets`**, as it finds vanilla meshes.
- **A head part whose chargen morph doesn't fit its mesh stops the bake with its name**, the morph
  folder and the nif, instead of an IndexError from deep in the bake. A bake that stops prints an
  `ERROR:` line, not a traceback.
- **No human scalp masks on furry faces.** A human hair's scalp mask (its `NAM3`) is drawn for the
  human face's UVs. Fitted hairs leave it out, and the bake doesn't paint a kept human hair's.
- **`--keep-hair` keeps the fitted copy** of an NPC's hair when the load order has one, and says
  how many hairs had none. The FaceGen bake reads the fitted hair from the output folder, so it
  needn't be deployed first.

- **`--overlay DIR`** (sf_furrify, sf_racecheck, sf_tintbake): a folder laid out like Data whose
  files win over Data's, like a mod installed but not deployed. Run against an undeployed mod, or
  check FSFPlayer_HYENA while FOX is the deployed one. The tools read through a merged view made of
  links, so nothing is copied. An `overlay.toml` there (`replaces = [...]`) hides the deployed files
  of the mods it stands in for.
- **FaceGen bakes match the Creation Kit's in more cases.** Each fix was measured against a CK bake.
  - A beard's or hair's follicle mask (the head part's `NAM3`) is now painted on the face in the
    NPC's facial-hair or hair colour, and lowers roughness under it (the colour's first byte is the
    roughness). With no hair colour, the mask paints black and leaves roughness alone.
  - A mask tint with no colour (`NNAM` 00000000) paints black. It used to paint the mask itself
    over the whole face.
  - A tint's strength is `INTV`/63, not /64. 64 still means full strength.
  - A phenotype with no `_ao`/`_rough`/`_normal` maps no longer stops the bake. Its sliders are
    left out of the texture blend, so that region gets the default maps.
  - A race without `FCTP` (HumanRace) takes its face maps from `actors\human\faces\chargen`.
- **Baking an NPC as it stands reads its phenotype for its own sex.** The male and female
  phenotype tables share their ids, and a male used to get the female table's name.
- **The tests have their own NPCs**, in `tests/fixtures/fsftest/FSFTest.esm`, written by
  `tests/make_test_plugin.py`, and the CK's bake of them. FSF's own presets can change freely.
- **race_copy can run again.** On a plugin that already has the new species, it rewrites the copies
  in place under their FormIDs, instead of adding a second set with the same editor IDs. Hand edits
  to the copies are overwritten, and a copy renamed by hand comes back under the config's name.
- **The furrifier's scheme and race definitions default to `Data\FSFTools\furrify`,** where a
  mod ships them. `--scheme` and `--races` still name others. The classification rules
  (`builtin.toml`) ship with the tools.
- **Paths in a race definition are relative to the file,** so a mod's data folder works wherever
  it's deployed. `crowd_manifests = ["../../crowd/fox/CrowdHead_fox_male.variants.json"]`.
- **`sf_racecheck.py` says which nifs use a material** it reports on: each finding lists
  `used by <nif> (<shape>)` for every shape that names it. A material it can't find, that vanilla's
  nif of the same name names too (a fitted copy of a vanilla hair), is a warning naming that nif,
  not a failure: it's probably in a DLC's own material database, which the checker doesn't read.
- **`sf_racecheck.py` and `sf_tintbake.py` warn about vertices with no skin weight** in a crowd
  head or its `_faceBones` companion. The game can't place them, so those parts don't show.
- **`sf_racecheck.py` fails a race that can't show spacesuits.** Starfield shows a spacesuit
  only on HumanRace, HumanCorpseRace, ChildRace, or a race with the keyword
  `RaceAllowShowSpacesuit`; giving the race HumanRace as its Armor Race doesn't help. A custom
  race without the keyword wears no visible suit: the player's suit is invisible, and NPCs
  dressed only by a space outfit (The Hunter, Lin, the Argos miners) stand naked. Crowd
  races are exempt, as vanilla crowds don't wear spacesuits.
- **`sf_racecheck.py` resolves tint-group references by editor ID, as the game does.** A
  Complex tint group's entry names its target by editor ID. `sf_racecheck` was building the
  name from the target's group name (TNAM) instead, which only agrees when the editor ID is
  `SimpleGroup_` + TNAM. A dermaesthetic filter pointing at `…SkinTone1` when the group's
  editor ID was `…SkinTone01` passed the check, and the character creator offered no
  dermaesthetic options at those skin tones. It now fails such an entry and names the editor
  ID it should use. `sf_tintbake.py` follows the same rule.
- **`sf_racecheck.py` no longer fails a face for a few empty morph keys.** It said a declared
  key with no displacement makes the head invisible. What's actually proven is narrower: a
  `morph.dat` with no data at all crashes the CK, and that's still a failure. Some empty keys
  among real ones render fine. 246 of vanilla's 1,194 morph files have them, and a fox head
  shipping two empty squint keys shows normally. They're now a warning that names the keys,
  since those morphs won't move anything when the game drives them.
