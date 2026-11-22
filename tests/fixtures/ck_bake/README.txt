The Creation Kit's FaceGen output, the reference the bake is tested against.

fsftest\  The CK's bake of every NPC in tests\fixtures\fsftest\FSFTest.esm (written by
          tests\make_test_plugin.py, which says what each NPC covers), laid out as the CK writes:
          Meshes\Actors\Character\FaceGenData\FaceGeom\FSFTest.esm\<id>.NIF
          Geometries\<the .mesh files those nifs name>
          Textures\Actors\Character\FaceCustomization\FSFTest.esm\<id>_Color/_Normal/_ao/_rough.dds
          The furry NPCs are 00000800 on; the vanilla human copies follow them.

The rest  The CK's bake of three Starfield.esm NPCs from 2026-11-05, used by test_facegen.py's
          piecewise checks (colour layers, region maps, an eye's nudged vertices).

Refreshing, whenever the FSF snapshot (tests\fixtures\fsf) is retaken. The bake must come from
the same FSF the snapshot holds, so change nothing in FSF between steps 1 and 3:
  1. Take the snapshot: trace a test run, then tests\make_snapshot.py (see its docstring).
  2. Rebuild the test plugin: tests\make_test_plugin.py --force.
  3. Copy FSFTest.esm into the game's Data folder (a plain copy, so the CK can't write to the
     fixture). In the CK load FSF.esm, FSFPlayer_FOX.esm and FSFTest.esm (none active; don't
     save), select every FSFTest_ NPC and bake FaceGen. FSFPlayer_FOX.esm is there for its
     BeardFollicleMask group: a ruff's follicle mask (NAM3) is only found where that group is,
     and our bake reads it from the race's tint plugin. (FSFPlayer_HYENA.esm holds the same
     group; either will do.) Don't load the furrifier's output (FSFNPC*.esm).
  4. Copy the CK's output from Data into fsftest\, with the layout above: each nif, its four
     textures, and every .mesh the nif names. Then delete FSFTest.esm and its FaceGen folders
     from Data.
  5. Run the tests and triage what breaks: a test that's too specific, or a real bug.
