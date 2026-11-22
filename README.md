# FSFTools

Tools for building furry races for Starfield, and for putting them into the game's population.
They ship with FSF (Furry Starfield), and work for any custom race.

| Tool | What it does |
|---|---|
| `sf_furrify.py` | Makes the NPC population furry: classifies human NPCs, assigns races by weighted probability, and writes one plugin with the NPC overrides and the crowd outfits and heads. Optionally bakes their FaceGen. |
| `sf_racecheck.py` | Audits a custom race: records, head parts, morphs, materials, textures, tint groups and crowd heads. Run it first when a race misbehaves. |
| `sf_tintbake.py` | Bakes crowd-head variants. A crowd head has one texture, so the variety chargen gets from skin tones and tint layers is baked into separate textures and heads. |
| `uv_transfer.py` | Paints part textures (head, eyes, hands...) onto a joined mesh's UV layout, as crowd heads need. Runs inside Blender to make the map, and from the command line to paint. |
| `sf_texconv.py` | Converts PNG texture sets to DDS the way vanilla stores each kind. |
| `sf_race_copy.py` | Makes a new species from an existing one: copies its own records, shares the rest. |

## Installing

- Python 3.11 or later, with `numpy` and `Pillow`.
- [PyNifly](https://github.com/BadDogSkyrim/PyNifly) installed in Blender. The tools use its `pyn`
  library and DLL from the installed extension. Set `PYNIFLY` to a PyNifly folder to use another.
- esplib: `pip install esplib`, or set `ESPLIB` to its folder.

## Data

A race's data ships with its mod, under `Data\FSFTools`:

```
FSFTools\
  furrify\scheme.toml          which NPCs become which race
  furrify\races\<Race>.toml    each race: tones, tint layers, breeds, morph ranges, crowd manifests
  furrify\race_copies\         race_copy configurations
  crowd\<race>\                sf_tintbake recipes, UV maps, paint scripts and variant manifests
```

The furrifier reads `scheme.toml` and `races` from there by default. Paths inside these files are
relative to the file, so the folder works wherever it is deployed.

## Docs

- `docs/Crowd_Race_Instructions.md`: building a crowd race, end to end.
- `docs/plan_*.md`: design notes.

## Tests

```
python -m pytest                    # the tools; reads the game's Data folder
blender --background --python tests/blender/run_blender_tests.py      # uv_transfer in Blender
```

The tests never read the live mod. They keep their own race and scheme files in `tests/fixtures`,
and a snapshot of FSF (`tests/fixtures/fsf`: its plugins and the files the tests use), read through
an `--overlay` view of the game's Data that hides the deployed FSF. Vanilla is read live: Starfield's
plugins and the unpacked assets (`C:\Modding\Starfield\00StarfieldAssets`). The Blender tests need a
PyNifly source checkout for its test harness.

Refreshing the snapshot (`tests/make_snapshot.py`) is expected to break some tests: each is either
too specific or a real bug. The CK's FaceGen references must be re-baked from the same FSF:
`tests/fixtures/ck_bake/README.txt`.
