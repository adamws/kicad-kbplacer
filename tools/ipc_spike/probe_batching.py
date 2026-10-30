"""Batching probes: how many requests does a kbplacer-like edit need, and what can be merged.

python3 probe_batching.py /repo /out   (inside kicad-kbplacer-primary:nightly-jammy)
"""

import json
import shutil
import sys
import time
import traceback
import uuid
from pathlib import Path

from kipy import KiCad
from kipy.board_types import BoardLayer, Net, Track, Via
from kipy.client import KiCadClient
from kipy.geometry import Angle, Vector2
from kipy.proto.board import board_commands_pb2
from kipy.proto.board.board_commands_pb2 import BoardFlipDirection
from kipy.proto.common.commands import editor_commands_pb2
from kipy.util import pack_any

REPO = Path(sys.argv[1])
OUT = Path(sys.argv[2])
R = {}
SWIG_BACK_SW1 = {  # tools/ipc_spike/swig_reference.kicad-10.0.6.json, case "back"
    "": (5080000, -20150000),
    "1": (-3810000, -17610000),
    "2": (2540000, -15070000),
}


class CountingClient(KiCadClient):
    count = 0

    def send(self, command, response_type):
        CountingClient.count += 1
        return super().send(command, response_type)


def fresh(name):
    d = OUT / name
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    shutil.copytree(
        REPO / "examples/examples.pretty", OUT / "examples.pretty", dirs_exist_ok=True
    )
    for f in ["keyboard-before.kicad_pcb", "fp-lib-table"]:
        shutil.copy(REPO / "examples/2x2" / f, d / f)
    return d / "keyboard-before.kicad_pcb"


def kicad(pcb):
    k = KiCad(headless=True, file_path=str(pcb), timeout_ms=20000)
    k._client.__class__ = CountingClient
    return k


def refs(board):
    return {f.reference_field.text.value: f for f in board.get_footprints()}


def pads(fp):
    return {p.number: (p.position.x, p.position.y) for p in fp.definition.pads}


def all_pads(fp):
    """Sorted multiset; `pads` collapses the unnumbered NPTH holes into one key"""
    return sorted((p.number, p.position.x, p.position.y) for p in fp.definition.pads)


def track(x0, y0, x1, y1, net="", layer=BoardLayer.BL_B_Cu):
    t = Track()
    t.start = Vector2.from_xy_mm(x0, y0)
    t.end = Vector2.from_xy_mm(x1, y1)
    t.width = 200_000
    t.layer = layer
    if net:
        t.net = Net(name=net)
    return t


def run(name, fn):
    t0 = time.time()
    try:
        R[name] = fn()
    except Exception as e:
        R[name] = {
            "error": f"{type(e).__name__}: {e}",
            "trace": traceback.format_exc()[-600:],
        }
    R[name]["seconds"] = round(time.time() - t0, 2)
    print(name, json.dumps(R[name], default=str), flush=True)


def bulk_update_move_and_rotate():
    """All footprints moved+rotated in ONE update_items; position+orientation together."""
    with kicad(fresh("b1")) as k:
        b = k.get_board()
        fps = refs(b)
        before = {r: pads(f) for r, f in fps.items()}
        for i, f in enumerate(fps.values()):
            f.position = Vector2.from_xy_mm(20 * i, 10)
            f.orientation = Angle.from_degrees(30 * i)
        n0 = CountingClient.count
        b.update_items(list(fps.values()))
        requests = CountingClient.count - n0
        after = refs(b)
        ok = all(
            (after[r].position.x, after[r].position.y)
            == (fps[r].position.x, fps[r].position.y)
            and abs(after[r].orientation.degrees - fps[r].orientation.degrees) < 1e-9
            for r in fps
        )

        # pads must be rigidly transformed: distances between pads preserved
        def dist(p):
            v = list(p.values())
            return sorted(
                round(((a[0] - c[0]) ** 2 + (a[1] - c[1]) ** 2) ** 0.5)
                for i, a in enumerate(v)
                for c in v[i + 1 :]
            )

        rigid = all(
            max(abs(x - y) for x, y in zip(dist(before[r]), dist(pads(after[r])))) <= 2
            for r in fps
            if len(before[r]) > 1
        )
        return {
            "items": len(fps),
            "requests": requests,
            "all_applied": ok,
            "pads_rigid": rigid,
        }


def mixed_types_single_requests():
    """create: footprint copy + tracks + via in one call; update: footprint + track together."""
    with kicad(fresh("b2")) as k:
        b = k.get_board()
        sw = refs(b)["SW1"]
        sw.proto.ClearField("id")
        sw.reference_field.text.value = "SW9"
        v = Via()
        v.position = Vector2.from_xy_mm(5, 5)
        v.net = Net(name="ROW0")
        n0 = CountingClient.count
        created = b.create_items(
            [sw, track(0, 0, 5, 5, "ROW0"), track(5, 5, 10, 5, "ROW0"), v]
        )
        create_req = CountingClient.count - n0
        fp = next(c for c in created if type(c).__name__ == "FootprintInstance")
        tr = next(c for c in created if type(c).__name__ == "Track")
        fp.position = Vector2.from_xy_mm(40, 40)
        tr.end = Vector2.from_xy_mm(7, 7)
        n0 = CountingClient.count
        updated = b.update_items([fp, tr])
        update_req = CountingClient.count - n0
        n0 = CountingClient.count
        b.remove_items(created)
        remove_req = CountingClient.count - n0
        return {
            "created_types": [type(c).__name__ for c in created],
            "create_requests": create_req,
            "updated_types": [type(u).__name__ for u in updated],
            "update_requests": update_req,
            "remove_requests": remove_req,
            "remaining_tracks": len(b.get_tracks()),
            "remaining_fps": len(b.get_footprints()),
        }


def bulk_flip_direction():
    """flip_items for several footprints in one request; which direction matches SWIG."""
    out = {}
    for name, direction in [
        ("left_right", BoardFlipDirection.BFD_LEFT_RIGHT),
        ("top_bottom", BoardFlipDirection.BFD_TOP_BOTTOM),
    ]:
        with kicad(fresh(f"b3_{name}")) as k:
            b = k.get_board()
            fps = refs(b)
            sws = [f for r, f in fps.items() if r.startswith("SW")]
            n0 = CountingClient.count
            res = b.flip_items(sws, direction)
            req = CountingClient.count - n0
            sw1 = refs(b)["SW1"]
            got = pads(sw1)
            out[name] = {
                "flipped": len(res),
                "requests": req,
                "orientation": sw1.orientation.degrees,
                "matches_kbplacer_swig_set_side": got == SWIG_BACK_SW1,
            }
    return out


def transaction_visibility_and_order():
    """Inside one commit: flip -> update -> create -> remove. Are staged changes readable?"""
    with kicad(fresh("b4")) as k:
        b = k.get_board()
        fps = refs(b)
        n0 = CountingClient.count
        commit = b.begin_commit()
        b.flip_items([fps["SW1"]], BoardFlipDirection.BFD_TOP_BOTTOM)
        mid_layer = BoardLayer.Name(refs(b)["SW1"].layer)  # read inside commit
        f = refs(b)["SW1"]
        f.position = Vector2.from_xy_mm(30, 30)
        b.update_items(f)
        mid_pos = refs(b)["SW1"].position.x
        created = b.create_items([track(30, 30, 35, 30, "COL0")])
        mid_tracks = len(b.get_tracks())
        b.remove_items(created)
        b.push_commit(commit, "kbplacer")
        req = CountingClient.count - n0
        final = refs(b)["SW1"]
        return {
            "requests_incl_reads": req,
            "inside_commit_sees_flip": mid_layer,
            "inside_commit_sees_move": mid_pos == 30_000_000,
            "inside_commit_sees_created_track": mid_tracks,
            "final_layer": BoardLayer.Name(final.layer),
            "final_x": final.position.x,
            "final_tracks": len(b.get_tracks()),
        }


def drop_commit_rolls_back():
    with kicad(fresh("b5")) as k:
        b = k.get_board()
        x0 = refs(b)["SW1"].position.x
        commit = b.begin_commit()
        f = refs(b)["SW1"]
        f.position = Vector2.from_xy_mm(50, 50)
        b.update_items(f)
        b.create_items([track(0, 0, 1, 1)])
        b.drop_commit(commit)
        return {
            "position_restored": refs(b)["SW1"].position.x == x0,
            "tracks": len(b.get_tracks()),
        }


def partial_failure():
    """One bad item inside a batch: does the rest apply? (raw responses, kipy hides status)"""
    with kicad(fresh("b6")) as k:
        b = k.get_board()
        fps = refs(b)
        good = fps["SW1"]
        good.position = Vector2.from_xy_mm(60, 60)
        bogus = fps["SW2"]
        bogus.proto.id.value = str(uuid.uuid4())  # nonexistent
        cmd = editor_commands_pb2.UpdateItems()
        cmd.header.document.CopyFrom(b.document)
        cmd.items.extend([pack_any(good.proto), pack_any(bogus.proto)])
        out = {}
        try:
            resp = k._client.send(cmd, editor_commands_pb2.UpdateItemsResponse)
            out["update_status"] = [
                editor_commands_pb2.ItemStatusCode.Name(r.status.code)
                for r in resp.updated_items
            ]
        except Exception as e:
            out["update_error"] = f"{type(e).__name__}: {e}"
        out["good_item_applied"] = refs(b)["SW1"].position.x == 60_000_000

        existing = b.get_tracks()
        t = track(0, 0, 2, 2)
        dup = track(0, 0, 3, 3)
        b.create_items(dup)
        dup_id = b.get_tracks()[0].id
        dup2 = track(0, 0, 4, 4)
        dup2.proto.id.CopyFrom(dup_id)
        cmd = editor_commands_pb2.CreateItems()
        cmd.header.document.CopyFrom(b.document)
        cmd.items.extend([pack_any(t.proto), pack_any(dup2.proto)])
        try:
            resp = k._client.send(cmd, editor_commands_pb2.CreateItemsResponse)
            out["create_status"] = [
                editor_commands_pb2.ItemStatusCode.Name(r.status.code)
                for r in resp.created_items
            ]
        except Exception as e:
            out["create_error"] = f"{type(e).__name__}: {e}"
        out["tracks_after"] = len(b.get_tracks()) - len(existing)
        try:
            out["kipy_create_items_with_dup"] = len(
                b.create_items([track(0, 0, 5, 5), dup2])
            )
        except Exception as e:
            out["kipy_create_items_with_dup_error"] = f"{type(e).__name__}: {e}"
        return out


def pad_nets_via_footprint_update():
    """board_builder assigns pad nets: set on footprint definition pads, one update."""
    with kicad(fresh("b7")) as k:
        b = k.get_board()
        fps = refs(b)
        changed = []
        for r in ["SW1", "SW2", "SW3", "SW4"]:
            f = fps[r]
            for p in f.definition.pads:
                if p.number == "1":
                    p.net = Net(name=f"NEW_{r}")
            changed.append(f)
        b.update_items(changed)
        after = refs(b)
        return {
            "pad_nets": {
                r: {p.number: p.net.name for p in after[r].definition.pads}
                for r in ["SW1", "SW4"]
            },
            "nets_created": sorted(
                n.name for n in b.get_nets() if n.name.startswith("NEW_")
            ),
        }


def large_payload():
    with kicad(fresh("b8")) as k:
        b = k.get_board()
        out = {}
        for n in [1000, 5000, 20000]:
            items = [track(0, i * 0.01, 1, i * 0.01) for i in range(n)]
            t0 = time.time()
            try:
                created = b.create_items(items)
                out[n] = {"created": len(created), "s": round(time.time() - t0, 2)}
            except Exception as e:
                out[n] = {"error": f"{type(e).__name__}: {e}"[:200]}
                break
            t0 = time.time()
            b.remove_items(created)
            out[n]["remove_s"] = round(time.time() - t0, 2)
        return out


def kbplacer_like_run():
    """Snapshot -> local compute -> flip + update + create in one commit -> save."""
    with kicad(fresh("b9")) as k:
        b = k.get_board()
        n0 = CountingClient.count
        fps = refs(b)
        b.get_tracks()
        b.get_nets()
        commit = b.begin_commit()
        diodes = [f for r, f in fps.items() if r.startswith("D")]
        b.flip_items(diodes, BoardFlipDirection.BFD_TOP_BOTTOM)
        # objects refreshed inside flip_items keep pre-flip pads (see
        # update_after_flip_source_object), re-read instead; flips are visible in commits
        fps = refs(b)
        diodes = [f for r, f in fps.items() if r.startswith("D")]
        flipped_pads = {f.reference_field.text.value: all_pads(f) for f in diodes}
        for f in diodes:
            f.position = f.position + Vector2.from_xy_mm(0, 5)
        for i, (r, f) in enumerate(
            sorted((r, f) for r, f in fps.items() if r.startswith("SW"))
        ):
            f.position = Vector2.from_xy_mm(19.05 * i, 0)
        b.update_items(list(fps.values()))
        b.create_items(
            [track(19.05 * i, 0, 19.05 * i + 5, 5, "ROW0") for i in range(4)]
        )
        b.push_commit(commit, "kbplacer")
        b.save()
        total = CountingClient.count - n0
        after = refs(b)
        return {
            "total_requests": total,
            "diodes_back": all(
                BoardLayer.Name(after[r].layer) == "BL_B_Cu" for r in flipped_pads
            ),
            "diode_pads_moved_with_footprint": all(
                all_pads(after[r]) == sorted((n, x, y + 5_000_000) for n, x, y in p)
                for r, p in flipped_pads.items()
            ),
        }


def flip_inside_dropped_commit():
    """flip_items is visible immediately inside a commit; does drop_commit undo it?"""
    with kicad(fresh("b10")) as k:
        b = k.get_board()
        original = all_pads(refs(b)["SW1"])
        commit = b.begin_commit()
        b.flip_items([refs(b)["SW1"]], BoardFlipDirection.BFD_TOP_BOTTOM)
        b.drop_commit(commit)
        sw1 = refs(b)["SW1"]
        return {
            "layer_after_drop": BoardLayer.Name(sw1.layer),
            "orientation_after_drop": sw1.orientation.degrees,
            "pads_after_drop_equal_original": all_pads(sw1) == original,
        }


def stale_update_after_flip():
    """update_items with a footprint object read BEFORE the flip: does it undo the flip?"""
    with kicad(fresh("b11")) as k:
        b = k.get_board()
        stale = refs(b)["SW1"]
        original = all_pads(stale)
        fresh_copy = refs(b)["SW1"]
        b.flip_items([fresh_copy], BoardFlipDirection.BFD_TOP_BOTTOM)
        stale_dx = stale.position.x - 10_000_000
        stale_dy = stale.position.y - 10_000_000
        stale.position = Vector2.from_xy_mm(10, 10)
        b.update_items(stale)
        sw1 = refs(b)["SW1"]
        return {
            "layer": BoardLayer.Name(sw1.layer),
            "position": (sw1.position.x, sw1.position.y),
            "pads_are_unflipped_original_moved": all_pads(sw1)
            == sorted((n, x - stale_dx, y - stale_dy) for n, x, y in original),
        }


def _raw_flip(k, b, ids, direction):
    """FlipItems with per-item status (kipy's flip_items silently skips failures)"""
    cmd = board_commands_pb2.FlipItems()
    cmd.header.document.CopyFrom(b.document)
    cmd.direction = direction
    cmd.items.extend(ids)
    try:
        resp = k._client.send(cmd, board_commands_pb2.FlipItemsResponse)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    return {
        "status": [
            editor_commands_pb2.ItemStatusCode.Name(r.status.code)
            for r in resp.flipped_items
        ]
    }


W11_DY = 40_000_000


def _flipped_sw1_shifted(b):
    """Reference pads: SW1 flipped BFD_TOP_BOTTOM (= SWIG `set_side`), moved by W11_DY"""
    b.flip_items([refs(b)["SW1"]], BoardFlipDirection.BFD_TOP_BOTTOM)
    return sorted((n, x, y + W11_DY) for n, x, y in all_pads(refs(b)["SW1"]))


def _sw9_result(b, requests=None):
    final = refs(b).get("SW9")
    out = {"requests": requests} if requests is not None else {}
    if final is None:
        return {**out, "sw9": None}
    return {
        **out,
        "layer": BoardLayer.Name(final.layer),
        "position_y": final.position.y,
        "pads_correct": all_pads(final) == _flipped_sw1_shifted(b),
    }


def _sw1_copy(fp, dy=0):
    fp.proto.ClearField("id")
    fp.reference_field.text.value = "SW9"
    fp.position = Vector2.from_xy(fp.position.x, fp.position.y + dy)
    return fp


def w11_flip_created_in_same_commit():
    """W11: can FlipItems/UpdateItems target an item created earlier in the same commit?"""
    with kicad(fresh("b12a")) as k:
        b = k.get_board()
        n0 = CountingClient.count
        commit = b.begin_commit()
        created = b.create_items([_sw1_copy(refs(b)["SW1"])])[0]
        flip = _raw_flip(k, b, [created.id], BoardFlipDirection.BFD_TOP_BOTTOM)
        created.position = Vector2.from_xy(
            created.position.x, created.position.y + W11_DY
        )
        cmd = editor_commands_pb2.UpdateItems()
        cmd.header.document.CopyFrom(b.document)
        cmd.items.extend([pack_any(created.proto)])
        resp = k._client.send(cmd, editor_commands_pb2.UpdateItemsResponse)
        b.push_commit(commit, "kbplacer")
        return {
            "flip": flip,
            "update_status": [
                editor_commands_pb2.ItemStatusCode.Name(r.status.code)
                for r in resp.updated_items
            ],
            **_sw9_result(b, CountingClient.count - n0),
        }


def w11_create_already_flipped():
    """W11 fallback: flip the source, read it back, copy+move locally, create on the back.
    `fresh_read` builds the copy from a re-read; `flip_refreshed` from the object
    kipy refreshed in place inside flip_items."""
    out = {}
    for variant in ["fresh_read", "flip_refreshed"]:
        with kicad(fresh(f"b12b_{variant}")) as k:
            b = k.get_board()
            # in kbplacer this flip would happen on the throwaway auxiliary server
            commit = b.begin_commit()
            src = refs(b)["SW1"]
            b.flip_items([src], BoardFlipDirection.BFD_TOP_BOTTOM)
            if variant == "fresh_read":
                src = refs(b)["SW1"]
            b.drop_commit(commit)
            n0 = CountingClient.count
            commit = b.begin_commit()
            b.create_items([_sw1_copy(src, W11_DY)])
            b.push_commit(commit, "kbplacer")
            out[variant] = _sw9_result(b, CountingClient.count - n0)
    return out


def w11_create_then_flip_two_commits():
    """W11 fallback: create front-side copy in commit 1, flip it in commit 2 (2 undo steps)"""
    with kicad(fresh("b12c")) as k:
        b = k.get_board()
        n0 = CountingClient.count
        commit = b.begin_commit()
        created = b.create_items([_sw1_copy(refs(b)["SW1"], W11_DY)])[0]
        b.push_commit(commit, "kbplacer: create")
        commit = b.begin_commit()
        flip = _raw_flip(k, b, [created.id], BoardFlipDirection.BFD_TOP_BOTTOM)
        b.push_commit(commit, "kbplacer: flip")
        return {"flip": flip, **_sw9_result(b, CountingClient.count - n0)}


def update_after_flip_source_object():
    """W5 follow-up: is the object kipy refreshes inside flip_items safe to update from?
    `flip_refreshed`: move that object. `reread`: re-read after the flip (visible inside
    the commit, W7), then move."""
    out = {}
    for variant in ["flip_refreshed", "reread"]:
        with kicad(fresh(f"b13_{variant}")) as k:
            b = k.get_board()
            commit = b.begin_commit()
            f = refs(b)["SW1"]
            b.flip_items([f], BoardFlipDirection.BFD_TOP_BOTTOM)
            refreshed_pads_mirrored = all_pads(f) == all_pads(refs(b)["SW1"])
            expected = sorted(
                (n, x, y + W11_DY) for n, x, y in all_pads(refs(b)["SW1"])
            )
            if variant == "reread":
                f = refs(b)["SW1"]
            f.position = Vector2.from_xy(f.position.x, f.position.y + W11_DY)
            b.update_items(f)
            b.push_commit(commit, "kbplacer")
            final = refs(b)["SW1"]
            out[variant] = {
                "refreshed_object_has_mirrored_pads": refreshed_pads_mirrored,
                "layer": BoardLayer.Name(final.layer),
                "position_y": final.position.y,
                "pads_correct": all_pads(final) == expected,
            }
    return out


for name, fn in list(globals().items()):
    if (
        callable(fn)
        and getattr(fn, "__module__", None) == "__main__"
        and name
        not in (
            "fresh",
            "kicad",
            "refs",
            "pads",
            "track",
            "run",
            "all_pads",
            "_raw_flip",
            "_flipped_sw1_shifted",
            "_sw9_result",
            "_sw1_copy",
            "CountingClient",
        )
    ):
        run(name, fn)
(OUT / "results_batching.json").write_text(json.dumps(R, indent=2, default=str))
