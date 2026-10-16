# SPDX-FileCopyrightText: 2026 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
from pathlib import Path

import pytest

from kbplacer.element_position import ElementPosition, Side
from kbplacer.pair_pads import (
    build_pair_board,
    dump_pair_pads,
    load_footprint_by_identifier,
    main,
    parse_element_position,
)

from .conftest import get_footprints_dir

# Tools previewing kbplacer placements (kle-ng PCB generator) are tested against
# this dump. When this snapshot changes their fixtures must be regenerated too.
SNAPSHOT = Path(__file__).parent / "data/pair-pads/snapshot.json"
# rotated placements may round differently between KiCad versions
TOLERANCE_NM = 2

SWITCH = "SW_Cherry_MX_PCB_1.00u"
SMD_DIODE = "D_SOD-323F"
# footprint origin is pin 1, not the middle
THT_DIODE = "D_DO-34_SOD68_P7.62mm_Horizontal"

CASES = [
    (SMD_DIODE, "0 0 0 FRONT", 0),
    (SMD_DIODE, "5.08 4 90 FRONT", 0),
    (SMD_DIODE, "5.08 4 90 BACK", 0),
    (SMD_DIODE, "5.08 4 270 BACK", 90),
    (SMD_DIODE, "5.08 4 90 BACK", 37),
    (THT_DIODE, "-3.81 9.5 0 FRONT", 0),
    (THT_DIODE, "-3.81 9.5 90 BACK", 37),
]


def _case_id(case) -> str:
    diode, position, rotation = case
    return f"{diode}-{position.replace(' ', '_')}-{rotation}"


def _dump(request, diode, position, rotation):
    library = get_footprints_dir(request)
    board = build_pair_board(
        f"{library}:{SWITCH}",
        f"{library}:{diode}",
        parse_element_position(position),
        switch_rotation=rotation,
    )
    return dump_pair_pads(board)


def _assert_close(actual, expected, path="") -> None:
    if isinstance(expected, dict):
        assert actual.keys() == expected.keys(), path
        for key in expected:
            _assert_close(actual[key], expected[key], f"{path}.{key}")
    elif isinstance(expected, list):
        assert len(actual) == len(expected), path
        for i, (a, e) in enumerate(zip(actual, expected)):
            _assert_close(a, e, f"{path}[{i}]")
    elif isinstance(expected, int) and path.endswith("_nm"):
        assert abs(actual - expected) <= TOLERANCE_NM, path
    elif isinstance(expected, float):
        assert actual == pytest.approx(expected, abs=1e-3), path
    else:
        assert actual == expected, path


def test_snapshot(request) -> None:
    result = {_case_id(case): _dump(request, *case)["footprints"] for case in CASES}
    if request.config.getoption("--save-results-as-reference"):
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(json.dumps(result, indent=2) + "\n")
    _assert_close(result, json.loads(SNAPSHOT.read_text()))


@pytest.mark.parametrize("rotation", [0, 90, 37])
@pytest.mark.parametrize("side", ["FRONT", "BACK"])
def test_frames_agree(request, rotation, side) -> None:
    result = _dump(request, SMD_DIODE, f"5.08 4 90 {side}", rotation)
    for footprint in result["footprints"]:
        for item in [footprint, *footprint["pads"]]:
            local, board = item["switch_local"], item["board"]
            if rotation == 0:
                assert local == board
            # rotation keeps distance from switch origin
            assert (local["x_nm"] ** 2 + local["y_nm"] ** 2) ** 0.5 == pytest.approx(
                (board["x_nm"] ** 2 + board["y_nm"] ** 2) ** 0.5, abs=TOLERANCE_NM
            )
    diode = result["footprints"][1]
    assert diode["layer"] == ("B.Cu" if side == "BACK" else "F.Cu")
    _assert_close(
        diode["switch_local"], {"x_nm": 5080000, "y_nm": 4000000}, "switch_local"
    )


def test_identity_placement_keeps_footprint_pads(request) -> None:
    result = _dump(request, SMD_DIODE, "0 0 0 FRONT", 0)
    library = get_footprints_dir(request)
    footprint = load_footprint_by_identifier(f"{library}:{SMD_DIODE}")
    expected = sorted(
        (p.GetNumber(), p.GetPosition().x, p.GetPosition().y) for p in footprint.Pads()
    )
    actual = [
        (p["number"], p["switch_local"]["x_nm"], p["switch_local"]["y_nm"])
        for p in result["footprints"][1]["pads"]
    ]
    assert actual == expected


def test_nets(request) -> None:
    result = _dump(request, SMD_DIODE, "5.08 4 90 BACK", 0)
    nets = {
        (footprint["reference"], pad["number"]): pad["net"]
        for footprint in result["footprints"]
        for pad in footprint["pads"]
        if pad["number"]
    }
    assert nets == {
        ("SW1", "1"): "COL",
        ("SW1", "2"): "SW_D",
        ("D1", "1"): "ROW",
        ("D1", "2"): "SW_D",
    }


def test_parse_element_position() -> None:
    assert parse_element_position("1 -2.5 90 back") == ElementPosition(
        1, -2.5, 90, Side.BACK
    )
    with pytest.raises(ValueError, match="X Y ORIENTATION"):
        parse_element_position("1 2 90")
    with pytest.raises(ValueError, match="X Y ORIENTATION"):
        parse_element_position("1 2 90 TOP")


def test_main(request, capsys) -> None:
    library = get_footprints_dir(request)
    args = [
        "--switch-footprint",
        f"{library}:{SWITCH}",
        "--diode-footprint",
        f"{library}:{SMD_DIODE}",
        "--diode-position",
        "5.08 4 90 BACK",
        "--switch-rotation",
        "90",
    ]
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert [f["reference"] for f in result["footprints"]] == ["SW1", "D1"]
    assert result["footprints"][1]["layer"] == "B.Cu"
