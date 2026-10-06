# SPDX-FileCopyrightText: 2026 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Dump switch-local pad geometry of a switch and diode placed by kbplacer.

Builds in-memory board with one switch and one diode, places the diode the same
way `--diode "D{} CUSTOM X Y ORIENTATION SIDE"` does and prints JSON with pad
centres, orientations, layers and nets in switch-local coordinates (switch
origin, switch rotated back to 0 degree, +Y down, integer nanometres).
Nets follow kbplacer board builder convention: switch pad 1 -> COL,
diode pad 1 (K) -> ROW, switch pad 2 and diode pad 2 (A) -> SW_D.

The output is a golden fixture for tools which preview kbplacer placements
(for example kle-ng PCB generator) and for authoring switch presets.

Example:

    python tools/dump_pair_pads.py \\
        --switch-footprint /path/Cherry_MX.pretty:SW_Cherry_MX_PCB_1.00u \\
        --diode-footprint /usr/share/kicad/footprints/Diode_SMD.pretty:D_SOD-123 \\
        --diode-position "5.08 4 90 BACK" --switch-rotation 90
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

import pcbnew

from kbplacer.board_modifier import (
    get_orientation,
    get_position,
    position_in_rotated_coordinates,
    set_rotation,
    set_side,
)
from kbplacer.element_position import ElementPosition, Side
from kbplacer.footprint_loader import load_footprint
from kbplacer.key_placer import KeyPlacer

NETS = {("SW", "1"): "COL", ("D", "1"): "ROW", ("SW", "2"): "SW_D", ("D", "2"): "SW_D"}


def _load(identifier: str) -> pcbnew.FOOTPRINT:
    library, _, name = identifier.rpartition(":")
    if not library or not name:
        msg = f"Footprint must be in LIBRARY_PATH:NAME format, got '{identifier}'"
        raise ValueError(msg)
    return load_footprint(library, name)


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


def build_board(args: argparse.Namespace) -> pcbnew.BOARD:
    board = pcbnew.CreateEmptyBoard()
    switch = _load(args.switch_footprint)
    switch.SetReference("SW1")
    diode = _load(args.diode_footprint)
    diode.SetReference("D1")
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

    if args.switch_side == Side.BACK:
        set_side(switch, Side.BACK)
    set_rotation(switch, args.switch_rotation)

    x, y, orientation, side = args.diode_position.split()
    position = ElementPosition(float(x), float(y), float(orientation), Side.get(side))
    KeyPlacer(board).place_element(
        diode, position, get_position(switch), get_orientation(switch)
    )
    return board


def dump(board: pcbnew.BOARD) -> Dict[str, Any]:
    switch = board.FindFootprintByReference("SW1")
    origin = get_position(switch)
    switch_orientation = get_orientation(switch)

    def _local(point: pcbnew.VECTOR2I) -> Dict[str, int]:
        relative = pcbnew.VECTOR2I(point.x - origin.x, point.y - origin.y)
        if switch_orientation:
            relative = position_in_rotated_coordinates(relative, -switch_orientation)
        return {"x_nm": int(relative.x), "y_nm": int(relative.y)}

    footprints: List[Dict[str, Any]] = []
    for footprint in (switch, board.FindFootprintByReference("D1")):
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
                    "position": _local(pad.GetPosition()),
                    "orientation_deg": round(
                        (_orientation(pad) - switch_orientation) % 360, 6
                    ),
                    "layers": layers,
                }
            )
        pads.sort(
            key=lambda p: (p["number"], p["position"]["x_nm"], p["position"]["y_nm"])
        )
        fpid = footprint.GetFPID()
        footprints.append(
            {
                "reference": footprint.GetReference(),
                "footprint": f"{fpid.GetLibNickname()}:{fpid.GetLibItemName()}",
                "position": _local(footprint.GetPosition()),
                "orientation_deg": round(
                    (_orientation(footprint) - switch_orientation) % 360, 6
                ),
                "layer": "B.Cu" if footprint.IsFlipped() else "F.Cu",
                "pads": pads,
            }
        )
    return {"kicad_version": pcbnew.Version(), "footprints": footprints}


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
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
        help="X Y ORIENTATION FRONT|BACK, same as diode CUSTOM position",
    )
    parser.add_argument("--switch-rotation", type=float, default=0)
    parser.add_argument("--switch-side", type=Side.get, default=Side.FRONT)
    args = parser.parse_args(argv)

    board = build_board(args)
    json.dump(dump(board), sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
