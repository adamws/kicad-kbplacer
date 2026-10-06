# SPDX-FileCopyrightText: 2026 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import copy
import json
from pathlib import Path

import pytest

from kbplacer.preset_format import (
    DiodePlacement,
    Point,
    PresetFormatError,
    SwitchPreset,
    TrackSegment,
    Via,
    dump_switch_preset,
    load_switch_preset,
    parse_switch_preset,
    switch_preset_to_dict,
)

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"

TRACK = {
    "type": "track",
    "start": {"x_nm": 2540000, "y_nm": -5080000},
    "end": {"x_nm": 5080000, "y_nm": -2540000},
    "width_nm": 250000,
    "layer": "B.Cu",
}
VIA = {
    "type": "via",
    "position": {"x_nm": 0, "y_nm": 1000000},
    "diameter_nm": 600000,
    "drill_diameter_nm": 300000,
}
DIODE = {
    "position": {"x_nm": 5080000, "y_nm": 4000000},
    "orientation_deg": 90,
    "layer": "B.Cu",
}


def preset(**kwargs):
    result = {"version": 1, "diodes": [DIODE], "items": [TRACK, VIA]}
    result.update(kwargs)
    return copy.deepcopy(result)


def test_parse_full_preset() -> None:
    result = parse_switch_preset(preset(basis={"switchFootprint": "x"}))
    assert result == SwitchPreset(
        [DiodePlacement(Point(5080000, 4000000), 90.0, "B.Cu")],
        [
            TrackSegment(
                Point(2540000, -5080000), Point(5080000, -2540000), 250000, "B.Cu"
            ),
            Via(Point(0, 1000000), 600000, 300000),
        ],
        {"switchFootprint": "x"},
    )


def test_parse_tracks_only_preset() -> None:
    data = preset()
    del data["diodes"]
    result = parse_switch_preset(data)
    assert result.diodes is None
    assert len(result.items) == 2


def test_parse_multiple_diodes() -> None:
    second = copy.deepcopy(DIODE)
    second["position"] = {"x_nm": -5080000, "y_nm": 4000000}
    second["orientation_deg"] = 270.5
    result = parse_switch_preset(preset(diodes=[DIODE, second]))
    assert result.diodes is not None
    assert [d.position.x_nm for d in result.diodes] == [5080000, -5080000]
    assert result.diodes[1].orientation_deg == 270.5


def test_schema_key_is_allowed() -> None:
    parse_switch_preset(preset(**{"$schema": "switch-preset.schema.json"}))


@pytest.mark.parametrize(
    "modify,error",
    [
        (lambda d: d.update(version=2), r"\$\.version: unsupported version 2"),
        (lambda d: d.update(version=True), r"\$\.version: unsupported version"),
        (lambda d: d.pop("version"), r"\$: missing required property 'version'"),
        (lambda d: d.pop("items"), r"\$: missing required property 'items'"),
        (lambda d: d.update(items=[]), r"\$\.items: expected non-empty array"),
        (lambda d: d.update(diodes=[]), r"\$\.diodes: expected non-empty array"),
        (lambda d: d.update(extra=1), r"\$: unknown properties: extra"),
        (lambda d: d.update(basis=[]), r"\$\.basis: expected object"),
        (
            lambda d: d["items"][0].update(type="arc"),
            r"\$\.items\[0\]: arc tracks are not supported yet",
        ),
        (
            lambda d: d["items"][0].update(type="zone"),
            r"\$\.items\[0\]: unknown item type 'zone'",
        ),
        (lambda d: d["items"][0].pop("type"), r"missing required property 'type'"),
        (
            lambda d: d["items"][0]["start"].update(x_nm=1.5),
            r"\$\.items\[0\]\.start\.x_nm: expected integer nanometres, got 1\.5",
        ),
        (
            lambda d: d["items"][0]["start"].update(x_nm="1"),
            r"expected integer nanometres",
        ),
        (
            lambda d: d["items"][0]["start"].update(x_nm=True),
            r"expected integer nanometres",
        ),
        (
            lambda d: d["items"][0]["start"].update(x_nm=2**31),
            r"\$\.items\[0\]\.start\.x_nm: value 2147483648 out of range",
        ),
        (
            lambda d: d["items"][0]["start"].update(z_nm=0),
            r"\$\.items\[0\]\.start: unknown properties: z_nm",
        ),
        (
            lambda d: d["items"][0].update(end=d["items"][0]["start"]),
            r"\$\.items\[0\]: track has zero length",
        ),
        (
            lambda d: d["items"][0].update(width_nm=0),
            r"\$\.items\[0\]\.width_nm: expected positive value",
        ),
        (
            lambda d: d["items"][0].update(layer="In1.Cu"),
            r"\$\.items\[0\]\.layer: expected one of F\.Cu, B\.Cu",
        ),
        (
            lambda d: d["items"][0].update(net=1),
            r"\$\.items\[0\]: unknown properties: net",
        ),
        (
            lambda d: d["items"][1].update(drill_diameter_nm=600000),
            r"\$\.items\[1\]: drill_diameter_nm must be smaller than diameter_nm",
        ),
        (
            lambda d: d["diodes"][0].update(orientation_deg="90"),
            r"\$\.diodes\[0\]\.orientation_deg: expected number",
        ),
        (
            lambda d: d["diodes"][0].update(orientation_deg=float("nan")),
            r"\$\.diodes\[0\]\.orientation_deg: expected number",
        ),
        (
            lambda d: d["diodes"][0].update(layer="FRONT"),
            r"\$\.diodes\[0\]\.layer: expected one of",
        ),
    ],
)
def test_parse_invalid_preset(modify, error) -> None:
    data = preset()
    modify(data)
    with pytest.raises(PresetFormatError, match=error):
        parse_switch_preset(data)


def test_parse_not_an_object() -> None:
    with pytest.raises(PresetFormatError, match=r"\$: expected object, got list"):
        parse_switch_preset([])


def test_round_trip() -> None:
    data = preset(basis={"source": "template.kicad_pcb"})
    result = parse_switch_preset(data)
    assert switch_preset_to_dict(result) == data
    assert parse_switch_preset(json.loads(dump_switch_preset(result))) == result


def test_orientation_serialized_as_integer_when_possible() -> None:
    result = parse_switch_preset(preset())
    assert switch_preset_to_dict(result)["diodes"][0]["orientation_deg"] == 90
    assert isinstance(
        switch_preset_to_dict(result)["diodes"][0]["orientation_deg"], int
    )


def test_load_invalid_json(tmpdir) -> None:
    path = Path(tmpdir) / "preset.json"
    path.write_text("{not json")
    with pytest.raises(PresetFormatError, match=r"is not valid JSON"):
        load_switch_preset(str(path))


def test_load_example_presets() -> None:
    presets = list(EXAMPLES_DIR.glob("*/*_template.json"))
    assert len(presets) >= 2
    for path in presets:
        result = load_switch_preset(str(path))
        assert result.items


def test_schema_document_is_valid_json() -> None:
    schema_path = Path(__file__).parent.parent / "docs" / "switch-preset.schema.json"
    schema = json.loads(schema_path.read_text())
    assert schema["properties"]["version"] == {"const": 1}
    # keep in sync with the parser:
    assert set(schema["properties"]) == {
        "$schema",
        "version",
        "diodes",
        "items",
        "basis",
    }
    assert set(schema["$defs"]["track"]["required"]) == {
        "type",
        "start",
        "end",
        "width_nm",
        "layer",
    }
    assert set(schema["$defs"]["via"]["required"]) == {
        "type",
        "position",
        "diameter_nm",
        "drill_diameter_nm",
    }
