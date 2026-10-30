# SPDX-FileCopyrightText: 2026 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Backend-neutral snapshot of a saved `.kicad_pcb`, used as a test oracle.

Parses the board file directly (no `pcbnew`, no running KiCad), so the same assertion
can judge a board produced through SWIG or through the IPC API. Handles KiCad 6-9 files
(numbered nets), KiCad 10 (nets by name) and KiCad 11 (footprint `(transform ...)`
instead of `(at ...)`).

The snapshot contains what kbplacer changes: footprints (position, orientation, side and
absolute pad positions with nets), tracks, vias and the Edge.Cuts outline. UUIDs,
graphics inside footprints and everything else are ignored. Coordinates are integer
nanometers.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import sexpdata

Snapshot = Dict[str, Any]

# allowed difference between two snapshots, in nm and degrees
POSITION_TOLERANCE = 2
ANGLE_TOLERANCE = 1e-3


def _sym(item) -> Optional[str]:
    if isinstance(item, list) and item and isinstance(item[0], sexpdata.Symbol):
        return item[0].value()
    return None


def _children(node, name: str) -> List[list]:
    return [c for c in node[1:] if _sym(c) == name]


def _child(node, name: str) -> Optional[list]:
    found = _children(node, name)
    return found[0] if found else None


def _atom(value) -> Union[str, float]:
    if isinstance(value, sexpdata.Symbol):
        return value.value()
    return value


def _nm(value) -> int:
    return round(float(value) * 1_000_000)


def _xy(node) -> List[int]:
    return [_nm(node[1]), _nm(node[2])]


def _normalize_angle(angle: float) -> float:
    angle = round(angle % 360, 6)
    return 0.0 if angle in (0.0, 360.0) else angle


class _Nets:
    """KiCad <= 9 stores `(net <code>)` on items and a top-level code -> name table,
    KiCad >= 10 stores `(net "<name>")`; pads in both have the name available"""

    def __init__(self, board: list) -> None:
        self.names = {}
        for net in _children(board, "net"):
            if len(net) >= 3:  # noqa: PLR2004
                self.names[int(net[1])] = str(net[2])

    def name(self, node) -> str:
        net = _child(node, "net")
        if net is None:
            return ""
        if len(net) >= 3:  # noqa: PLR2004 - (net <code> "<name>") on pads
            return str(net[2])
        value = net[1]
        if isinstance(value, str):
            return value
        return self.names.get(int(value), "")


def _layer(node) -> str:
    layer = _child(node, "layer")
    return str(_atom(layer[1])) if layer else ""


def _placement(footprint: list):
    """Position and orientation, `(at x y a)` (KiCad <= 10) or `(transform ...)` (11)"""
    transform = _child(footprint, "transform")
    if transform is not None:
        translate = _child(transform, "translate")
        rotate = _child(transform, "rotate")
        position = _xy(translate) if translate else [0, 0]
        angle = float(rotate[1]) if rotate else 0.0
        return position, angle
    at = _child(footprint, "at")
    angle = float(at[3]) if len(at) > 3 else 0.0  # noqa: PLR2004
    return _xy(at), angle


def _reference(footprint: list) -> str:
    for prop in _children(footprint, "property"):  # KiCad >= 8
        if str(prop[1]) == "Reference":
            return str(prop[2])
    for text in _children(footprint, "fp_text"):  # KiCad 6, 7
        if _atom(text[1]) == "reference":
            return str(text[2])
    return ""


def _to_board(local: List[int], position: List[int], angle: float) -> List[int]:
    # KiCad: Y axis points down, positive angle is counter-clockwise on screen
    a = math.radians(angle)
    x, y = local
    return [
        round(position[0] + x * math.cos(a) + y * math.sin(a)),
        round(position[1] - x * math.sin(a) + y * math.cos(a)),
    ]


def _footprint(node: list, nets: _Nets) -> Dict[str, Any]:
    position, angle = _placement(node)
    pads = []
    for pad in _children(node, "pad"):
        local = _xy(_child(pad, "at"))
        pads.append([str(pad[1]), *_to_board(local, position, angle), nets.name(pad)])
    return {
        "reference": _reference(node),
        "lib_id": str(node[1]),
        "side": "BACK" if _layer(node) == "B.Cu" else "FRONT",
        "position": position,
        "orientation": _normalize_angle(angle),
        "pads": sorted(pads),
    }


def _ordered(*points: List[int]) -> List[List[int]]:
    """Direction of a segment does not matter, always start with the smaller endpoint"""
    return sorted(points)


def _stroke_width(node: list) -> int:
    stroke = _child(node, "stroke")  # KiCad >= 7
    width = _child(stroke, "width") if stroke else _child(node, "width")
    return _nm(width[1]) if width else 0


def _outline_item(node: list) -> Optional[list]:
    """[kind, stroke width, *points]"""
    kind = _sym(node)
    width = _stroke_width(node)
    if kind in ("gr_line", "gr_rect"):
        start, end = _xy(_child(node, "start")), _xy(_child(node, "end"))
        return [kind, width, *_ordered(start, end)]
    if kind == "gr_arc":
        start, mid, end = (_xy(_child(node, k)) for k in ("start", "mid", "end"))
        first, last = _ordered(start, end)
        return [kind, width, first, mid, last]
    if kind == "gr_circle":
        return [kind, width, _xy(_child(node, "center")), _xy(_child(node, "end"))]
    if kind == "gr_poly":
        points = [_xy(p) for p in _children(_child(node, "pts"), "xy")]
        return [kind, width, *points]
    return None


def snapshot_board(path: Union[str, Path]) -> Snapshot:
    with open(path, "r", encoding="utf-8") as f:
        board = sexpdata.loads(f.read())
    nets = _Nets(board)

    footprints, tracks, arcs, vias, outline = [], [], [], [], []
    for node in board[1:]:
        kind = _sym(node)
        if kind == "footprint":
            footprints.append(_footprint(node, nets))
        elif kind == "segment":
            start, end = _xy(_child(node, "start")), _xy(_child(node, "end"))
            width = _nm(_child(node, "width")[1])
            tracks.append([_layer(node), width, nets.name(node), *_ordered(start, end)])
        elif kind == "arc":
            start, mid, end = (_xy(_child(node, k)) for k in ("start", "mid", "end"))
            width = _nm(_child(node, "width")[1])
            first, last = _ordered(start, end)
            arcs.append([_layer(node), width, nets.name(node), first, mid, last])
        elif kind == "via":
            layers = [str(_atom(v)) for v in _child(node, "layers")[1:]]
            drill = _child(node, "drill")
            vias.append(
                [
                    *_xy(_child(node, "at")),
                    _nm(_child(node, "size")[1]),
                    _nm(drill[1]) if drill else 0,
                    layers,
                    nets.name(node),
                ]
            )
        elif kind and kind.startswith("gr_") and _layer(node) == "Edge.Cuts":
            item = _outline_item(node)
            if item:
                outline.append(item)

    footprints.sort(key=lambda f: (f["reference"], f["position"]))
    return {
        "footprints": footprints,
        "tracks": sorted(tracks),
        "arcs": sorted(arcs),
        "vias": sorted(vias),
        "outline": sorted(outline),
    }


def save_snapshot(snapshot: Snapshot, path: Union[str, Path]) -> None:
    """One item per line, so reference updates produce readable diffs"""
    lines = ["{"]
    sections = list(snapshot.items())
    for i, (name, items) in enumerate(sections):
        lines.append(f'  "{name}": [')
        for j, item in enumerate(items):
            comma = "," if j < len(items) - 1 else ""
            lines.append(f"    {json.dumps(item, separators=(',', ':'))}{comma}")
        lines.append("  ]" + ("," if i < len(sections) - 1 else ""))
    lines.append("}")
    Path(path).write_text("\n".join(lines) + "\n")


def load_snapshot(path: Union[str, Path]) -> Snapshot:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _close(expected, actual, path: str) -> bool:
    if isinstance(expected, list) and isinstance(actual, list):
        return len(expected) == len(actual) and all(
            _close(e, a, path) for e, a in zip(expected, actual)
        )
    if isinstance(expected, dict) and isinstance(actual, dict):
        return expected.keys() == actual.keys() and all(
            _close(expected[k], actual[k], f"{path}.{k}") for k in expected
        )
    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected == actual
    if isinstance(expected, int) and isinstance(actual, int):
        return abs(expected - actual) <= POSITION_TOLERANCE
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if path.endswith("orientation"):
            diff = abs(expected - actual) % 360
            return min(diff, 360 - diff) <= ANGLE_TOLERANCE
        return abs(expected - actual) <= ANGLE_TOLERANCE
    return expected == actual


def _match_unordered(name: str, expected: list, actual: list) -> List[str]:
    """Greedy matching within tolerance; sorting alone may reorder items off by 1 nm"""
    remaining = list(actual)
    missing = []
    for item in expected:
        for i, candidate in enumerate(remaining):
            if _close(item, candidate, name):
                del remaining[i]
                break
        else:
            missing.append(item)
    return [f"{name}: missing {json.dumps(m)}" for m in missing] + [
        f"{name}: unexpected {json.dumps(u)}" for u in remaining
    ]


def compare_snapshots(
    expected: Snapshot, actual: Snapshot, ignore: Sequence[str] = ()
) -> List[str]:
    """Returns human readable differences, empty when snapshots match within tolerance.
    `ignore` lists top-level sections to skip"""
    differences = []
    for name in sorted(set(expected) | set(actual)):
        if name == "footprints" or name in ignore:
            continue
        differences += _match_unordered(
            name, expected.get(name, []), actual.get(name, [])
        )

    def by_reference(snapshot):
        result: Dict[str, list] = {}
        for f in snapshot.get("footprints", []):
            result.setdefault(f["reference"], []).append(f)
        return result

    if "footprints" in ignore:
        return differences
    expected_fps, actual_fps = by_reference(expected), by_reference(actual)
    for ref in sorted(set(expected_fps) | set(actual_fps)):
        e, a = expected_fps.get(ref, []), actual_fps.get(ref, [])
        if len(e) != len(a):
            differences.append(f"footprint {ref}: expected {len(e)}, got {len(a)}")
            continue
        for ef, af in zip(e, a):
            for key in ef:
                if key == "pads":
                    differences += _match_unordered(
                        f"footprint {ref} pads", ef["pads"], af.get("pads", [])
                    )
                elif not _close(ef[key], af.get(key), key):
                    differences.append(
                        f"footprint {ref} {key}: expected {ef[key]}, got {af.get(key)}"
                    )
    return differences
