# SPDX-FileCopyrightText: 2026 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""JSON format of switch-diode connection presets.

A preset describes one switch with its diodes and the tracks connecting them,
in switch-local coordinates (switch origin, 0 degree orientation, switch on the
front side, +Y down). It is the JSON counterpart of the `kicad_pcb` template
used by the `PRESET` position option. See `docs/switch-preset.schema.json`.

Field names and units follow KiCad's IPC API types (`kipy`): integer
nanometres, `{x_nm, y_nm}` vectors, tracks with `start`/`end`/`width`/`layer`,
vias with `position`/`diameter`/`drill_diameter` and footprint placement with
`position`/`orientation`/`layer`.

This module does not depend on `pcbnew`.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from .plugin_error import PluginError

PRESET_VERSION = 1
COPPER_LAYERS = ("F.Cu", "B.Cu")
# KiCad stores board coordinates as 32-bit integers
MAX_ABS_NM = 2**31 - 1


class PresetFormatError(PluginError):
    pass


@dataclass(frozen=True)
class Point:
    x_nm: int
    y_nm: int


@dataclass(frozen=True)
class TrackSegment:
    start: Point
    end: Point
    width_nm: int
    layer: str


@dataclass(frozen=True)
class Via:
    position: Point
    diameter_nm: int
    drill_diameter_nm: int


PresetItem = Union[TrackSegment, Via]


@dataclass(frozen=True)
class DiodePlacement:
    position: Point
    orientation_deg: float
    layer: str


@dataclass
class SwitchPreset:
    """
    :param diodes: Diode placements relative to the switch, in the order of
                   diodes associated with a switch. `None` means tracks-only
                   preset (diodes are not moved).
    :param items: Tracks and vias, normalised to switch position.
    :param basis: Free-form information about what preset was made for,
                  not used by kbplacer.
    """

    diodes: Optional[List[DiodePlacement]]
    items: List[PresetItem]
    basis: Optional[Dict[str, Any]] = None


def _fail(path: str, message: str) -> PresetFormatError:
    return PresetFormatError(f"Invalid switch preset: {path}: {message}")


def _expect_object(value: object, path: str, keys: List[str]) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise _fail(path, f"expected object, got {type(value).__name__}")
    unknown = sorted(set(value) - set(keys))
    if unknown:
        raise _fail(path, f"unknown properties: {', '.join(unknown)}")
    return value


def _required(obj: Dict[str, Any], key: str, path: str) -> object:
    if key not in obj:
        raise _fail(path, f"missing required property '{key}'")
    return obj[key]


def _parse_nm(value: object, path: str, *, positive: bool = False) -> int:
    # bool is subclass of int but `true` is never a valid coordinate
    if not isinstance(value, int) or isinstance(value, bool):
        raise _fail(path, f"expected integer nanometres, got {value!r}")
    if abs(value) > MAX_ABS_NM:
        raise _fail(path, f"value {value} out of range")
    if positive and value <= 0:
        raise _fail(path, f"expected positive value, got {value}")
    return value


def _parse_point(value: object, path: str) -> Point:
    obj = _expect_object(value, path, ["x_nm", "y_nm"])
    return Point(
        _parse_nm(_required(obj, "x_nm", path), f"{path}.x_nm"),
        _parse_nm(_required(obj, "y_nm", path), f"{path}.y_nm"),
    )


def _parse_layer(value: object, path: str) -> str:
    if not isinstance(value, str) or value not in COPPER_LAYERS:
        raise _fail(path, f"expected one of {', '.join(COPPER_LAYERS)}, got {value!r}")
    return value


def _parse_track(obj: Dict[str, Any], path: str) -> TrackSegment:
    _expect_object(obj, path, ["type", "start", "end", "width_nm", "layer"])
    start = _parse_point(_required(obj, "start", path), f"{path}.start")
    end = _parse_point(_required(obj, "end", path), f"{path}.end")
    if start == end:
        raise _fail(path, "track has zero length")
    width = _parse_nm(
        _required(obj, "width_nm", path), f"{path}.width_nm", positive=True
    )
    layer = _parse_layer(_required(obj, "layer", path), f"{path}.layer")
    return TrackSegment(start, end, width, layer)


def _parse_via(obj: Dict[str, Any], path: str) -> Via:
    _expect_object(obj, path, ["type", "position", "diameter_nm", "drill_diameter_nm"])
    position = _parse_point(_required(obj, "position", path), f"{path}.position")
    diameter = _parse_nm(
        _required(obj, "diameter_nm", path), f"{path}.diameter_nm", positive=True
    )
    drill = _parse_nm(
        _required(obj, "drill_diameter_nm", path),
        f"{path}.drill_diameter_nm",
        positive=True,
    )
    if drill >= diameter:
        raise _fail(path, "drill_diameter_nm must be smaller than diameter_nm")
    return Via(position, diameter, drill)


def _parse_item(value: object, path: str) -> PresetItem:
    if not isinstance(value, dict):
        raise _fail(path, f"expected object, got {type(value).__name__}")
    item_type = _required(value, "type", path)
    if item_type == "track":
        return _parse_track(value, path)
    if item_type == "via":
        return _parse_via(value, path)
    if item_type == "arc":
        raise _fail(path, "arc tracks are not supported yet")
    raise _fail(path, f"unknown item type {item_type!r}")


def _parse_diode(value: object, path: str) -> DiodePlacement:
    obj = _expect_object(value, path, ["position", "orientation_deg", "layer"])
    position = _parse_point(_required(obj, "position", path), f"{path}.position")
    orientation = _required(obj, "orientation_deg", path)
    if (
        not isinstance(orientation, (int, float))
        or isinstance(orientation, bool)
        or not math.isfinite(orientation)
    ):
        raise _fail(f"{path}.orientation_deg", f"expected number, got {orientation!r}")
    layer = _parse_layer(_required(obj, "layer", path), f"{path}.layer")
    return DiodePlacement(position, float(orientation), layer)


def parse_switch_preset(data: object) -> SwitchPreset:
    """Validates and converts decoded JSON document to `SwitchPreset`.

    :raises PresetFormatError: when document does not match the schema.
    """
    obj = _expect_object(data, "$", ["$schema", "version", "diodes", "items", "basis"])
    version = _required(obj, "version", "$")
    if version != PRESET_VERSION or isinstance(version, bool):
        raise _fail("$.version", f"unsupported version {version!r}")

    diodes: Optional[List[DiodePlacement]] = None
    if "diodes" in obj:
        raw_diodes = obj["diodes"]
        if not isinstance(raw_diodes, list) or not raw_diodes:
            raise _fail("$.diodes", "expected non-empty array (omit for tracks-only)")
        diodes = [_parse_diode(d, f"$.diodes[{i}]") for i, d in enumerate(raw_diodes)]

    raw_items = _required(obj, "items", "$")
    if not isinstance(raw_items, list) or not raw_items:
        raise _fail("$.items", "expected non-empty array")
    items = [_parse_item(item, f"$.items[{i}]") for i, item in enumerate(raw_items)]

    basis = obj.get("basis")
    if basis is not None and not isinstance(basis, dict):
        raise _fail("$.basis", f"expected object, got {type(basis).__name__}")

    return SwitchPreset(diodes, items, basis)


def load_switch_preset(path: str) -> SwitchPreset:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        msg = f"Invalid switch preset: '{path}' is not valid JSON: {e}"
        raise PresetFormatError(msg) from e
    return parse_switch_preset(data)


def _point_to_dict(point: Point) -> Dict[str, int]:
    return {"x_nm": point.x_nm, "y_nm": point.y_nm}


def _item_to_dict(item: PresetItem) -> Dict[str, Any]:
    if isinstance(item, TrackSegment):
        return {
            "type": "track",
            "start": _point_to_dict(item.start),
            "end": _point_to_dict(item.end),
            "width_nm": item.width_nm,
            "layer": item.layer,
        }
    return {
        "type": "via",
        "position": _point_to_dict(item.position),
        "diameter_nm": item.diameter_nm,
        "drill_diameter_nm": item.drill_diameter_nm,
    }


def _orientation_to_json(value: float) -> Union[int, float]:
    return int(value) if float(value).is_integer() else value


def switch_preset_to_dict(preset: SwitchPreset) -> Dict[str, Any]:
    result: Dict[str, Any] = {"version": PRESET_VERSION}
    if preset.diodes is not None:
        result["diodes"] = [
            {
                "position": _point_to_dict(d.position),
                "orientation_deg": _orientation_to_json(d.orientation_deg),
                "layer": d.layer,
            }
            for d in preset.diodes
        ]
    result["items"] = [_item_to_dict(item) for item in preset.items]
    if preset.basis is not None:
        result["basis"] = preset.basis
    return result


def dump_switch_preset(preset: SwitchPreset) -> str:
    return json.dumps(switch_preset_to_dict(preset), indent=2) + "\n"
