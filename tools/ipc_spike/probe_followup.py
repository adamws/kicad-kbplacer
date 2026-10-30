"""Chunk 0 follow-ups: IPC side of SWIG comparison, second server transfer, latency."""

import json
import shutil
import statistics
import sys
import time
from pathlib import Path

from kipy import KiCad
from kipy.board_types import BoardLayer
from kipy.geometry import Angle, Vector2
from kipy.proto.common.types import DocumentType

REPO = Path(sys.argv[1])
OUT = Path(sys.argv[2])
R = {}


def fresh(name, src=REPO / "examples/2x2/keyboard-before.kicad_pcb"):
    d = OUT / name
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    shutil.copytree(
        REPO / "examples/examples.pretty", OUT / "examples.pretty", dirs_exist_ok=True
    )
    shutil.copy(REPO / "examples/2x2/fp-lib-table", d)
    shutil.copy(src, d / src.name)
    return d / src.name


def kicad(pcb=None):
    return KiCad(headless=True, file_path=str(pcb) if pcb else None, timeout_ms=20000)


def fp(board, ref):
    return next(
        f for f in board.get_footprints() if f.reference_field.text.value == ref
    )


def pads(board, ref):
    return {
        p.number: (p.position.x, p.position.y) for p in fp(board, ref).definition.pads
    }


def run(name, f):
    try:
        R[name] = f()
    except Exception as e:
        import traceback

        R[name] = {
            "error": f"{type(e).__name__}: {e}",
            "trace": traceback.format_exc()[-800:],
        }
    print(name, json.dumps(R[name], default=str), flush=True)


def transforms():
    out = {}
    for case in ["rotate90", "back", "back_then_rotate90"]:
        pcb = fresh(f"t_{case}")
        with kicad(pcb) as k:
            b = k.get_board()
            f = fp(b, "SW1")
            if case in ("back", "back_then_rotate90"):
                b.flip_items(f)
                f = fp(b, "SW1")
            if case in ("rotate90", "back_then_rotate90"):
                # kbplacer semantics: set absolute orientation to 90
                f.orientation = Angle.from_degrees(90)
                b.update_items(f)
                f = fp(b, "SW1")
            out[case] = {
                "orientation": f.orientation.degrees,
                "flipped": f.layer == BoardLayer.BL_B_Cu,
                "position": (f.position.x, f.position.y),
                "pads": pads(b, "SW1"),
            }
    return out


def latency():
    pcb = fresh("lat")
    with kicad(pcb) as k:
        b = k.get_board()

        def t(fn, n=100):
            xs = []
            for _ in range(n):
                t0 = time.perf_counter()
                fn()
                xs.append((time.perf_counter() - t0) * 1000)
            return {
                "median_ms": round(statistics.median(xs), 2),
                "min_ms": round(min(xs), 2),
            }

        return {
            "ping": t(k.ping),
            "get_version": t(k.get_version),
            "get_footprints": t(b.get_footprints),
            "get_nets": t(b.get_nets),
        }


def second_server_transfer():
    """Template board in server B; copy its footprints + a track into board in server A."""
    target = fresh("xfer_target")
    tmpl = fresh(
        "xfer_tmpl",
        REPO
        / "examples/2x3-rotations-custom-diode-with-track/keyboard-before.kicad_pcb",
    )
    out = {}
    with kicad(target) as a, kicad(tmpl) as b:
        ba, bb = a.get_board(), b.get_board()
        out["servers"] = [ba.name, bb.name]
        src_fps = list(bb.get_footprints())
        src_tracks = list(bb.get_tracks())
        out["template_fps"] = len(src_fps)
        out["template_tracks"] = len(src_tracks)
        sw = next(f for f in src_fps if f.reference_field.text.value.startswith("SW"))
        sw.proto.ClearField("id")
        sw.reference_field.text.value = "SW_FROM_TMPL"
        sw.position = Vector2.from_xy_mm(100, 100)
        created = ba.create_items([sw] + [t for t in src_tracks[:3]])
        out["created"] = [type(c).__name__ for c in created]
        out["pads_of_copy"] = len(pads(ba, "SW_FROM_TMPL"))
    return out


def kicad_mod_via_wrapper_board():
    """Load a footprint from a .pretty path: wrap .kicad_mod text into a minimal board file."""
    d = OUT / "modwrap"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    mod = (
        REPO / "tests/data/footprints/tests.pretty/SW_Cherry_MX_PCB_1.00u.kicad_mod"
    ).read_text()
    body = mod.strip()
    # footprint "NAME" -> footprint "lib:NAME"
    body = body.replace('(footprint "', '(footprint "tests:', 1)
    wrapper = d / "wrap.kicad_pcb"
    wrapper.write_text(
        f'(kicad_pcb (version 20240108) (generator "kbplacer")\n{body}\n)\n'
    )
    target = fresh("modwrap_target")
    with kicad(wrapper) as w, kicad(target) as t:
        fps = w.get_board().get_footprints()
        f = fps[0]
        f.proto.ClearField("id")
        f.reference_field.text.value = "SW_FROM_MOD"
        f.position = Vector2.from_xy_mm(60, 60)
        tb = t.get_board()
        tb.create_items(f)
        tb.save()
        return {
            "loaded": len(fps),
            "lib_id": str(f.definition.id).strip()[:120],
            "pads": len(pads(tb, "SW_FROM_MOD")),
        }


def open_second_doc_other_name():
    pcb = fresh("multi")
    other = fresh(
        "multi_other", REPO / "examples/2x3-rotations/keyboard-before.kicad_pcb"
    )
    renamed = other.with_name("template.kicad_pcb")
    other.rename(renamed)
    with kicad(pcb) as k:
        out = {}
        try:
            doc = k.open_document(str(renamed), DocumentType.DOCTYPE_PCB)
            out["opened"] = str(doc).replace("\n", " ")
        except Exception as e:
            out["error"] = f"{type(e).__name__}: {e}"
        out["open_docs"] = [
            str(d).replace("\n", " ")
            for d in k.get_open_documents(DocumentType.DOCTYPE_PCB)
        ]
        return out


run("transforms", transforms)
run("latency", latency)
run("second_server_transfer", second_server_transfer)
run("kicad_mod_via_wrapper_board", kicad_mod_via_wrapper_board)
run("open_second_doc_other_name", open_second_doc_other_name)
(OUT / "results2.json").write_text(json.dumps(R, indent=2, default=str))
