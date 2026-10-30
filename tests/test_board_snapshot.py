# SPDX-FileCopyrightText: 2026 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The board snapshot parser is the oracle for IPC results, check it against pcbnew"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from .board_snapshot import compare_snapshots, snapshot_board
from .conftest import KICAD_VERSION, pcbnew

DATA = Path(__file__).parent / "data/board-snapshot"
EXAMPLES = Path(__file__).parents[1] / "examples"

# KiCad 6 format, loadable by every supported version
OLD_FORMAT_BOARDS = sorted(EXAMPLES.glob("*/keyboard-after.kicad_pcb"))
KICAD10_BOARDS = sorted(DATA.glob("kicad10-*.kicad_pcb"))


def _nm_xy(point) -> list:
    return [point.x, point.y]


def swig_snapshot(path: Path) -> dict:
    """Same structure as `snapshot_board`, built from pcbnew instead of the file"""
    board = pcbnew.LoadBoard(str(path))
    footprints = []
    for f in board.GetFootprints():
        pads = [
            [p.GetNumber(), *_nm_xy(p.GetPosition()), p.GetNetname()] for p in f.Pads()
        ]
        footprints.append(
            {
                "reference": f.GetReference(),
                "lib_id": f.GetFPIDAsString(),
                "side": "BACK" if f.IsFlipped() else "FRONT",
                "position": _nm_xy(f.GetPosition()),
                "orientation": f.GetOrientationDegrees() % 360,
                "pads": sorted(pads),
            }
        )
    tracks, arcs, vias = [], [], []
    for t in board.GetTracks():
        net = t.GetNetname()
        if t.GetClass() == "PCB_VIA":
            via = t.Cast()
            try:
                size = via.GetWidth(pcbnew.F_Cu)
            except TypeError:  # KiCad < 9, no padstacks
                size = via.GetWidth()
            layers = [
                board.GetLayerName(via.TopLayer()),
                board.GetLayerName(via.BottomLayer()),
            ]
            vias.append(
                [*_nm_xy(via.GetPosition()), size, via.GetDrillValue(), layers, net]
            )
            continue
        layer = board.GetLayerName(t.GetLayer())
        ends = sorted([_nm_xy(t.GetStart()), _nm_xy(t.GetEnd())])
        if t.GetClass() == "PCB_ARC":
            arc = t.Cast()
            arcs.append(
                [layer, t.GetWidth(), net, ends[0], _nm_xy(arc.GetMid()), ends[1]]
            )
        else:
            tracks.append([layer, t.GetWidth(), net, *ends])
    outline = []
    for d in board.GetDrawings():
        if d.GetLayer() == pcbnew.Edge_Cuts and d.GetShape() == pcbnew.SHAPE_T_SEGMENT:
            ends = sorted([_nm_xy(d.GetStart()), _nm_xy(d.GetEnd())])
            outline.append(["gr_line", d.GetWidth(), *ends])
    return {
        "footprints": footprints,
        "tracks": tracks,
        "arcs": arcs,
        "vias": vias,
        "outline": outline,
    }


def _ids(paths):
    return [f"{p.parent.name}/{p.name}" for p in paths]


def _ignore_nets_assigned_on_load(swig: dict, parsed: dict) -> None:
    """pcbnew propagates nets to tracks stored with `(net 0)` when loading a board,
    the snapshot reports what the file stores. Some old example boards have such
    tracks."""
    netless = {tuple(map(str, t[:2] + t[3:])) for t in parsed["tracks"] if not t[2]}
    for t in swig["tracks"]:
        if tuple(map(str, t[:2] + t[3:])) in netless:
            t[2] = ""


@pytest.mark.skipif(pcbnew is None, reason="needs SWIG pcbnew")
@pytest.mark.parametrize("path", OLD_FORMAT_BOARDS, ids=_ids(OLD_FORMAT_BOARDS))
def test_snapshot_matches_pcbnew_old_format(path) -> None:
    swig, parsed = swig_snapshot(path), snapshot_board(path)
    _ignore_nets_assigned_on_load(swig, parsed)
    assert compare_snapshots(swig, parsed) == []


@pytest.mark.skipif(KICAD_VERSION < (10, 0, 0), reason="KiCad 10 file format")
@pytest.mark.parametrize("path", KICAD10_BOARDS, ids=_ids(KICAD10_BOARDS))
def test_snapshot_matches_pcbnew_kicad10_format(path) -> None:
    assert compare_snapshots(swig_snapshot(path), snapshot_board(path)) == []


@pytest.mark.parametrize("path", KICAD10_BOARDS, ids=_ids(KICAD10_BOARDS))
def test_kicad11_transform_format_matches_kicad10(path) -> None:
    # kicad11-* fixtures are the kicad10-* boards re-saved by KiCad 11 nightly
    kicad11 = path.with_name(path.name.replace("kicad10-", "kicad11-"))
    assert "(transform" in kicad11.read_text()
    assert compare_snapshots(snapshot_board(path), snapshot_board(kicad11)) == []


def test_snapshot_content() -> None:
    snapshot = snapshot_board(DATA / "kicad10-rotations-vias.kicad_pcb")
    assert len(snapshot["vias"]) == 5
    assert snapshot["tracks"]
    assert all(t[2] for t in snapshot["tracks"]), "tracks without net"
    sides = {f["side"] for f in snapshot["footprints"]}
    assert sides == {"FRONT", "BACK"}
    assert any(f["orientation"] == 345 for f in snapshot["footprints"])
    outline = snapshot_board(DATA / "kicad10-outline.kicad_pcb")["outline"]
    assert len(outline) == 8


@pytest.fixture
def reference():
    return snapshot_board(DATA / "kicad10-rotations-vias.kicad_pcb")


def test_compare_identical(reference) -> None:
    assert compare_snapshots(reference, copy.deepcopy(reference)) == []


def test_compare_within_tolerance(reference) -> None:
    actual = copy.deepcopy(reference)
    actual["footprints"][0]["position"][0] += 2
    actual["footprints"][0]["pads"][0][1] -= 1
    actual["footprints"][0]["orientation"] = (
        actual["footprints"][0]["orientation"] - 0.0005
    ) % 360
    actual["tracks"][0][3][1] += 1
    actual["tracks"].reverse()
    assert compare_snapshots(reference, actual) == []


def test_compare_detects_differences(reference) -> None:
    actual = copy.deepcopy(reference)
    actual["footprints"][0]["position"][0] += 3
    flipped = {"FRONT": "BACK", "BACK": "FRONT"}
    actual["footprints"][1]["side"] = flipped[reference["footprints"][1]["side"]]
    actual["tracks"][0][2] = "OTHER_NET"
    del actual["vias"][0]
    differences = compare_snapshots(reference, actual)
    assert len(differences) == 5, differences
    assert any("position" in d for d in differences)
    assert any("side" in d for d in differences)
    assert any(d.startswith("tracks: missing") for d in differences)
    assert any(d.startswith("tracks: unexpected") for d in differences)
    assert any(d.startswith("vias: missing") for d in differences)
