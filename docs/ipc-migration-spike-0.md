# IPC migration: chunk 0 feasibility spike report

Run 2026-10-29, chunk 0 of `docs/ipc-migration-plan.md`. Raw data and scripts are in
`tools/ipc_spike/`.

## Environment

| | |
|---|---|
| Image | `admwscki/kicad-kbplacer-primary:nightly-jammy`, rebuilt today, unchanged Dockerfile |
| KiCad | `10.99.0-unknown-2291d3f224` (PPA `kicad-dev-nightly`, built 2026-09-15) |
| SWIG `pcbnew` | **not shipped** in the nightly (no `pcbnew.py`/`_pcbnew.so` anywhere) |
| Test image | `docker/ipc-tests.Dockerfile` (FROM nightly + hatch + kicad-python) → local tag `kicad-kbplacer-ipc-tests:nightly-jammy`. Since removed: kicad-python is now baked into `.circleci/images/jammy/nightly.Dockerfile` at the same ref |
| kicad-python | built from source at `87b945a` (main, 2026-09-23, 0.9.0.dev0); PyPI tops out at 0.8.0 |
| SWIG reference | `admwscki/kicad-kbplacer-primary:10.0.6-noble`, kbplacer's own `set_rotation`/`set_side` |

**Version skew:** the PPA hasn't published a nightly since 2026-09-15, six weeks ago, even after
a fresh `apt-get update`. kipy main pins KiCad protos from 2026-09-23. Diffing the `.proto`
trees (`2291d3f224` vs `dcadf9baa3`) shows **additive changes only** (new messages, fields and
enums; nothing removed or renumbered). So kipy main works against this server, but every command
added after 2026-09-14 returns `no handler available`. Those are the library commands and
`PlaceFootprintFromLibrary`.

## Results

| # | Question | Result |
|---|---|---|
| 1 | Headless server start | `KiCad(headless=True, file_path=…)` ready in **0.2 s**, about 0.8 s per probe including load and teardown. Two servers in parallel work (separate sockets) |
| 2 | Read board snapshot | footprints/pads/nets/tracks OK. 2x2 example: 4 snapshot calls in 42 ms |
| 3 | Move footprint, pads follow | ✅ pads move by exactly the delta. Saved file correct. The `xfail` in `tests/test_ipc.py:159` (KiCad 9.0.2 / kipy 0.3.0) no longer reproduces |
| 4 | Rotate direction | ✅ `orientation = 90` gives pad positions **bit-identical** to SWIG `set_rotation(fp, 90)` on KiCad 10 |
| 5 | Flip to back | ⚠️ **semantics differ**, see below |
| 6 | `layer = BL_B_Cu` on an existing footprint | ⚠️ accepted silently: layer changes, pads are **not** mirrored. The result is an inconsistent footprint (matches the kipy docstring warning). Must never be used for flipping |
| 7 | Tracks, vias, nets | ✅ create/remove tracks and vias. Assigning `Net(name="NEW")` to a new track **creates the net** |
| 8 | Create new board | ✅ `create_document` + `save()` writes `.kicad_pcb`, `.kicad_pro`, `.kicad_prl` |
| 9 | Geometry queries | ✅ `get_pad_shapes_as_polygons` (polygon per pad and layer), `get_item_bounding_box`, `hit_test`, `get_design_rules`, `get_connected_items`. Still **no collide/clearance query**, as expected |
| 10 | Library footprints (`load_all_libraries`, `get_library_footprint(s)`, `place_footprint_from_library`) | ❌ not in this server build (`no handler available`). Untested |
| 11 | Footprint without libraries: copy an existing instance, clear `id`, `create_items` | ✅ new footprint with all pads |
| 12 | Footprint from an arbitrary `.pretty` path: wrap `.kicad_mod` text in a minimal `(kicad_pcb …)` file, open it in a **second server**, copy the instance over | ✅ works (3 pads). The lib nickname is lost (`:SW_Cherry_MX_PCB_1.00u`) and must be set |
| 13 | Second board in the same server (`open_document`) | ❌ "cannot open a document from project X because project Y is already open". One project per server |
| 14 | Template board → target board across two servers (footprints + tracks) | ✅ `create_items` accepts items read from the other server |
| 15 | `get_as_string` | ✅ 40 kB s-expr of the whole board in one call |
| 16 | Per-request latency | ⚠️ **~10 ms floor for every request**, even `ping` (median 10.07 ms, min 9.96 ms). Batched `create_items` of 200 tracks: 15 ms. Same 200 one per call: 10.2 ms each (2 s) |
| 17 | wxPython for an IPC plugin venv | Wheels exist for Windows and macOS (4.3.2). **None on PyPI for Linux** (`No matching distribution`) |

### Flip semantics (row 5)

Same footprint (SW1 of `examples/2x2`, at (0, −20.15 mm), 0°), pad positions in nm:

| Case | SWIG@10 kbplacer `set_side(BACK)` | IPC `flip_items(f)` (default `BFD_LEFT_RIGHT`) |
|---|---|---|
| orientation | 0° | **180°** |
| pad "" | (5 080 000, −20 150 000) | (**−**5 080 000, −20 150 000) |
| pad 1 | (−3 810 000, −17 610 000) | (3 810 000, −22 690 000) |
| pad 2 | (2 540 000, −15 070 000) | (−2 540 000, −25 230 000) |

kbplacer on KiCad ≥ 9 calls `Flip(pos, False)` and then rotates 180° (`board_modifier.py:153`).
The net effect is a **top-bottom mirror at 0°**. IPC's default is the plain left-right flip.
The IPC adapter's `set_side` must therefore use `BFD_TOP_BOTTOM`, or flip and then rotate 180°,
and a contract test must pin it down. This is exactly the silent difference the A/B snapshot
comparison is there to catch.

After flip + rotate to 90°, IPC is within **1 nm** of SWIG (pad 1 x `2 539 999` vs `2 540 000`).
That confirms the 1–2 nm snapshot tolerance in the plan.

Caveat: `probe_basic`/`probe_followup`/`swig_reference` key pads by number, which collapses the
switch's unnumbered NPTH holes into one `""` entry. The numbered pads are compared exactly.
`probe_batching.py` compares the full pad multiset. Chunk 2 contract tests must use the multiset.

### Batching and transactions (`probe_batching.py`)

| Probe | Result |
|---|---|
| Move + rotate all 8 footprints | 1 `UpdateItems` request; all applied, pads rigid |
| Mixed types | 1 `CreateItems` for footprint + 2 tracks + via; 1 `UpdateItems` for footprint + track; 1 `DeleteItems` |
| Bulk flip of 4 switches | 1 `FlipItems`. `BFD_TOP_BOTTOM` = kbplacer SWIG `set_side` exactly (0°); `BFD_LEFT_RIGHT` doesn't (180°) |
| Reads inside an open commit | flip **visible**; staged move and created track **not visible** until `push_commit` |
| `drop_commit` | rolls back moves, creates and flips |
| Stale object update after flip | whole item replaced → flip silently reverted |
| Update from the object `flip_items` refreshed in place | that object has back-side layers but **pre-flip pads**; the update moves the footprint, pads stay behind. A re-read after the flip works |
| W11: flip/update an item created in the same commit | both `ISC_NONEXISTENT`; item stays front-side, unmoved |
| W11: create an already-flipped copy (from a re-read), moved locally | ✅ correct pads on the back; from the `flip_items`-refreshed object ❌ pads mirrored at the old position |
| W11: create in commit 1, flip in commit 2 | ✅ correct, but two undo steps |
| One bad item in a batch | rest applied; per-item `ISC_NONEXISTENT` / `ISC_EXISTING`; kipy `create_items` returns 2 items anyway (statuses discarded) |
| Pad nets via footprint update | applied, missing nets created |
| Payload | 1k / 5k / 20k tracks in one create: 0.02 / 0.1 / 0.36 s |
| kbplacer-like run (snapshot, flip, re-read, update, create, commit, save) | **10 requests total**; flipped diodes' pads verified (the first version built updates from the `flip_items`-refreshed objects, 9 requests, and wasn't checked) |

There is no multi-command request: `ApiRequest` carries a single `Any`. "Bulk" therefore means
one list per command type inside one commit. The write model and its consequences are in
`docs/ipc-migration-plan.md`, section "IPC write model" (W1–W10).

### Other findings

- **File format changed in KiCad 11 nightly** (`(version 20260901)`): footprint placement is now
  written as `(transform (translate x y) (rotate a) (scale 1 1))` instead of `(at x y a)`. Any
  file-based reader needs to handle both: the chunk 1 snapshot parser, `tools/pcb2layout.py`, and
  any test that greps board files. Older files (`20240108`) still load fine.
- **Docker bind mounts:** the probes were run with `docker cp` because the daemon here can't see
  the dev container's filesystem. The README commands above use `-v` for normal hosts.

## Impact on the plan

| Plan item | Change |
|---|---|
| Gap: footprint from `.pretty` path | Has a working fallback: wrap `.kicad_mod` → board file → load in an auxiliary server → copy the instance. Library commands become an optimisation once a newer nightly is testable |
| Gap: second board (presets, `template_copier`) | Solved by an **auxiliary headless server**, not a second document. Startup is 0.2 s, so per-run cost is negligible. The s-expr reader is no longer needed for chunk 6 |
| Gap: footprint transforms | Move/rotate OK. Flip needs an explicit direction mapping (above). Remove the `xfail` in chunk 2 |
| IPC chattiness | Confirmed and quantified: **10 ms per request**. Snapshot-and-commit is mandatory, and `geometry.py` (chunk 4) must not call the server inside the routing loop. A router with ~1 000 queries per board would take 10 s per-call vs ~50 ms batched. Ask upstream whether the 10 ms floor is a server poll interval |
| Chunk 1 snapshot parser | Must parse both `(at …)` and `(transform …)` |
| Chunk 7 GUI | wx is a problem on Linux only. Decision still open; leaning towards wx on Windows/macOS and a documented system `python3-wxgtk4` / CLI fallback on Linux |
| Nightly CI image | PPA is stale. To test library commands we need a fresher KiCad build source (KiCad's official nightly docker image or a self-built image). Decide before chunk 2's CI job |

## Upstream items to raise

1. kicad-python: ~10 ms latency floor on every request in headless mode (repro: `ping` ×100).
2. kicad-python docs: `FootprintInstance.layer` setter silently produces an unmirrored footprint.
   Raise an error or document it more strongly.
3. KiCad: one project per `api-server`. Is opening a second document from another project
   planned? (Workaround works, low priority.)
4. kicad-python: `create_items`/`update_items` drop per-item `ItemStatus`. Return or raise them.
   `flip_items` refreshes the passed objects with pre-flip pad positions; updating one of them
   leaves the pads behind.
5. KiCad: commit staging is inconsistent. `FlipItems` is visible to reads inside an open commit,
   `UpdateItems`/`CreateItems` aren't.
6. Ubuntu `kicad-dev-nightly` PPA has had no builds since 2026-09-15.

## Not covered (needs a newer nightly or later chunks)

- Library commands / `place_footprint_from_library` (server too old).
- Plugin entrypoint (`plugin.json` action) and GUI-mode IPC: chunk 7.
- Performance on a large board (absolem): chunk 4/5 benchmark.
