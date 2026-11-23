# FSFTools changes

## Unreleased

The tools have a home of their own: `sf_racecheck`, `sf_tintbake`, `uv_transfer` and
`sf_texconv` came here from PyNifly's `scripts` folder, joining the furrifier. They find PyNifly
through `fsftools/deps.py`: the `PYNIFLY` environment variable, a development checkout, or the
PyNifly extension installed in Blender. esplib comes from pip.

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
  - Hairs with cloth or extra parts aren't fitted yet.
- **`--log FILE`** (sf_furrify) writes everything printed to a file as well, errors and tracebacks
  included, headed by the command line.
- **The FaceGen bake finds vanilla textures in `--assets`**, as it finds vanilla meshes.
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
