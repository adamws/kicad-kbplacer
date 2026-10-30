# Migration from SWIG `pcbnew` to the KiCad IPC API (`kicad-python` / `kipy`)

## Context

kbplacer drives KiCad through the SWIG `pcbnew` module in three ways:

1. **Action plugin** (`kbplacer/__init__.py:34`, `kbplacer_plugin_action.py`): runs in-process
   inside pcbnew, wx dialog, mutates `pcbnew.GetBoard()`.
2. **CLI** (`python -m kbplacer`): headless, `pcbnew.LoadBoard`/`NewBoard`/`SaveBoard` on files.
   This is what `kle-ng-api` workers and `examples/absolem-ergogen` use.
3. **Tests and tools**: fixtures build boards with `pcbnew.FootprintLoad`, assertions reload
   boards, SVG references are rendered with `pcbnew.PLOT_CONTROLLER` (`tests/conftest.py:234`),
   `tools/pcb2layout.py` reads boards with `pcbnew`.

The SWIG bindings are removed in KiCad 11 (stated in the `kicad-python` README). When KiCad 11
is released, kbplacer drops SWIG and supports only KiCad ≥ 11 through IPC. Until then master has
to stay green on the current matrix (6.0, 7.0, 8.0, 9.0, 10.0).

### Size of the job (measured)

| Area | `pcbnew.` references | Hot spots |
|---|---|---|
| `kbplacer/` | ~290 | `board_modifier.py` (86), `key_placer.py` (71), `connection_preset.py` (27), `edge_generator.py` (19), `board_builder.py` (16), `pair_pads.py` (16) |
| `tests/` | ~230 | `test_key_placer.py` (52), `test_board_modifier.py` (51), `conftest.py` (36), `test_with_examples.py` (18) |
| `tools/` | ~36 | `pcb2layout.py` (17), `tests/test_pcb2layout.py` (15), `ipc_spike/swig_reference.py` (2) |

Most-used SWIG API: `FOOTPRINT`, `VECTOR2I`, `PCB_TRACK`, `BOARD`, `PAD`, `Add`, `GetValue`,
`GetReference`, `GetNetCode`, `Pads`, `FindPadByNumber`, `SetPosition`, `Rotate`, `Flip`,
`Duplicate`, `Collide`, `HitTest`, `GetBoundingHull`, `GetEffectiveShape`, connectivity
(`GetConnectedTracks`/`GetConnectedPads`), `SHAPE_POLY_SET` inflate/deflate, `FootprintLoad`.

Eight test modules have no pcbnew dependency: `test_kle_serial`, `test_element_position`,
`test_preset_format`, `test_project_builder`, `test_schematic_project`, `test_pair_pads`,
`test_performance`, `test_gui`. They need no changes. The schematic builders are file-based
(kicad-skip) and use pcbnew only for `KICAD_VERSION`. `test_pair_pads` has no pcbnew import,
but the module it tests does: `pair_pads.py:74` builds a board with `CreateEmptyBoard` and loads
footprints by identifier.

## Gap analysis: what kbplacer needs vs. what `kipy` provides

Checked against `kicad-python` at `87b945a` (0.9.0.dev0). The Status column is updated with the
chunk 0 results from `docs/ipc-migration-spike-0.md` (KiCad nightly 2026-09-14).

| kbplacer needs | SWIG today | IPC / kipy | Status |
|---|---|---|---|
| Open/save board headless | `LoadBoard`/`SaveBoard` | `KiCad(headless=True, file_path=…)` → `kicad-cli api-server` (**KiCad 11 only**), `board.save()`/`save_as()` | OK on 11 |
| Create new board (`--create-pcb-file`) | `NewBoard`/`CreateEmptyBoard` | `KiCad.create_document` | Verify on 11 |
| Load footprint from a `.pretty` **path** (`lib.pretty:FP`, `tests/data/footprints/tests.pretty`) | `FootprintLoad(path, name)` | `place_footprint_from_library` / `get_library_footprint` take a lib-table **nickname** and need `load_all_libraries` in headless mode | **Workaround verified:** wrap `.kicad_mod` in a board file, load it in an auxiliary server, copy the instance. Library commands untested (server too old) |
| Move / rotate / flip footprint with its children | `SetPosition`, `Rotate`, `Flip` | `FootprintInstance.position`/`orientation`/`layer` setters + `update_items`, `flip_items` | **Verified:** move and rotate are identical to SWIG; the `xfail` no longer reproduces. **Flip differs:** kbplacer's SWIG `set_side` = top-bottom mirror at 0°, `flip_items` default = left-right at 180°. Never use the `layer` setter |
| Nets: create/assign | `NETINFO_ITEM`, `AppendNet`, `SetNet` | `Net` wrapper; assigning `Net(name=…)` to a new item creates the net | **Verified** |
| Tracks/vias create/remove | `PCB_TRACK`, `PCB_VIA`, `board.Add` | `create_items`, `remove_items`, commits | OK |
| Collision with clearance (core of the router, `board_modifier.py:384-492`) | `SHAPE.Collide(shape, clearance)`, `GetBoundingHull`, `HitTest` | `hit_test(item, point)` only, `get_pad_shapes_as_polygons`, design rules (`min_clearance`); **no collide, no hull, no per-item clearance** | **Gap:** pure-Python geometry |
| Connectivity of the board as read | `CONNECTIVITY_DATA` | `get_connected_items` (KiCad ≥ 10.0.1) | OK at snapshot time only |
| Connectivity **during** a run (`get_connection_template` `key_placer.py:739`, collision `board_modifier.py:438`) | `GetConnectedTracks`/`GetConnectedPads` on items just added | none: by W7, items staged in the open commit aren't visible to reads | **Gap:** local connectivity on `BoardModel` |
| Dangling track removal (`remove_dangling_tracks`, `key_placer.py:623`, runs after routing) | `TestTrackEndpointDangling` in a loop | none | **Gap:** local dangling test on `BoardModel` |
| Netclass / clearance | `GetNetClasses`, `GetOwnClearance` | `get_netclass_for_nets`, `get_design_rules` | Partial; own clearance resolution |
| Outline inflate/deflate, convex hull (`edge_generator.py`) | `SHAPE_POLY_SET` | none | **Gap:** pure-Python geometry |
| Read a second board (connection presets `.kicad_pcb`, `template_copier`) | `LoadBoard(template)` | GUI pcbnew holds one board; headless can open a document | One project per server (`open_document` refused). **Verified:** an auxiliary headless server (0.2 s start) and copying items across servers works |
| Write a second board (`save_connection_template`, `key_placer.py:645`; `pair_pads.py:74`) | `NewBoard`/`CreateEmptyBoard` + `SaveBoard`, then delete the `.kicad_pro` | auxiliary server + `create_document` + `create_items` + `save()`, or an s-expr writer | **Unverified** |
| Create a footprint already on the back side (`board_builder`, `template_copier`) | `board.Add` then `Flip` | `FlipItems`/`UpdateItems` on an item created in the same commit fail (`ISC_NONEXISTENT`); `CreateItems` of an already-flipped copy works | **Verified workaround**, see W11 |
| Version detection (`board_modifier.py:35`) | `pcbnew.Version()` | `KiCad.get_version()` | Trivial |
| Action plugin + dialog | `ActionPlugin`, in-process wx | `plugin.json` action runs an external process in a venv; no in-process wx | **Gap:** packaging and GUI toolkit decision |
| Render SVG for test references | `PLOT_CONTROLLER` | `board.export_svg` (11) or `kicad-cli pcb export svg` (≥ 7) | OK |
| DRC in tests | `WriteDRCReport` | `kicad-cli pcb drc` (already used in `conftest.py:374`) | OK |

Takeaways:

- **The CLI can only go IPC on KiCad 11.** Headless `api-server` doesn't exist in 10, and KiCad 10
  IPC needs a running GUI pcbnew. So the IPC backend targets 11. KiCad 10 is used only to
  cross-check against SWIG where both APIs exist (see A/B section).
- **Connectivity during a run has to move into kbplacer too.** Routing, template extraction and
  dangling-track removal all query connectivity of tracks the run just added, which W7 makes
  invisible to IPC reads. `BoardModel` needs its own item adjacency and dangling test.
- **Collision and outline geometry have to move into kbplacer.** It's the riskiest part and it
  doesn't depend on IPC, so it can be done and verified early on SWIG.
- **IPC is chatty.** Measured: about 10 ms per request regardless of payload. The router
  queries every footprint and track for each candidate segment. Doing that over IPC per call
  would be very slow. The design must take one snapshot of the board into memory, compute
  locally, and write back in bulk: **never one request per moved footprint or added track**.
  The verified rules are in "IPC write model" below. Measure with the existing
  `tests/test_performance.py` benchmark.

## Target architecture

```
kbplacer/
  model.py            # backend-neutral types: Point(nm ints), Angle, Side, Layer, Footprint,
                      # Pad, Track, Via, Net, Shape; plain dataclasses, no pcbnew/kipy
  geometry.py         # segment/capsule/polygon/circle collide-with-clearance, hull,
                      # offset (inflate/deflate), rotate/flip transforms
  backend/
    __init__.py       # Backend protocol + select_backend() (explicit flag, env
                      # KBPLACER_BACKEND, else "pcbnew importable ? swig : ipc")
    swig.py           # the only module that imports pcbnew (deleted at the KiCad 11 cutover)
    ipc.py            # the only module that imports kipy
  board_modifier.py, key_placer.py, edge_generator.py, ...  # operate on model + Backend
```

`Backend` protocol (start small and grow it per chunk):
`version()`, `load(path)`/`create(path)`/`save()`, `snapshot() -> BoardModel`,
`load_footprint(lib_path, name)`, `apply(changes: ChangeSet)`, `netclass_clearance(net)`.

Algorithms never call the backend to mutate one item. They mutate the `BoardModel` and record
the change in a `ChangeSet` (`flips`, `updates`, `creates`, `removes`, each keyed by item id so
repeated edits of one item collapse into one entry; an item created and then removed in the
same run, e.g. a dangling track, cancels out and is never sent). The backend applies the whole `ChangeSet`
at the end of a run. `SwigBackend.apply` replays it with `board.Add`/`SetPosition`/`Flip`, so the
batching discipline is enforced and A/B-tested on KiCad 6–10 long before IPC is switched on.

### IPC write model (verified 2026-10-29, `tools/ipc_spike/probe_batching.py`)

| # | Fact | Consequence for kbplacer |
|---|---|---|
| W1 | A request carries **exactly one command** (`ApiRequest.message` is a single `Any`). No envelope combines e.g. update + create | "Joining operations" means: one list per command type, all inside one commit |
| W2 | `CreateItems`, `UpdateItems`, `DeleteItems` and `FlipItems` take **lists**, and lists may **mix types**: one create of footprint + tracks + via, one update of footprints + tracks | One request per command type per run, not per item |
| W3 | One footprint update carries position **and** orientation **and** pad nets together. All 8 footprints moved+rotated in 1 request, pads follow rigidly. Pad nets set on `definition.pads` create missing nets | No separate "rotate" or "assign net" requests |
| W4 | Flip **cannot** be expressed as an update (the `layer` setter leaves pads unmirrored). `FlipItems` is a separate command. `BFD_TOP_BOTTOM` reproduces kbplacer's SWIG `set_side` exactly; kipy's default `BFD_LEFT_RIGHT` does not | Apply order: `FlipItems(all side changes, BFD_TOP_BOTTOM)` **first**, then `UpdateItems` |
| W5 | `UpdateItems` **replaces the whole item**. A footprint object read before a flip and sent afterwards silently un-flips it. The object kipy refreshes in place inside `flip_items` is **not** usable either: it has back-side layers but pre-flip pad positions, and updating it moves the footprint while its pads stay behind (`update_after_flip_source_object`) | After `FlipItems`, **re-read** the flipped footprints with one `get_footprints` (flips are visible inside the commit, W7) and build updates from that read only. +1 request per run |
| W6 | `begin_commit`/`push_commit` is an **undo/atomicity unit, not request batching**. Each command inside still costs one request | One commit per kbplacer run = one undo step in the GUI |
| W7 | Inside an open commit, staged updates/creates are **not visible to reads**, but flips are | Never read back inside a commit, except the post-flip re-read of W5. The local `BoardModel` is the only source of truth during a run |
| W8 | **No per-request atomicity:** a batch with one bad item applies the good ones and reports `ISC_NONEXISTENT`/`ISC_EXISTING` per item. kipy's `create_items`/`update_items` **discard** these statuses | `IpcBackend` sends raw commands and checks every item status. On any failure → `drop_commit` (verified: rolls back moves, creates **and** flips) → raise `PluginError` |
| W9 | Payload size is not a constraint: 20 000 tracks in one `CreateItems` take 0.36 s | No chunking needed at keyboard scale. Keep a 5 000-item chunk guard anyway |
| W10 | ~10 ms per request, any command | A complete run is a fixed ~10 requests (≈0.1 s), whatever the board size |
| W11 | `FlipItems` **and** `UpdateItems` on an item created earlier in the same open commit return `ISC_NONEXISTENT`; the item stays as created (`w11_flip_created_in_same_commit`). `CreateItems` of an already-flipped, locally moved copy gives correct pads, if the copy comes from a **fresh read** after the flip, not the `flip_items`-refreshed object (`w11_create_already_flipped`). Two commits (create, then flip) also work but cost two undo steps | New footprints are created in their **final state**: side, position, orientation, pad nets, all in the one `CreateItems`. Get the flipped source by flipping in the throwaway auxiliary server (which loads library footprints anyway) and re-reading it; then translate/rotate locally. Never flip or update an item created in the same commit |

A complete run is therefore a fixed sequence (verified with 10 requests on the 2x2 example,
`kbplacer_like_run`):

```
snapshot: get_footprints, get_tracks (+vias), get_nets, [design rules, netclasses, pad polygons]
compute:  everything locally on BoardModel (placement, templates, routing, collision, outline)
apply:    begin_commit
          FlipItems(all side changes, BFD_TOP_BOTTOM)
          get_footprints                            # re-read flipped state (W5)
          UpdateItems(all modified footprints + tracks, built from that re-read)
          CreateItems(all new tracks, vias, outline shapes, and new footprints
                      already in final side/position/orientation, W11)
          DeleteItems(all removed items)            # e.g. remove_dangling_tracks
          push_commit  — or drop_commit on any per-item failure
save:     save()                                    # CLI only; GUI leaves it to the user
```

Interleaving matters too: kbplacer routes **after** placing, using pad positions at the new
placement. Because of W7, those positions can't be re-read from KiCad inside the commit.
`geometry.py` must therefore transform pad shapes locally: fetch `get_pad_shapes_as_polygons`
once at snapshot time, then apply the footprint's rigid transform and top-bottom mirror. The
fallback (two commits: placement, re-snapshot, routing) costs a second undo step and is only
acceptable for the CLI.

Why a model + adapters and not a pcbnew-lookalike shim on top of kipy: a shim keeps SWIG
semantics (wxPoint/VECTOR2I, ×10 angles, Cast_to_*, per-call round trips) and fixes nothing
about chattiness. With a model, a backend adapter is the only place KiCad semantics live. That
also makes A/B testing cheap: same algorithm, two adapters, compare outputs.

Migration style is strangler: move one concern at a time behind the seam, keep master green on
6–10, and never fork the algorithm.

## Is A/B testing required?

**Yes, as differential testing in CI. No, as a user-facing experiment.** The risk is silent
geometric differences, not crashes: rotation sign (`rotate()` passes `angle * -10` on KiCad 6),
flip mirroring axis, whether footprint moves carry pads (the bug `test_ipc.py` documents), ±1 nm
rounding, net assignment on new tracks. Golden SVGs catch some of this, but they're coarse
(silkscreen layers are skipped, and a tiny offset can still render the same).

SWIG's own flip is not stable across versions: `set_side` rotates 180° after `Flip` only on
KiCad ≥ 9 (`board_modifier.py:153`), so `BFD_TOP_BOTTOM` matches SWIG on 9 and 10 only. All
reference snapshots must come from SWIG@10, never from a 6–8 run.

Three levels, cheapest first:

1. **Primitive shadow tests (KiCad 10, SWIG only).** Run the new `geometry.py` collide, hull and
   offset next to SWIG `SHAPE.Collide`/`GetBoundingHull`/`SHAPE_POLY_SET` on every example plus
   randomized/property cases. KiCad polygonizes arcs and rounded pads with a max-error
   tolerance, so near-touching cases will legitimately disagree with float math: cases within a
   tolerance band (a few hundred nm of touching) are recorded, not failed. Fail on any
   disagreement outside the band. Also shadow-test connectivity and dangling detection against
   `CONNECTIVITY_DATA`. Gates the switch to Python geometry (chunk 4).
2. **Backend contract tests (KiCad 10 GUI+IPC via xvfb, KiCad 11 headless).** One parametrized
   suite runs each primitive operation (place, rotate, flip, add track, assign net, load
   footprint) through `SwigBackend` and `IpcBackend` and compares normalized snapshots. On
   nightly this doubles as an early warning for upstream kipy regressions. The KiCad 10 run is
   **required**, not optional: it is the only same-version SWIG vs IPC comparison. Level 3
   changes backend and KiCad version at once, so a mismatch there may come from KiCad 11 itself
   (default widths, netclass resolution, polygonization).
3. **End-to-end snapshot equivalence (cross-version).** `test_with_examples` writes a
   normalized JSON snapshot of the produced board (footprints by reference: position,
   orientation mod 360, side, absolute pad positions; tracks/vias as an unordered set with
   endpoint-normalized direction, layer, width, net name; outline segments; UUIDs ignored).
   Snapshots generated with SWIG@10 are committed next to the SVG references. IPC@11 must match
   them within a 1–2 nm tolerance. Both runs don't have to happen in the same job, which matters
   because no single KiCad version has both SWIG and headless IPC.

Not needed: shipping both backends to users and comparing at runtime. A temporary opt-in switch
(`--backend ipc` / `KBPLACER_BACKEND=ipc`) during the transition is enough for kle-ng-api to
canary IPC on a KiCad 11 nightly worker before the cutover.

## Deliverable chunks

Each chunk is a self-contained PR (or short PR series) that leaves master green on the current
matrix. **PoC = chunks 0–2**: by the end of chunk 2 the test suite can verify an IPC board, with
no production code changed yet.

### Chunk 0: Feasibility spike — done 2026-10-29, see `docs/ipc-migration-spike-0.md`

Open items left over: library commands (nightly PPA stale since 2026-09-15), GUI toolkit (no
Linux wxPython wheels), the `(transform …)` file format change. W11 was answered on 2026-10-29
(see the write model). The exit criterion "each gap has an owner" is not met yet: the six upstream
items in the spike report still have to be filed and linked here.

Original scope:

- Build a KiCad 11 nightly image (`.circleci/images/jammy/nightly.Dockerfile`) with `kicad-cli
  api-server`. Record whether nightly still ships `pcbnew` SWIG.
- In a scratch script against headless 11, verify every **Verify**/**Gap** row in the table:
  footprint from an arbitrary `.pretty` path, `create_document`, net creation, footprint
  move/rotate/flip incl. pads (re-run the `xfail` test), back-side placement, `save_as`.
- Measure IPC cost: `get_footprints`/`get_tracks` on the largest example and the round trips per
  routed key.
- **GUI toolkit decision** for the IPC action plugin: wxPython inside the plugin venv works on
  Windows/macOS with KiCad's bundled Python. On Linux there are no PyPI wheels for most distros.
  Options: wx via system site-packages, tkinter, or minimal "CLI-from-plugin" with a settings
  file. Pick one.
- Exit criterion: gap matrix filled in, each gap has an owner (kbplacer workaround or upstream
  issue on gitlab.com/kicad/code/kicad-python or kicad).

### Chunk 1 (PoC, part 1): Backend-neutral test oracles

Goal: e2e assertions no longer need `import pcbnew`, so the same tests can judge an IPC board.

- `tests/board_snapshot.py`: parse a saved `.kicad_pcb` with `sexpdata` (already a test
  dependency) into the normalized snapshot described in the A/B section. It must read both the
  `(at x y a)` placement and the KiCad 11 `(transform (translate …) (rotate …) (scale …))` form
  (spike report, "Other findings"); cover both with fixture files. `pair_pads.py`'s JSON
  dump is a precedent for the shape.
- Generate and commit snapshots for `tests/data/examples-references/*` on KiCad 10. Add the
  snapshot assertion next to the SVG check in `assert_example` (`test_with_examples.py:216`).
- Replace the `PLOT_CONTROLLER` render (`conftest.py:234-350`) with `kicad-cli pcb export svg`
  for KiCad ≥ 8. Check that the references are unchanged; if they aren't, regenerate them in a
  separate reviewed commit. KiCad 6/7 keep the old path until they're dropped.
- Replace `pcbnew.WriteDRCReport` (`conftest.py:393`) with `kicad-cli pcb drc` everywhere.
- Done when `test_with_examples.py` imports pcbnew only in fixtures that build input boards,
  never in assertions.
- **Progress 2026-10-30:**
  - `tests/board_snapshot.py` parses KiCad 6–9 (numbered nets), 10 (nets by name) and
    11 (`(transform …)`) files. `tests/test_board_snapshot.py` checks it against
    `pcbnew.LoadBoard` (all example boards, on 6–10) and the 10 vs 11 format on the same
    board; ad hoc, 100/100 KiCad 10 outputs of the example tests matched pcbnew exactly.
  - Snapshot references are **per test function**, not per SVG reference directory: tests
    sharing SVG references differ in what SVGs don't show (net names like `N$1` vs
    `Net-(D1-A)`, library nicknames, Edge.Cuts). Layout/preset variants of one test share a
    snapshot and must match each other. Regenerate with `--save-snapshots-as-reference` on
    KiCad 10 (the SVG option can't be used for non-parametrized tests).
  - **KiCad 8, 9 and 10 produce identical snapshots** (≤ 2 nm) for all 79 example tests, so
    the snapshot is compared on every version, not only ≥ 10. On 6/7 only the board outline
    differs (offsetting), so `outline` is ignored there.
  - `common_board_checks`, the template and outline assertions now use the snapshot. The
    snapshot reads nets as stored; pcbnew assigns nets to `(net 0)` tracks on load, so the
    check is stricter than before (passes on 6–10).
  - `generate_render` uses `kicad-cli pcb export svg` on KiCad ≥ 8 (`--mode-multi` on ≥ 9,
    one call per layer on 8), `PLOT_CONTROLLER` stays for 6/7. Same drawing, but
    `kicad-cli` has no SVG precision option and writes 4 decimals instead of 3, so the 8, 9
    and 10 SVG references were regenerated (separate commit). Normalizing numbers instead
    does not work: two independently rounded sources disagree on the last digit.
  - SVG comparison tolerates numbers differing by one unit in the last decimal place: a
    1 nm board difference (e.g. after rotating a reference pair by 60° and back) can flip
    the 4th decimal. Exact geometry is the snapshot's job.
  - `kicad-cli pcb drc` only exists from KiCad 8, so `WriteDRCReport` stays for 6/7 until
    they are dropped. Without pcbnew (KiCad 11) `prepare_kicad_config` must find the
    config dir itself so `--theme user` resolves; not done yet.
  - Pre-existing: `Edge_cuts` in the render layer list never matched KiCad's `Edge_Cuts`,
    so the outline was never plotted or compared as SVG. Left as is; the snapshot covers
    the outline.

### Chunk 2 (PoC, part 2): IPC test harness and contract tests

- **Prerequisite:** a fresh KiCad 11 nightly image. The Ubuntu PPA has had no build since
  2026-09-15, so library commands can't be tested. Pick a source (KiCad's official nightly
  docker image or a self-built image), give it an owner, and switch
  `.circleci/images/jammy/nightly.Dockerfile` before the CI job below.
- Session fixture `kicad_ipc`: headless `kipy.KiCad(headless=True)` on ≥ 11. On 10, reuse the
  existing xvfb `background_kicad` (`test_ipc.py:113`). Add a pytest option
  `--backend {swig,ipc}` and make `import pcbnew` in `conftest.py` conditional, so the suite
  collects on a KiCad without SWIG.
- Add `kicad-python` to the `test` hatch env (pinned; follow the KiCad 11 tag).
- `tests/test_ipc_contract.py`: small, focused tests of the kipy behaviour kbplacer relies on
  (rotation direction, flip axis, pads follow footprint, nm units, net assignment, footprint
  from lib path) **and the write-model facts W1–W9** (mixed-type batches, stale-update
  overwrite, commit visibility, partial failure statuses, `drop_commit` rollback incl. flips)
  plus W11 (flip/update of an item created in the same commit fails, creating an
  already-flipped copy works) and the W5 follow-up (`flip_items`-refreshed objects keep pre-flip
  pads). Compare pads as a
  multiset, not keyed by number (unnumbered NPTH holes collide).
  Port them from `tools/ipc_spike/probe_batching.py`. Upstream may change commit staging, and
  these tests are the alarm. They're expected to pass on 11 nightly. **Started 2026-10-29:**
  W5 and W11 are in (`ipc` marker, own headless server per test; two strict `xfail`s track the
  kipy `flip_items` refresh bug), and `conftest.py` collects without `pcbnew`. Fold in and un-`xfail`
  `test_footprint_move`.
- CI: add a `test-linux-kicad-nightly` run with `--backend ipc -m ipc` (non-blocking at first,
  like the current nightly job). **Started 2026-10-29:** `test-linux-kicad-nightly-ipc` in the
  `nightly` workflow runs `-m ipc tests/test_ipc_contract.py`; kicad-python (pinned ref) is
  baked into `.circleci/images/jammy/nightly.Dockerfile`. `--backend ipc` comes with the option.
- Done when CI on nightly shows which contract tests pass. That is the evidence base for
  chunks 3–5.

### Chunk 3: Backend seam with SWIG adapter (no behaviour change)

Sub-PRs, each green on 6–10:

1. `KICAD_VERSION` from `backend.version()`; schematic modules
   (`schematic_builder.py:10`, `led_schematic_builder.py:9`, `schematic_project.py:10`,
   `footprint_loader.py:14`) stop importing `board_modifier` for it.
2. `model.py` types plus footprint transforms: move `set_position`/`rotate`/`set_side`/
   `get_orientation` (`board_modifier.py:133-197`) into `backend/swig.py`. Keep the KiCad 6
   `wxPoint` branches there.
3. Pads/nets/netclass (`get_pads_by_net`, `get_netclass`, `board_builder._add_or_get_net`).
4. Tracks/vias (`_build_track_segment`, `duplicate_track`, `connection_preset._build_item`).
5. Footprint loading (`footprint_loader.load_footprint`) and board IO (`kbplacer_plugin.run_board`),
   including the secondary boards kbplacer writes: `save_connection_template`
   (`key_placer.py:645`) and `pair_pads.py` (`CreateEmptyBoard`). Both need a
   `backend.create_secondary(path)` (auxiliary server under IPC).
6. `ChangeSet` + `SwigBackend.apply`: algorithms stop mutating SWIG objects directly and record
   changes instead (see "IPC write model"). This is the largest refactor in the chunk. Watch for
   code that reads back what it just wrote (pad positions after a move, net codes after
   `AppendNet`, connectivity of just-added tracks in `get_connection_template` and
   `remove_dangling_tracks`); it must read the `BoardModel` instead. A new footprint enters the
   `ChangeSet` as one `creates` entry in its final state, never as create + flip/update (W11).
- Track progress with a `grep -c "pcbnew\."` count outside `backend/swig.py`, aiming for 0. Add
  a ruff `banned-api` rule for `pcbnew` outside the backend once a module is clean.

### Chunk 4: Pure-Python geometry and collision (A/B level 1)

- `geometry.py`: capsule (track), polygon with holes (pad shapes; from SWIG
  `GetEffectiveShape` now, `get_pad_shapes_as_polygons` later), circle (via), point-in/hit-test,
  rigid transform + top-bottom mirror of pad shapes fetched once (needed for W7, see
  "IPC write model"),
  convex hull, polygon offset with chamfered corners (matches
  `CORNER_STRATEGY_CHAMFER_ALL_CORNERS`).
- Hull: IPC only offers `get_item_bounding_box`. To match `GetBoundingHull` the snapshot must
  carry the footprint's graphic items (from the footprint definition), not just pads.
- Connectivity on `BoardModel`: item adjacency from shared track endpoints, track–pad and
  track–via overlap per layer, plus a dangling-endpoint test replacing
  `TestTrackEndpointDangling`. It must include items created during the run.
- Use int/float math, not Decimal. Consider `shapely` only if it can be a declared IPC-plugin
  requirement on all three platforms.
- Rewrite `BoardModifier._test_collision_*`, `remove_dangling_tracks`,
  `get_connection_template` and `edge_generator` to run on a `BoardModel` snapshot.
  `get_connected_items` (IPC) / `CONNECTIVITY_DATA` (SWIG) only seed connectivity at snapshot
  time; from then on the local connectivity is the source of truth (W7).
- Shadow test against SWIG `Collide`/hull/offset/connectivity/dangling on all examples plus
  randomized cases. Switch the SWIG path over only at zero disagreements outside the tolerance
  band (see A/B level 1), with the final `kicad-cli pcb drc` in e2e tests as the arbiter, and
  within benchmark budget
  (`hatch run test:benchmark`).

### Chunk 5: IPC backend for the CLI (KiCad 11, headless)

- `backend/ipc.py`: start or connect to `api-server`. `snapshot()` in a fixed handful of `get_*`
  calls. `apply(ChangeSet)` exactly as the fixed sequence in "IPC write model": one commit, one
  request per command type, raw commands with per-item status checks, `drop_commit` on failure.
  Footprint loading via the chunk 0 auxiliary-server workaround. Create/save.
- Request-count guard test: **each kbplacer run** in `test_with_examples` must stay ≤ 15
  requests on the main server (count via a wrapping client, as in `probe_batching.py`), so
  per-item regressions fail CI instead of showing up as slowness. Count auxiliary-server
  traffic (footprint loading from `.pretty` paths, templates) separately, with its own budget:
  server starts per run and requests per loaded library.
- `--backend` CLI flag and `KBPLACER_BACKEND` env var, auto-detect default.
- Run the full `test_with_examples` + `test_cli` with `--backend ipc` on nightly. They must match
  the chunk 1 SWIG@10 snapshots (A/B level 3). Port `test_board_modifier`/`test_key_placer`
  fixtures to build boards through the backend instead of `pcbnew.FootprintLoad`
  (`conftest.py:531`).
- Done when the nightly IPC job is green and promoted to blocking.

### Chunk 6: Templates and presets under IPC

- Connection presets from `.kicad_pcb` (`key_placer.load_kicad_pcb_preset`) and
  `template_copier`: read via an auxiliary headless server (verified in chunk 0; a second
  document in the same server is refused).
- Writing connection templates (`save_connection_template`): create the board in an auxiliary
  server and save it, without leaving a `.kicad_pro` behind. Alternatively emit the JSON preset
  only.
- Promote the JSON preset (`preset_format.py`, `docs/switch-preset.schema.json`) as the
  recommended format. Add a converter `.kicad_pcb` → JSON preset (`connection_preset.py` already
  has `_to_json`).

### Chunk 7: IPC action plugin (GUI)

- `plugin.json` action (identifier, entrypoint, runtime python, `requirements.txt` with
  `kicad-python` pin), using the GUI toolkit chosen in chunk 0.
- Connect via `KICAD_API_SOCKET`/`KICAD_API_TOKEN`, operate on the open board, apply everything
  in **one commit** so a run is a single undo step (an improvement over today).
- Packaging: extend `hatch-kicad` (`[tool.hatch.build.targets.kicad-package]`) or use
  `kicad-python-packager` to emit the IPC layout. PCM metadata `kicad_version = "11.0"`.
  Keep the SWIG package as a separate PCM version entry for KiCad < 11.
- Adapt `test_gui.py`/`test_plugin_action.py`, and add an installation test like
  `test-plugin-install`.

### Chunk 8: Tools and downstream consumers

- `tools/pcb2layout.py`: switch to the s-expr reader (it only reads; must handle both `(at …)`
  and `(transform …)`), so it doesn't need a running KiCad. Port `tools/tests/test_pcb2layout.py`
  (15 `pcbnew.` references) along with it.
- `kle-ng-api` worker image (`keyboard-tools-admin`): KiCad 11 base image, `api-server` lifecycle
  per job (startup cost, memory; re-run `just profile-memray`), canary with
  `KBPLACER_BACKEND=ipc`.
- `examples/absolem-ergogen/run.sh`, `docker/Dockerfile`, `.justfile` default image, README
  install/usage, `tests/README.md`.

### Chunk 9: Cutover at the KiCad 11 release

- Tag the last SWIG release (supports 6–10). Keep a maintenance branch, bugfixes only.
- Delete `backend/swig.py`, the `KICAD_VERSION < (x)` branches (~40 sites), KiCad 6–10 from the
  CI matrix and `test-all`, and the `ensure_swig_iterator_next` hack. Set
  `requires KiCad >= 11`.
- Drop the `--backend` flag (keep the env var as a no-op for one release).

## Dependencies and schedule

```
0 spike ─┬─> 1 oracles ─> 2 IPC harness ─┬─> 5 IPC CLI ─> 6 templates ─> 8 downstream ─> 9 cutover
         │                               │        ^
         └─> 3 seam ─> 4 geometry ───────┴────────┘
         └─> (GUI decision) ────────────────────────> 7 IPC plugin ───────────────────────┘
```

- Chunks 1–2 and 3–4 can run in parallel.
- Critical path: 0 → 3 → 4 → 5. Collision/geometry is the largest single risk.
- Assumption: KiCad 11 ships on the usual annual cadence (early 2027), which leaves about one
  quarter. The critical path carries the two biggest refactors (chunk 3.6 `ChangeSet`, chunk 4
  geometry + connectivity), so this is tight. If time runs short, 7 (GUI) and 6 (`.kicad_pcb`
  presets **and** writing connection templates) are the cuts: the release can ship IPC CLI first,
  with JSON presets only.

## Risks

| Risk | Mitigation |
|---|---|
| kipy footprint transform bugs or API churn before 11.0 | Chunk 2 contract tests on nightly; pin `kicad-python`; file upstream issues early |
| No way to load footprints from arbitrary paths | Temporary lib-table entries; fallback: parse `.kicad_mod` and `create_items` |
| IPC latency makes routing slow | Snapshot + `ChangeSet` design, fixed ~10 requests per run; request-count guard test (chunk 5); benchmark gate in chunk 4/5 |
| Partial batch failure leaves a half-applied board | Per-item status check + `drop_commit` (W8); contract test |
| Stale item objects revert earlier edits (e.g. a flip) or leave pads behind | Updates built only from a re-read after `FlipItems`, never from the `flip_items`-refreshed object (W5); contract test; upstream issue against kipy `flip_items` |
| Connectivity/dangling logic reads stale state inside a commit | Local connectivity on `BoardModel` (chunk 4), shadow-tested against `CONNECTIVITY_DATA` |
| New back-side footprints can't be flipped inside the commit (verified, W11) | Create them already flipped from an auxiliary-server source; contract test |
| Level 3 mismatches caused by KiCad 11, not the backend | KiCad 10 GUI+IPC contract tests (level 2) are required as the same-version comparison |
| Python geometry diverges from KiCad's clearance semantics | A/B level 1 shadow tests; final `kicad-cli pcb drc` in e2e tests |
| GUI toolkit unavailable in plugin venv on Linux | Decide in chunk 0; CLI-first release is acceptable |
| Golden SVGs change when switching renderer | Separate reviewed regeneration commit; snapshots are the primary oracle afterwards |
| KiCad 11 nightly drops SWIG before the cutover | No problem: auto-detect picks IPC, and SWIG coverage stays on the 6–10 matrix |
