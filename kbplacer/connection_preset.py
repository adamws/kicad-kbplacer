# SPDX-FileCopyrightText: 2026 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Conversion between switch preset JSON (`preset_format`) and `pcbnew` items.

Usage, converting a `kicad_pcb` template to JSON preset:

    python -m kbplacer.connection_preset to-json template.kicad_pcb > preset.json
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import pcbnew

from .board_modifier import (
    KICAD_VERSION,
    duplicate_track,
    get_orientation,
    get_position,
    rotate,
)
from .element_position import ElementPosition, Side
from .preset_format import (
    DiodePlacement,
    Point,
    PresetItem,
    SwitchPreset,
    TrackSegment,
    Via,
    dump_switch_preset,
)

_LAYER_IDS = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu}
_LAYER_NAMES = {v: k for k, v in _LAYER_IDS.items()}
_SIDE_BY_LAYER = {"F.Cu": Side.FRONT, "B.Cu": Side.BACK}
_LAYER_BY_SIDE = {v: k for k, v in _SIDE_BY_LAYER.items()}


@dataclass
class ConnectionPreset:
    """Preset loaded from `kicad_pcb` template or JSON file.

    :param diode_positions: Diode positions relative to switch, `None` when
                            preset does not define them (tracks-only preset).
    :param tracks: Tracks and vias normalised to switch position and
                   orientation, with no netcodes and not added to any board.
    :param source_board: Board which `tracks` were copied from. Copies keep
                         pointer to it, so it must outlive them.
    """

    diode_positions: Optional[List[ElementPosition]]
    tracks: List[pcbnew.PCB_TRACK]
    source_board: Optional[pcbnew.BOARD] = None


def is_json_preset(path: str) -> bool:
    return Path(path).suffix.lower() == ".json"


def _to_vector(point: Point) -> pcbnew.VECTOR2I:
    if KICAD_VERSION < (7, 0, 0):
        return pcbnew.wxPoint(point.x_nm, point.y_nm)
    return pcbnew.VECTOR2I(point.x_nm, point.y_nm)


def _to_point(vector: pcbnew.VECTOR2I) -> Point:
    return Point(int(vector.x), int(vector.y))


def _build_item(board: pcbnew.BOARD, item: PresetItem) -> pcbnew.PCB_TRACK:
    if isinstance(item, TrackSegment):
        track = pcbnew.PCB_TRACK(board)
        track.SetStart(_to_vector(item.start))
        track.SetEnd(_to_vector(item.end))
        track.SetWidth(item.width_nm)
        track.SetLayer(_LAYER_IDS[item.layer])
        return track
    via = pcbnew.PCB_VIA(board)
    via.SetViaType(pcbnew.VIATYPE_THROUGH)
    via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
    via.SetPosition(_to_vector(item.position))
    via.SetWidth(item.diameter_nm)
    via.SetDrill(item.drill_diameter_nm)
    return via


def preset_items_to_tracks(
    board: pcbnew.BOARD, preset: SwitchPreset
) -> List[pcbnew.PCB_TRACK]:
    """Creates (not added to the board) tracks and vias with no netcodes."""
    return [_build_item(board, item) for item in preset.items]


def preset_diode_positions(preset: SwitchPreset) -> Optional[List[ElementPosition]]:
    if preset.diodes is None:
        return None
    return [
        ElementPosition(
            d.position.x_nm / 1e6,
            d.position.y_nm / 1e6,
            d.orientation_deg,
            _SIDE_BY_LAYER[d.layer],
        )
        for d in preset.diodes
    ]


def normalize_template_tracks(
    tracks: List[pcbnew.PCB_TRACK], switch: pcbnew.FOOTPRINT
) -> List[pcbnew.PCB_TRACK]:
    """Returns copies of `tracks`, without netcodes, in coordinates of `switch`
    (centered in switch position and rotated back to 0 degree orientation).
    """
    origin = get_position(switch)
    angle = get_orientation(switch)
    result = []
    for item in tracks:
        item_copy = duplicate_track(item)
        item_copy.SetNetCode(0)
        if angle:
            rotate(item_copy, origin, angle)
        if KICAD_VERSION < (7, 0, 0):
            item_copy.Move(pcbnew.wxPoint(-origin.x, -origin.y))
        else:
            item_copy.Move(pcbnew.VECTOR2I(-origin.x, -origin.y))
        result.append(item_copy)
    return result


def _via_diameter(via: pcbnew.PCB_VIA) -> int:
    # since KiCad 9 vias have padstacks, size without layer argument is deprecated
    if KICAD_VERSION >= (9, 0, 0):
        return via.GetWidth(pcbnew.F_Cu)
    return via.GetWidth()


def _track_to_item(track: pcbnew.PCB_TRACK) -> PresetItem:
    if track.Type() == pcbnew.PCB_VIA_T:
        via = pcbnew.Cast_to_PCB_VIA(track)
        if via.GetViaType() != pcbnew.VIATYPE_THROUGH:
            msg = "Only through vias are supported in switch presets"
            raise ValueError(msg)
        return Via(
            _to_point(via.GetPosition()), _via_diameter(via), via.GetDrillValue()
        )
    if track.Type() != pcbnew.PCB_TRACE_T:
        msg = "Arc tracks are not supported in switch presets yet"
        raise ValueError(msg)
    layer = track.GetLayer()
    if layer not in _LAYER_NAMES:
        name = track.GetBoard().GetLayerName(layer) if track.GetBoard() else layer
        msg = f"Track on unsupported layer '{name}', only F.Cu and B.Cu allowed"
        raise ValueError(msg)
    return TrackSegment(
        _to_point(track.GetStart()),
        _to_point(track.GetEnd()),
        track.GetWidth(),
        _LAYER_NAMES[layer],
    )


def connection_preset_to_switch_preset(
    preset: ConnectionPreset, basis: Optional[dict] = None
) -> SwitchPreset:
    """Converts loaded (normalised) preset to its JSON representation.

    :raises ValueError: when preset contains items not representable in JSON
                        format (arcs, blind/buried vias, inner layers).
    """
    diodes = None
    if preset.diode_positions is not None:
        diodes = [
            DiodePlacement(
                Point(round(p.x * 1e6), round(p.y * 1e6)),
                p.orientation,
                _LAYER_BY_SIDE[p.side],
            )
            for p in preset.diode_positions
        ]
    items = [_track_to_item(t) for t in preset.tracks]
    return SwitchPreset(diodes, items, basis)


def _footprint_name(footprint: pcbnew.FOOTPRINT) -> str:
    fpid = footprint.GetFPID()
    return f"{fpid.GetLibNickname()}:{fpid.GetLibItemName()}"


def _to_json(args: argparse.Namespace) -> int:
    # imported here, `key_placer` depends on this module
    from .key_placer import KeyMatrix, KeyPlacer  # noqa: PLC0415

    board = pcbnew.LoadBoard(args.template)
    placer = KeyPlacer(board)
    preset = placer.load_kicad_pcb_preset(args.template, args.switch, args.diode)

    matrix = KeyMatrix(board, args.switch, args.diode)
    switch_reference = matrix.first_switch_reference()
    switch = matrix.switch_by_reference(switch_reference)
    diodes = matrix.diodes_by_switch_reference(switch_reference)
    basis = {
        "source": Path(args.template).name,
        "switchFootprint": _footprint_name(switch),
        "diodeFootprints": [_footprint_name(d) for d in diodes],
    }
    try:
        result = connection_preset_to_switch_preset(preset, basis)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    sys.stdout.write(dump_switch_preset(result))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m kbplacer.connection_preset",
        description="Switch preset conversion tools",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    to_json = subparsers.add_parser(
        "to-json",
        help="Convert kicad_pcb switch-diode template to JSON preset (stdout)",
    )
    to_json.add_argument("template", help="Path to kicad_pcb template file")
    to_json.add_argument(
        "--switch", default="SW{}", help="Switch annotation format (default SW{})"
    )
    to_json.add_argument(
        "--diode", default="D{}", help="Diode annotation format (default D{})"
    )
    args = parser.parse_args(argv)
    return _to_json(args)


if __name__ == "__main__":
    sys.exit(main())
