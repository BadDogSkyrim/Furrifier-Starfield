# Fur Layer Generator — plan

A tool that takes a tree of hand-authored fur layers (base tints, cheek patches, muzzles,
eyebrows, …) and produces every combination as a Starfield face-customization texture, in
the game's format, ready to drop into a race's `postblenddetails` tree.

Working name: **`scripts/sf_layergen.py`**. Sits next to `sf_texconv.py` (PNG→DDS) and
`sf_racecheck.py` (audit), and hands off to both.

---

## 1. What the game gives us

Verified, with sources. The numbers drive every decision below.

### Three full-colour slots, not one

Only `Dermaesthetic`, `Complexion1`, `Complexion2` composite **below scars**; everything
above is conceived as makeup and paint. All three take a Simple group of `*_color.dds`
where **the texture's own alpha is the strength** — there is no per-slot blend mode.

All three are reachable in the character creator. Probed from `Starfield.esm`:

| group | kind | entries |
|---|---|---|
| `SimpleGroup_Dermaesthetic` | Simple | 84 |
| `SimpleGroup_Chargen_Complexion1` | Simple | 13 |
| `SimpleGroup_Chargen_Complexion2` | Simple | 13 |
| `SimpleGroup_chargen_DermaestheticSkinTone0`…`8` | Simple | 63 each |

⚠ `plan_furry_races.md` records Complexion2 as "does not seem to be accessible in the UI".
The chargen-side group exists with 13 entries, so either the note is wrong or something
else suppresses it. **One in-game look settles it** — see Phase 0.

Stack order is fixed and built into the engine (proven: reordering
`PostBlendFaceCustomizationLayers` *and* reordering in the NPC record both failed).
Bottom to top: `Dermaesthetic` → `ComplexionMask1` → `Complexion1` → `Complexion2`.
So a base wash on Dermaesthetic with two pattern layers above it composites in the order
you would want anyway.

### Dermaesthetic is free real estate

Not tied to skin tone, despite the naming. Measured over 2,949 vanilla NPCs carrying both
a `Dermaesthetic` layer and a `STON`: **466 agree (15.8%), 2,483 do not**, and the
phenotype matches one the NPC actually blends only 45.7% of the time. It is an independent
overlay picked by eye. Nothing stops us keying it however we like.

### The chargen filter is the gate, and it is global

`ComplexGroup_Chargen_Dermaesthetic` `[000D4004]` has 9 entries, one per skin-tone
**index**, each pointing at a `chargen_DermaestheticSkinTone<n>` Simple group of 63
options. The creator offers the intersection of the master list and the filter group for
the character's tone.

Consequences for us:

- A new derm option is invisible in chargen until it is added to the filter group for
  **every tone index the fox races use**. One option → up to 9 plugin entries.
- The filter is **keyed by tone index and shared by every race**. There is no per-race
  variant. Whatever goes there, a human character in the same load order sees too — so it
  ships in `FSFPlayer_CANINE.esm`, not the race plugin. Same pattern as Felid's
  `FelidRace.esm` / `FelidPlayer.esp` split.
- The CK validates filter ⊆ master list ("all entries from skin tone filters are valid
  entries from the main Dermaesthetic reserved type"), so a stale filter entry is a
  reported error. The generator must emit both sides together or neither.

### Format, exactly

1024×1024, single mip, DX10 `R8G8B8A8_UNORM_SRGB`, **4,194,452 bytes** each. Uncompressed —
the game rejects BCn here. Bethesda's header fields differ from a default `texconv` run
(`dwFlags` `0xA1007`, whole-image size field, `dwDepth` 0, `dwCaps` `0x401008`,
`alphaMode` 0), and a mod author has reported the creator's dermaesthetic chooser
rejecting correctly-formatted layers carrying texconv's header.

**`sf_texconv.py` already does all of this** for any `*_derm_color.png`, including the
vanilla-header rewrite. The generator writes PNGs; it does not write DDS.

### Two authoring rules worth enforcing in code

From the vanilla census, both of which a naive compositor gets wrong:

1. **Real colour under transparent pixels.** Vanilla keeps skin colour in RGB beneath
   fully-transparent areas so bilinear filtering never bleeds a halo at an edge.
   Transparent-*black* padding fringes dark; transparent-white fringes light.
2. **Alpha goes to 0 at the neck seam** so the layer blends into the body.

Also: vanilla derm layers are *soft*. In a sampled file only **63 pixels of a million
exceed alpha 250**, and the commonest non-zero values are 1 and 17.

---

## 2. Decide before coding

These change the scope, so they come first.

### Q1 — Is the "base tint" fur colour, or a wash over it?

This is the load-bearing one. If a base tint layer is near-opaque it replaces the face
albedo outright, and the face stops tracking `STON` — while the body and hands still do.
Face and body then mismatch unless each base tint is paired with exactly one body tone,
at which point the base tint *is* a skin tone and belongs in `STON`, which already moves
face, body and hands together and is already planned at 8 fox values.

Reading: **base fur colour → `STON`; the layer tool generates pattern only.** That also
deletes a factor from the cross product. If the 4 base tints are instead soft washes
(warmth, sun-bleaching) over whatever `STON` is underneath, they stay in the tool.

### Q2 — How many groups go on runtime slots vs. get baked?

Three slots are free. Assign the three groups that vary most independently; bake the rest.
With 4 base × 3 cheek × 2 muzzle × 2 brow:

| approach | files | on disk |
|---|---|---|
| bake everything | 48 | 192 MiB |
| bake everything, each optional group gaining a "none" (4×4×3×3) | 144 | 576 MiB |
| Derm=base(4), C1=cheek×brow(6), C2=muzzle(2) | **12** | **48 MiB** |
| Q1 answered "STON", Derm=cheek(3), C1=muzzle(2), C2=brow(2) | **7** | **28 MiB** |

At 4 MB apiece this is the difference between a mod that ships and one that doesn't. The
tool should support both — a group is either assigned to a slot or joined into a bake, and
that is config, not code.

### Q3 — Composite in sRGB or linear?

Correct compositing is linear-light; but if the layers were authored by stacking them in a
paint program, that program composited in the working space and what you saw is the sRGB
answer. Matching what you drew matters more than being technically right.
**Proposal: default sRGB, `--linear` to switch.** Cheap either way.

### Q4 — Does the creator cope with a long option list?

Vanilla ships 63 per filter group. Unknown whether the UI pages sensibly at 100+, or what
the cap is. Answered by Phase 0, before any bulk generation.

---

## 3. The tool

### Input: a directory per group

Convention over config, the way `sf_texconv` works. Numeric prefix = composite order,
bottom to top. Directory stem = group name. File stem = the option's token.

```
fur-src/
  10_base/     red.png  cross.png  silver.png  sand.png
  20_cheek/    wide.png  narrow.png  full.png
  30_muzzle/   dark.png  pale.png
  40_brow/     spots.png  bars.png
  _seam.png                  <- optional: final alpha is multiplied by this
```

An optional `layers.json` beside the root carries what convention can't:

- `"optional": true` per group — adds an implicit empty choice, multiplying the count
- `"slot": "Dermaesthetic" | "Complexion1" | "Complexion2"` — this group is *not* baked
- `"exclude"` — pairs that never go together (fennec ears on a red fox, etc.)
- `"name"` — key template, default `<prefix>_<tok>_<tok>…`

### Compositing

1. Load each layer as RGBA, assert identical dimensions, decode sRGB→linear if `--linear`.
2. Straight (non-premultiplied) source-over, bottom to top:
   `a = aₛ + a_d(1−aₛ)`, `rgb = (rgbₛaₛ + rgb_d a_d(1−aₛ)) / a`.
3. **Dilate RGB into transparent regions** — push the nearest opaque colour outward until
   every pixel has a defined colour. Alpha is untouched. This is rule (1) from §1, and a
   plain `Image.alpha_composite` will not do it.
4. Multiply final alpha by `_seam.png` if present.
5. Report alpha statistics per output, and **warn when a composite is substantially
   opaque** — that is the signal it has stopped being an overlay and started replacing the
   fur albedo (Q1's failure mode, caught automatically).

Pillow 12.2 and numpy 2.4 are both already available; numpy does the compositing and the
dilation.

### Output

`<out>/<key>_derm_color.png`, one per combination, then `sf_texconv.py` over the tree.
`--convert` runs it in-process and `--clean` drops the PNGs afterwards.

### CLI

```
python scripts/sf_layergen.py fur-src --out "…\textures\actors\FSFCanine\faces\chargen\postblenddetails\dermaesthetic"
    --prefix male_fox_md1     name template stem
    --dry-run                 list combinations, count, total bytes — no work
    --exclude / --only        narrow the cross product
    --convert [--clean]       hand off to sf_texconv
    --plugin FSFPlayer_CANINE.esm --tones 0,1,2,3   write the AVMD entries (Phase 3)
```

`--dry-run` first, always: it is the thing that stops a 576 MB run.

---

## 4. Phases

**Phase 0 — spike, before writing the generator.** Hand-make 3 or 4 placeholder derm
textures (flat colours are fine), add them to the master list and to one tone's filter
group, and check in the creator that a fox character sees exactly those. Then the same for
`Complexion1` and `Complexion2`. Answers Q2 and Q4 and settles the Complexion2
contradiction for the cost of an afternoon. **Everything downstream is speculative until
this passes.**

**Phase 1 — the compositor.** Directory scan, cross product, source-over, RGB dilation,
seam mask, alpha stats, `--dry-run`. Output PNG only. Tests at the pyn layer
(`tests/pynifly_tests.py`, no Blender needed) on small synthetic layers with known answers,
plus one real-asset case: composite a vanilla derm texture over a flat base and confirm the
result matches a reference.

**Phase 2 — DDS.** Call `sf_texconv`. Verify byte-for-byte that an output header matches a
vanilla derm file, which is the check that actually protects against the rejected-by-the-
creator failure.

**Phase 3 — plugin entries.** esplib can write (`new_record`, `add_record`, `save_as`), so
the tool can emit the `SimpleGroup_Dermaesthetic` override and the
`chargen_DermaestheticSkinTone<n>` filter entries directly into the player plugin —
master and filter together, so they cannot drift. Fallback if that proves fiddly: emit a
CSV plus an xEdit `.pas` script into `C:\Modding\GitTools\xEdit\Edit Scripts`.
Hand-entering 12–144 options × 9 tone groups in xEdit is not a plan.

**Phase 4 — validate.** Extend `sf_racecheck.py`: every option in a filter group exists in
the master list (the rule the CK enforces), every `VNAM` resolves on disk, every derm
texture is the right format and size. Then in-game.

---

## 5. Risks

- **Phase 0 fails** — the creator won't show custom derm options for a custom race. Then
  the whole approach changes and nothing has been wasted. Hence Phase 0.
- **Taking over the global filter groups** makes fox layers visible on human characters in
  the same load order. Mitigated by shipping in the player plugin, not eliminated.
- **Disk size.** 4 MB per texture, uncompressed and non-negotiable. Q2 is the answer;
  `--dry-run` is the guard.
- **Authoring burden shifts, it doesn't vanish.** Every layer has to be drawn to composite
  cleanly with every other layer in its groups — soft alpha, colour under the transparency,
  dead at the neck seam. The tool enforces the last two; the first is drawing.
