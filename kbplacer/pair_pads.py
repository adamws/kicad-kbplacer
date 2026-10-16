# SPDX-FileCopyrightText: 2026 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pad geometry of a switch and diode pair placed by kbplacer.

Builds in-memory board with one switch and one diode, places the diode the same
way `--diode "D{} CUSTOM X Y ORIENTATION SIDE"` does and reports pad centres,
orientations, layers and nets. Positions are integer nanometres relative to the
switch origin, +Y down, in two frames: `switch_local` (switch rotated back to
0 degree) and `board` (board axes).
Nets follow kbplacer board builder convention: switch pad 1 -> COL,
diode pad 1 (K) -> ROW, switch pad 2 and diode pad 2 (A) -> SW_D.

The output is a golden fixture for tools which preview kbplacer placements
(for example kle-ng PCB generator) and for authoring switch presets.

Usage:

    python -m kbplacer.pair_pads \\
        --switch-footprint /path/Cherry_MX.pretty:SW_Cherry_MX_PCB_1.00u \\
        --diode-footprint /usr/share/kicad/footprints/Diode_SMD.pretty:D_SOD-123 \\
        --diode-position "5.08 4 90 BACK" --switch-rotation 90
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional

import pcbnew

from .board_modifier import (
    get_orientation,
    get_position,
    position_in_rotated_coordinates,
    set_rotation,
    set_side,
)
from .element_position import ElementPosition, Side
from .footprint_loader import FootprintIdentifier, load_footprint
from .key_placer import KeyPlacer

SWITCH_REFERENCE = "SW1"
DIODE_REFERENCE = "D1"
NETS = {("SW", "1"): "COL", ("D", "1"): "ROW", ("SW", "2"): "SW_D", ("D", "2"): "SW_D"}


def load_footprint_by_identifier(identifier: str) -> pcbnew.FOOTPRINT:
    """Load footprint from `LIBRARY_PATH:NAME` identifier."""
    parsed = FootprintIdentifier.from_str(identifier)
    return load_footprint(parsed.library_path, parsed.footprint_name)


def parse_element_position(value: str) -> ElementPosition:
    """Parse `X Y ORIENTATION FRONT|BACK`, same as diode CUSTOM position."""
    try:
        x, y, orientation, side = value.split()
        return ElementPosition(float(x), float(y), float(orientation), Side.get(side))
    except ValueError as e:
        msg = f"Expected 'X Y ORIENTATION FRONT|BACK', got '{value}'"
        raise ValueError(msg) from e


def build_pair_board(
    switch_footprint: str,
    diode_footprint: str,
    diode_position: ElementPosition,
    switch_rotation: float = 0,
    switch_side: Side = Side.FRONT,
) -> pcbnew.BOARD:
    board = pcbnew.CreateEmptyBoard()
    switch = load_footprint_by_identifier(switch_footprint)
    switch.SetReference(SWITCH_REFERENCE)
    diode = load_footprint_by_identifier(diode_footprint)
    diode.SetReference(DIODE_REFERENCE)
    board.Add(switch)
    board.Add(diode)

    nets: Dict[str, pcbnew.NETINFO_ITEM] = {}
    for prefix, footprint in (("SW", switch), ("D", diode)):
        for pad in footprint.Pads():
            netname = NETS.get((prefix, pad.GetNumber()))
            if netname:
                if netname not in nets:
                    nets[netname] = pcbnew.NETINFO_ITEM(board, netname, -1)
                    board.Add(nets[netname])
                pad.SetNet(nets[netname])

    if switch_side == Side.BACK:
        set_side(switch, Side.BACK)
    set_rotation(switch, switch_rotation)

    KeyPlacer(board).place_element(
        diode, diode_position, get_position(switch), get_orientation(switch)
    )
    return board


def _orientation(item: pcbnew.BOARD_ITEM) -> float:
    orientation = item.GetOrientation()
    if hasattr(orientation, "AsDegrees"):
        return orientation.AsDegrees()
    return orientation / 10  # KiCad 6 uses tenths of degree


def _pad_attribute(pad: pcbnew.PAD) -> str:
    return {
        pcbnew.PAD_ATTRIB_PTH: "PTH",
        pcbnew.PAD_ATTRIB_SMD: "SMD",
        pcbnew.PAD_ATTRIB_CONN: "CONN",
        pcbnew.PAD_ATTRIB_NPTH: "NPTH",
    }.get(pad.GetAttribute(), str(pad.GetAttribute()))


def dump_pair_pads(board: pcbnew.BOARD) -> Dict[str, Any]:
    """Describe pads of a board made by `build_pair_board`."""
    switch = board.FindFootprintByReference(SWITCH_REFERENCE)
    origin = get_position(switch)
    switch_orientation = get_orientation(switch)

    def _positions(point: pcbnew.VECTOR2I) -> Dict[str, Dict[str, int]]:
        relative = pcbnew.VECTOR2I(point.x - origin.x, point.y - origin.y)
        local = relative
        if switch_orientation:
            local = position_in_rotated_coordinates(relative, -switch_orientation)
        return {
            "switch_local": {"x_nm": int(local.x), "y_nm": int(local.y)},
            "board": {"x_nm": int(relative.x), "y_nm": int(relative.y)},
        }

    def _local_orientation(item: pcbnew.BOARD_ITEM) -> float:
        return round((_orientation(item) - switch_orientation) % 360, 6)

    footprints: List[Dict[str, Any]] = []
    for footprint in (switch, board.FindFootprintByReference(DIODE_REFERENCE)):
        pads = []
        for pad in footprint.Pads():
            layers = [
                board.GetLayerName(layer)
                for layer in pad.GetLayerSet().CuStack()
                if board.IsLayerEnabled(layer)
            ]
            pads.append(
                {
                    "number": pad.GetNumber(),
                    "net": pad.GetNetname(),
                    "attribute": _pad_attribute(pad),
                    "orientation_deg": _local_orientation(pad),
                    "layers": layers,
                    **_positions(pad.GetPosition()),
                }
            )
        pads.sort(
            key=lambda p: (
                p["number"],
                p["switch_local"]["x_nm"],
                p["switch_local"]["y_nm"],
            )
        )
        fpid = footprint.GetFPID()
        footprints.append(
            {
                "reference": footprint.GetReference(),
                "footprint": f"{fpid.GetLibNickname()}:{fpid.GetLibItemName()}",
                "orientation_deg": _local_orientation(footprint),
                "layer": "B.Cu" if footprint.IsFlipped() else "F.Cu",
                **_positions(footprint.GetPosition()),
                "pads": pads,
            }
        )
    return {"kicad_version": pcbnew.Version(), "footprints": footprints}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m kbplacer.pair_pads",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--switch-footprint", required=True, help="LIBRARY_PATH:NAME of switch"
    )
    parser.add_argument(
        "--diode-footprint", required=True, help="LIBRARY_PATH:NAME of diode"
    )
    parser.add_argument(
        "--diode-position",
        required=True,
        type=parse_element_position,
        help="X Y ORIENTATION FRONT|BACK, same as diode CUSTOM position",
    )
    parser.add_argument("--switch-rotation", type=float, default=0)
    parser.add_argument("--switch-side", type=Side.get, default=Side.FRONT)
    args = parser.parse_args(argv)

    board = build_pair_board(
        args.switch_footprint,
        args.diode_footprint,
        args.diode_position,
        switch_rotation=args.switch_rotation,
        switch_side=args.switch_side,
    )
    json.dump(dump_pair_pads(board), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
