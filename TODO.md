# FSFTools TODO

## `sf_racecheck`: check every head part's morphs, not just the face's

**Status:** done 2026-10-23 (uncommitted): `check_part_morphs` on every head part
`check_head_parts` walks; `check_morphs` (face) also FAILs a zero-record file.
TEST_SF_RACECHECK_PART_MORPHS. FSFFoxRace: all 12 parts with morphs pass.

`run()` calls `check_morphs` only for the race's own Face head part (`own_face` -> `MNAM`). Any
other head part with a morph -- facial hair, eyebrows, ears -- goes unchecked, so the empty
`FSFFox_Ruff01` morph above was only found after it crashed the CK.

**Do:** for every non-official head part valid for the race (the set `check_head_parts` already
walks), resolve `MNAM` -> MRPH and run the morph-vs-.mesh vertex count on its TCMP/TMPP morph.dat.
A morph.dat with zero records is a FAIL ("crashes the CK"). Individual empty keys on a non-face part
are normal (see the item above) -- at most an INFO count, never a WARN. The race's `MPGM`
declared-keys-must-have-data check stays face-only.

**Where:** `sf_racecheck.py` (`check_head_parts`, `check_morphs`). Test with a real-looking
head part whose morph.dat has zero records.

## Crowd-head variants: teeth options

**Status:** done 2026-10-22 (uncommitted): a part painted `"teeth"` takes a TeethCustomization
option; `[teeth]` code (default `t`) and exclude; `_t<n>` after the eye code, only when some part
uses `"teeth"`. TEST_SF_TINTBAKE_TEETH.

`sf_tintbake.py` paints every variant's mouth with one fixed texture, named in the recipe's
`[parts]`. The race offers teeth options in `TeethCustomization` (the fox has two: Teeth_Clean,
Teeth_Dirty). Make teeth a choice like the eyes: a `"teeth"` part role, options from the group,
a `[teeth]` code and exclude list, and the option in the variant name.

## Crowd bake: fennec (and other sub-species) skin tones

**Status:** parked (Bad Dog 2026-10-19, not ready to decide).

A recipe's `phenotype` picks the face skin tones every head in its `heads` folder starts from, so
`crowdf_fennec_md1` bakes with `female_fox_md1`'s tones. Fennec may be the equivalent of
Starfield's ethnicity, which would tie each sub-species to its own set of skin tones. Options when
it's time: a recipe per sub-species, or the phenotype taken from the head's name.

## Future: weights on colours (tint masks, beards)

**Status:** future (Bad Dog 2026-11-20). Not needed for the hyena; wanted mainly for beard colours.

A generic syntax for weighting colours, the way `weights = { Label = n }` weights options. Today a
mask layer's colours (a Modulation group, or a `#rrggbb` list) all take the mask option's weight,
so a recipe can't say "Rusty_black rarely" or "never Black". Beards are the bigger want: `[beards]
colors` names the Simple AVM group the addon points at, and the game picks from it at random, so
weighting there isn't a bake-time choice -- it would have to be written into the group the plugin
builder makes (repeated entries, or a trimmed group per breed). Design one syntax that serves
both: labels as the group's LNAMs (case as in the plugin), 0 = never, unnamed = 50.

## Hair fit: one cloth bone plane, not one per particle

**Status:** to do (Bad Dog 2026-11-23). Works in game as is; tidy-up.

`hair_fit.fit_cloth` shifts each bone-plane record by its particle's move along the plane's
normal, and gives particles with different shifts their own copy of the plane. The female
ponytail's one C_Neck plane (particles 0-3) became 4 planes about 1 mm apart. Keep one plane per
vanilla record instead, shifted by the smallest of its particles' moves, so no particle starts
closer to the bone than it did in vanilla.
