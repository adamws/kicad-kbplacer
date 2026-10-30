"""Chunk 0 feasibility probes: kbplacer needs vs. kipy on headless KiCad nightly.

Run inside admwscki/kicad-kbplacer-primary:nightly-jammy (see README.md):
  python3 probe_basic.py /repo /out
Each probe gets a fresh copy of the 2x2 example and its own api-server.
"""

import json
import shutil
import sys
import time
import traceback
from pathlib import Path

from kipy import KiCad
from kipy.board_types import BoardLayer, FootprintInstance, Net, Track, Via
from kipy.geometry import Angle, Vector2
from kipy.proto.common.types import DocumentType

REPO = Path(sys.argv[1])
OUT = Path(sys.argv[2])
EXAMPLE = REPO / "examples/2x2"
RESULTS = {}


def fresh_board(name: str) -> Path:
    d = OUT / name
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    # keep ${KIPRJMOD}/../examples.pretty resolvable
    shutil.copytree(
        REPO / "examples/examples.pretty", OUT / "examples.pretty", dirs_exist_ok=True
    )
    for f in ["keyboard-before.kicad_pcb", "fp-lib-table"]:
        shutil.copy(EXAMPLE / f, d / f)
    return d / "keyboard-before.kicad_pcb"


def probe(fn):
    name = fn.__name__
    t0 = time.time()
    try:
        RESULTS[name] = {"ok": True, **(fn() or {})}
    except Exception as e:
        RESULTS[name] = {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "trace": traceback.format_exc().splitlines()[-6:],
        }
    RESULTS[name]["seconds"] = round(time.time() - t0, 2)
    print(name, json.dumps(RESULTS[name], indent=1, default=str), flush=True)


def kicad(pcb: Path | None = None) -> KiCad:
    return KiCad(headless=True, file_path=str(pcb) if pcb else None, timeout_ms=20000)


def fp_by_ref(board, ref: str) -> FootprintInstance:
    for f in board.get_footprints():
        if f.reference_field.text.value == ref:
            return f
    raise KeyError(ref)


def pad_positions(board, ref: str) -> dict:
    f = fp_by_ref(board, ref)
    return {p.number: (p.position.x, p.position.y) for p in f.definition.pads}


def saved_text(pcb: Path, ref: str) -> str:
    """Return the footprint s-expr block for reference from saved file (crude)."""
    text = pcb.read_text()
    i = text.find(f'"Reference" "{ref}"')
    start = text.rfind("\n\t(footprint ", 0, i)
    return text[start : text.find("\n\t(footprint ", i)][:1500]


@probe
def p01_startup_version():
    t0 = time.time()
    with kicad() as k:
        startup = time.time() - t0
        v = k.get_version()
        return {
            "startup_s": round(startup, 2),
            "version": v.full_version,
            "api_version": str(k.get_api_version()),
            "check_version": k.check_version(),
        }


@probe
def p02_open_board_and_snapshot():
    pcb = fresh_board("p02")
    with kicad(pcb) as k:
        b = k.get_board()
        t0 = time.time()
        fps = b.get_footprints()
        tracks = b.get_tracks()
        pads = b.get_pads()
        nets = b.get_nets()
        dt = time.time() - t0
        return {
            "footprints": len(fps),
            "tracks": len(tracks),
            "pads": len(pads),
            "nets": [n.name for n in nets][:10],
            "snapshot_s": round(dt, 3),
            "refs": sorted(f.reference_field.text.value for f in fps),
        }


@probe
def p03_move_footprint_moves_pads():
    pcb = fresh_board("p03")
    with kicad(pcb) as k:
        b = k.get_board()
        before = pad_positions(b, "SW1")
        f = fp_by_ref(b, "SW1")
        origin = (f.position.x, f.position.y)
        dx, dy = 5_000_000, 3_000_000
        f.position = Vector2.from_xy(origin[0] + dx, origin[1] + dy)
        b.update_items(f)
        after = pad_positions(b, "SW1")
        delta = {
            n: (after[n][0] - before[n][0], after[n][1] - before[n][1]) for n in before
        }
        b.save()
    from_file = saved_text(pcb, "SW1")
    return {
        "origin": origin,
        "pad_deltas": delta,
        "pads_follow": all(d == (dx, dy) for d in delta.values()),
        "saved_has_new_at": f"(at {(origin[0] + dx) / 1e6:g} {(origin[1] + dy) / 1e6:g}"
        in from_file,
    }


@probe
def p04_rotate_direction():
    pcb = fresh_board("p04")
    with kicad(pcb) as k:
        b = k.get_board()
        f = fp_by_ref(b, "SW1")
        c = (f.position.x, f.position.y)
        before = pad_positions(b, "SW1")
        o0 = f.orientation.degrees
        f.orientation = Angle.from_degrees(o0 + 90)
        b.update_items(f)
        f2 = fp_by_ref(b, "SW1")
        after = pad_positions(b, "SW1")

        # KiCad: +angle is CCW on screen; y axis points down -> (x,y) -> (y,-x) relative
        def ccw(p):
            rx, ry = p[0] - c[0], p[1] - c[1]
            return (c[0] + ry, c[1] - rx)

        expected = {n: ccw(p) for n, p in before.items()}
        err = max(
            max(abs(after[n][0] - expected[n][0]), abs(after[n][1] - expected[n][1]))
            for n in before
        )
        return {
            "orientation_before": o0,
            "orientation_after": f2.orientation.degrees,
            "max_err_nm_vs_ccw_screen": err,
            "pads_before": before,
            "pads_after": after,
        }


@probe
def p05_flip_to_back():
    pcb = fresh_board("p05")
    with kicad(pcb) as k:
        b = k.get_board()
        f = fp_by_ref(b, "SW1")
        c = (f.position.x, f.position.y)
        before = pad_positions(b, "SW1")
        res = b.flip_items(f)
        f2 = fp_by_ref(b, "SW1")
        after = pad_positions(b, "SW1")
        pads = [p for p in f2.definition.pads]
        mirrored_x = all(
            after[n] == (2 * c[0] - before[n][0], before[n][1]) for n in before
        )
        return {
            "flipped": len(res),
            "layer": BoardLayer.Name(f2.layer),
            "position_kept": (f2.position.x, f2.position.y) == c,
            "orientation": f2.orientation.degrees,
            "mirrored_left_right": mirrored_x,
            "pad_layers": sorted(
                {BoardLayer.Name(lyr) for p in pads for lyr in p.padstack.layers}
            ),
        }


@probe
def p06_layer_setter_on_existing_footprint():
    """docs say: don't use layer setter to flip; check what happens"""
    pcb = fresh_board("p06")
    with kicad(pcb) as k:
        b = k.get_board()
        f = fp_by_ref(b, "SW1")
        before = pad_positions(b, "SW1")
        f.layer = BoardLayer.BL_B_Cu
        b.update_items(f)
        f2 = fp_by_ref(b, "SW1")
        return {
            "layer": BoardLayer.Name(f2.layer),
            "pads_changed": pad_positions(b, "SW1") != before,
        }


@probe
def p07_tracks_vias_nets():
    pcb = fresh_board("p07")
    with kicad(pcb) as k:
        b = k.get_board()
        existing = {n.name for n in b.get_nets()}
        t = Track()
        t.start = Vector2.from_xy_mm(10, 10)
        t.end = Vector2.from_xy_mm(20, 10)
        t.width = 250_000
        t.layer = BoardLayer.BL_B_Cu
        some_net = sorted(n for n in existing if n)[0]
        t.net = Net(name=some_net)
        t2 = Track()
        t2.start = Vector2.from_xy_mm(10, 20)
        t2.end = Vector2.from_xy_mm(20, 20)
        t2.width = 250_000
        t2.layer = BoardLayer.BL_F_Cu
        t2.net = Net(name="KBPLACER_NEW_NET")
        v = Via()
        v.position = Vector2.from_xy_mm(20, 10)
        v.net = Net(name=some_net)
        created = b.create_items([t, t2, v])
        nets_after = {n.name for n in b.get_nets()}
        b.save()
        tracks = b.get_tracks()
        out = {
            "created": [repr(c) for c in created],
            "new_net_created": "KBPLACER_NEW_NET" in nets_after,
            "track_nets": [tr.net.name for tr in tracks],
        }
        b.remove_items(created)
        out["tracks_after_remove"] = len(b.get_tracks())
        return out


@probe
def p08_batching_cost():
    pcb = fresh_board("p08")
    with kicad(pcb) as k:
        b = k.get_board()

        def mk(i):
            t = Track()
            t.start = Vector2.from_xy_mm(0, i * 0.5)
            t.end = Vector2.from_xy_mm(5, i * 0.5)
            t.width = 200_000
            t.layer = BoardLayer.BL_B_Cu
            return t

        n = 200
        t0 = time.time()
        b.create_items([mk(i) for i in range(n)])
        batch = time.time() - t0
        t0 = time.time()
        commit = b.begin_commit()
        for i in range(n):
            b.create_items(mk(i + n))
        b.push_commit(commit, "kbplacer")
        single = time.time() - t0
        t0 = time.time()
        for _ in range(50):
            b.get_footprints()
        read = (time.time() - t0) / 50
        t0 = time.time()
        for _ in range(50):
            b.get_tracks()
        read_tracks = (time.time() - t0) / 50
        return {
            "n": n,
            "batch_create_s": round(batch, 3),
            "per_item_create_ms": round(single / n * 1000, 2),
            "get_footprints_ms": round(read * 1000, 2),
            "get_tracks_ms_with_400": round(read_tracks * 1000, 2),
        }


@probe
def p09_geometry_queries():
    pcb = fresh_board("p09")
    with kicad(pcb) as k:
        b = k.get_board()
        f = fp_by_ref(b, "SW1")
        pads = list(f.definition.pads)
        polys = b.get_pad_shapes_as_polygons(pads, BoardLayer.BL_B_Cu)
        bbox = b.get_item_bounding_box(f)
        hit = b.hit_test(pads[0], pads[0].position)
        rules = b.get_design_rules()
        conn = b.get_connected_items(pads[0])
        nc = b.get_netclass_for_nets([pads[0].net]) if pads[0].net.name else {}
        return {
            "pad_polys": [None if p is None else len(p.outline) for p in polys],
            "bbox": str(bbox),
            "hit_test_pad_center": hit,
            "rules_type": type(rules).__name__,
            "connected_items": len(conn),
            "netclass": {k_: v.name for k_, v in nc.items()},
        }


@probe
def p10_create_new_board():
    d = OUT / "p10"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir()
    path = d / "new.kicad_pcb"
    with kicad() as k:
        doc = k.create_document(str(path), DocumentType.DOCTYPE_PCB)
        b = k.get_board()
        b.save()
    return {
        "doc": str(doc).strip(),
        "exists": path.exists(),
        "files": sorted(p.name for p in d.iterdir()),
    }


@probe
def p11_libraries_and_place_footprint():
    pcb = fresh_board("p11")
    out = {}
    with kicad(pcb) as k:
        b = k.get_board()
        for name, fn in [
            ("load_all_libraries", lambda: k.load_all_libraries()),
            ("wait_for_libraries", lambda: k.wait_for_libraries()),
            (
                "get_library_footprints_examples",
                lambda: len(k.get_library_footprints(["examples"])),
            ),
            (
                "get_library_footprint",
                lambda: len(
                    k.get_library_footprint(
                        "examples:SW_Cherry_MX_PCB_1.00u", b.document
                    ).pads
                ),
            ),
            (
                "place_footprint_from_library",
                lambda: repr(
                    b.place_footprint_from_library(
                        "examples:SW_Cherry_MX_PCB_1.00u", Vector2.from_xy_mm(50, 50)
                    )
                ),
            ),
        ]:
            try:
                out[name] = {"ok": True, "value": fn()}
            except Exception as e:
                out[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return out


@probe
def p12_footprint_from_definition_copy():
    """Fallback for library loading: copy an existing footprint and create it as new item"""
    pcb = fresh_board("p12")
    with kicad(pcb) as k:
        b = k.get_board()
        f = fp_by_ref(b, "SW1")
        f.proto.ClearField("id")
        f.reference_field.text.value = "SW99"
        f.position = Vector2.from_xy_mm(80, 80)
        created = b.create_items(f)
        refs = sorted(x.reference_field.text.value for x in b.get_footprints())
        return {
            "created": [repr(c) for c in created],
            "refs": refs,
            "pads_of_new": len(pad_positions(b, "SW99")) if "SW99" in refs else None,
        }


@probe
def p13_second_document_headless():
    pcb = fresh_board("p13")
    other = REPO / "examples/2x3-rotations/keyboard-before.kicad_pcb"
    with kicad(pcb) as k:
        out = {}
        try:
            doc = k.open_document(str(other), DocumentType.DOCTYPE_PCB)
            out["open_second"] = str(doc).strip()
        except Exception as e:
            out["open_second_error"] = f"{type(e).__name__}: {e}"
        out["open_docs"] = [
            str(d).strip() for d in k.get_open_documents(DocumentType.DOCTYPE_PCB)
        ]
        out["board_name"] = k.get_board().name
        return out


@probe
def p14_get_as_string():
    pcb = fresh_board("p14")
    with kicad(pcb) as k:
        s = k.get_board().get_as_string()
        return {"len": len(s), "head": s[:80]}


OUT.mkdir(parents=True, exist_ok=True)
(OUT / "results.json").write_text(json.dumps(RESULTS, indent=2, default=str))
