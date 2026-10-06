# SPDX-FileCopyrightText: 2026 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
from pathlib import Path

import pcbnew
import pytest

from kbplacer.connection_preset import (
    ConnectionPreset,
    connection_preset_to_switch_preset,
    is_json_preset,
    main,
    normalize_template_tracks,
    preset_diode_positions,
    preset_items_to_tracks,
)
from kbplacer.element_position import ElementPosition, Side
from kbplacer.key_placer import KeyPlacer
from kbplacer.preset_format import (
    TrackSegment,
    Via,
    load_switch_preset,
    parse_switch_preset,
)

from .conftest import KICAD_VERSION, rotate

EXAMPLE_DIR = (
    Path(__file__).parent.parent
    / "examples"
    / "2x3-rotations-custom-diode-with-track-and-complex-footprint"
)
KICAD_PCB_TEMPLATE = EXAMPLE_DIR / "diode_template.kicad_pcb"
JSON_TEMPLATE = EXAMPLE_DIR / "diode_template.json"

PRESET = {
    "version": 1,
    "diodes": [
        {
            "position": {"x_nm": 5080000, "y_nm": 4000000},
            "orientation_deg": 90,
            "layer": "B.Cu",
        }
    ],
    "items": [
        {
            "type": "track",
            "start": {"x_nm": 2540000, "y_nm": -5080000},
            "end": {"x_nm": 5080000, "y_nm": -2540000},
            "width_nm": 250000,
            "layer": "B.Cu",
        },
        {
            "type": "via",
            "position": {"x_nm": 0, "y_nm": 1000000},
            "diameter_nm": 600000,
            "drill_diameter_nm": 300000,
        },
    ],
}


def _vector(x: int, y: int):
    if KICAD_VERSION < (7, 0, 0):
        return pcbnew.wxPoint(x, y)
    return pcbnew.VECTOR2I(x, y)


@pytest.mark.parametrize(
    "path,expected",
    [("a.json", True), ("a.JSON", True), ("a.kicad_pcb", False), ("json", False)],
)
def test_is_json_preset(path, expected) -> None:
    assert is_json_preset(path) == expected


def test_preset_items_to_tracks() -> None:
    board = pcbnew.CreateEmptyBoard()
    preset = parse_switch_preset(PRESET)
    track, via = preset_items_to_tracks(board, preset)

    assert track.Type() == pcbnew.PCB_TRACE_T
    assert track.GetStart() == _vector(2540000, -5080000)
    assert track.GetEnd() == _vector(5080000, -2540000)
    assert track.GetWidth() == 250000
    assert track.GetLayer() == pcbnew.B_Cu
    assert track.GetNetCode() == 0

    assert via.Type() == pcbnew.PCB_VIA_T
    assert via.GetPosition() == _vector(0, 1000000)
    if KICAD_VERSION >= (9, 0, 0):
        assert via.GetWidth(pcbnew.F_Cu) == 600000
        assert via.GetWidth(pcbnew.B_Cu) == 600000
    else:
        assert via.GetWidth() == 600000
    assert via.GetDrillValue() == 300000
    assert via.GetViaType() == pcbnew.VIATYPE_THROUGH
    assert via.GetNetCode() == 0

    # items are templates, they must not be added to the board:
    assert len(board.GetTracks()) == 0


def test_preset_diode_positions() -> None:
    preset = parse_switch_preset(PRESET)
    assert preset_diode_positions(preset) == [
        ElementPosition(5.08, 4.0, 90.0, Side.BACK)
    ]
    tracks_only = {k: v for k, v in PRESET.items() if k != "diodes"}
    assert preset_diode_positions(parse_switch_preset(tracks_only)) is None


def test_connection_preset_to_switch_preset_round_trip() -> None:
    board = pcbnew.CreateEmptyBoard()
    preset = parse_switch_preset(PRESET)
    loaded = ConnectionPreset(
        preset_diode_positions(preset), preset_items_to_tracks(board, preset)
    )
    result = connection_preset_to_switch_preset(loaded)
    assert result.diodes == preset.diodes
    assert result.items == preset.items


def test_connection_preset_to_switch_preset_rejects_arc() -> None:
    board = pcbnew.CreateEmptyBoard()
    arc = pcbnew.PCB_ARC(board)
    arc.SetStart(_vector(0, 0))
    arc.SetMid(_vector(1000000, 1000000))
    arc.SetEnd(_vector(2000000, 0))
    with pytest.raises(ValueError, match="Arc tracks are not supported"):
        connection_preset_to_switch_preset(ConnectionPreset(None, [arc]))


def test_kicad_pcb_and_json_presets_are_equivalent() -> None:
    placer = KeyPlacer(pcbnew.CreateEmptyBoard())
    from_kicad_pcb = placer.load_kicad_pcb_preset(
        str(KICAD_PCB_TEMPLATE), "SW{}", "D{}"
    )
    from_json = placer.load_json_preset(str(JSON_TEMPLATE))

    result1 = connection_preset_to_switch_preset(from_kicad_pcb)
    result2 = connection_preset_to_switch_preset(from_json)
    assert result1.diodes == result2.diodes
    assert result1.items == result2.items
    assert result1.diodes == load_switch_preset(str(JSON_TEMPLATE)).diodes


def test_kicad_pcb_preset_tracks_are_normalized(tmpdir) -> None:
    # move and rotate whole template, loaded preset must not change
    board = pcbnew.LoadBoard(str(KICAD_PCB_TEMPLATE))
    center = _vector(pcbnew.FromMM(50), pcbnew.FromMM(30))
    for footprint in board.GetFootprints():
        footprint.Move(center)
    for track in board.GetTracks():
        track.Move(center)
    for item in [*board.GetFootprints(), *board.GetTracks()]:
        rotate(item, center, 30)
    moved_path = f"{tmpdir}/moved_template.kicad_pcb"
    board.Save(moved_path)

    placer = KeyPlacer(pcbnew.CreateEmptyBoard())
    moved = placer.load_kicad_pcb_preset(moved_path, "SW{}", "D{}")
    expected = load_switch_preset(str(JSON_TEMPLATE))

    assert moved.diode_positions is not None
    assert len(moved.diode_positions) == 1
    assert moved.diode_positions[0].x == pytest.approx(0, abs=1e-5)
    assert moved.diode_positions[0].y == pytest.approx(3.8, abs=1e-5)
    assert moved.diode_positions[0].side == Side.BACK

    # saving board may reorder tracks, compare as sets with rounding
    # (rotating back and forth may be off by a nanometre):
    def _key(item):
        def _r(value):
            return round(value / 10)

        if isinstance(item, TrackSegment):
            points = sorted(
                [
                    (_r(item.start.x_nm), _r(item.start.y_nm)),
                    (_r(item.end.x_nm), _r(item.end.y_nm)),
                ]
            )
            return ("track", item.layer, item.width_nm, *points)
        assert isinstance(item, Via)
        position = (_r(item.position.x_nm), _r(item.position.y_nm))
        return ("via", item.diameter_nm, item.drill_diameter_nm, position)

    items = connection_preset_to_switch_preset(moved).items
    assert sorted(map(_key, items)) == sorted(map(_key, expected.items))


def test_normalize_template_tracks_does_not_modify_originals() -> None:
    board = pcbnew.LoadBoard(str(KICAD_PCB_TEMPLATE))
    switch = board.FindFootprintByReference("SW1")
    tracks = list(board.GetTracks())
    netcodes = [t.GetNetCode() for t in tracks]
    result = normalize_template_tracks(tracks, switch)
    assert [t.GetNetCode() for t in tracks] == netcodes
    assert all(t.GetNetCode() == 0 for t in result)


def test_to_json_command(capsys) -> None:
    assert main(["to-json", str(KICAD_PCB_TEMPLATE)]) == 0
    output = json.loads(capsys.readouterr().out)
    result = parse_switch_preset(output)
    expected = load_switch_preset(str(JSON_TEMPLATE))
    assert result.diodes == expected.diodes
    assert result.items == expected.items
    assert output["basis"]["switchFootprint"].endswith(
        "Kailh_socket_PG1350_optional_reversible"
    )
