from __future__ import annotations

import json
from typing import Tuple

import pcbnew
import pytest

from .conftest import (
    add_diode_footprint,
    add_switch_footprint,
    generate_render,
)

try:
    from kbplacer.board_modifier import (
        get_footprint,
        get_position,
        set_position,
        set_side,
    )
    from kbplacer.defaults import DEFAULT_DIODE_POSITION
    from kbplacer.element_position import ElementInfo, PositionOption, Side
    from kbplacer.key_placer import KeyPlacer
except:
    # satisfy import issues when running examples tests
    # in docker image on CI.
    # these tests should not be executed but pytest
    # would fail to collect test information without that:
    from enum import Flag

    class Side(Flag):
        FRONT = False
        BACK = True


def equal_ignore_order(a, b):
    unmatched = list(b)
    for element in a:
        try:
            unmatched.remove(element)
        except ValueError:
            return False
    return not unmatched


def get_board_with_one_switch(
    request, footprint: str
) -> Tuple[pcbnew.BOARD, pcbnew.FOOTPRINT, pcbnew.FOOTPRINT]:
    board = pcbnew.CreateEmptyBoard()
    net_info = board.GetNetInfo()
    net_count = board.GetNetCount()
    switch_diode_net = pcbnew.NETINFO_ITEM(board, "Net-(D1-Pad2)", net_count)
    net_info.AppendNet(switch_diode_net)
    board.Add(switch_diode_net)

    switch = add_switch_footprint(board, request, 1, footprint=footprint)
    diode = add_diode_footprint(board, request, 1)

    for p in switch.Pads():
        if p.GetNumber() == "2":
            p.SetNet(switch_diode_net)
    diode.FindPadByNumber("2").SetNet(switch_diode_net)

    column_net = pcbnew.NETINFO_ITEM(board, "COL1", net_count + 1)
    net_info.AppendNet(column_net)
    board.Add(column_net)

    for p in switch.Pads():
        if p.GetNumber() == "1":
            p.SetNet(column_net)

    return board, switch, diode


def assert_board_tracks(expected: list[Tuple[int, int]] | None, board: pcbnew.BOARD):
    expected_wx = [pcbnew.wxPoint(x[0], x[1]) for x in expected] if expected else None
    points = []
    for track in board.GetTracks():
        start = track.GetStart()
        if start not in points:
            points.append(start)
        end = track.GetEnd()
        if end not in points:
            points.append(end)

    if expected_wx:
        assert equal_ignore_order(points, expected_wx)
    else:
        assert not points


@pytest.mark.parametrize(
    "position,orientation,expected",
    [
        # fmt: off
        # simple cases when pads in line, expecting single segment track:
        ((-4,  0),   0, [(-410000, -5080000), (2540000, -5080000)]),
        (( 0,  4),  90, [(2540000, -2130000), (2540000, -5080000)]),
        (( 4,  0), 180, [(5490000, -5080000), (2540000, -5080000)]),
        (( 0, -4), 270, [(2540000, -8030000), (2540000, -5080000)]),
        # cases where need to route with two segment track:
        ((-4,  1),   0, [(-410000,  -4080000), (590000,   -5080000), (2540000, -5080000)]),
        ((-4, -1),   0, [(-410000,  -6080000), (590000,   -5080000), (2540000, -5080000)]),
        ((-4,  1),  90, [(-1460000, -5130000), (-1410000, -5080000), (2540000, -5080000)]),
        ((-4, -1),  90, [(-1460000, -7130000), (590000,   -5080000), (2540000, -5080000)]),
        ((-4,  1), 180, [(-2510000, -4080000), (-1510000, -5080000), (2540000, -5080000)]),
        ((-4, -1), 180, [(-2510000, -6080000), (-1510000, -5080000), (2540000, -5080000)]),
        ((-4,  1), 270, [(-1460000, -3030000), (590000,   -5080000), (2540000, -5080000)]),
        ((-4, -1), 270, [(-1460000, -5030000), (-1410000, -5080000), (2540000, -5080000)]),
        (( 1, 10),   0, [(4590000,   4920000), (2540000,   2870000), (2540000, -5080000)]),
        ((-1, 10),   0, [(2590000,   4920000), (2540000,   4870000), (2540000, -5080000)]),
        (( 1, 10),  90, [(3540000,   3870000), (2540000,   2870000), (2540000, -5080000)]),
        ((-1, 10),  90, [(1540000,   3870000), (2540000,   2870000), (2540000, -5080000)]),
        (( 1, 10), 180, [(2490000,   4920000), (2540000,   4870000), (2540000, -5080000)]),
        ((-1, 10), 180, [(490000,    4920000), (2540000,   2870000), (2540000, -5080000)]),
        (( 1, 10), 270, [(3540000,   5970000), (2540000,   4970000), (2540000, -5080000)]),
        ((-1, 10), 270, [(1540000,   5970000), (2540000,   4970000), (2540000, -5080000)]),
        (( 4,  1),   0, [(7590000,  -4080000), (6590000,  -5080000), (2540000, -5080000)]),
        (( 4, -1),   0, [(7590000,  -6080000), (6590000,  -5080000), (2540000, -5080000)]),
        (( 4,  1),  90, [(6540000,  -5130000), (6490000,  -5080000), (2540000, -5080000)]),
        (( 4, -1),  90, [(6540000,  -7130000), (4490000,  -5080000), (2540000, -5080000)]),
        (( 4,  1), 180, [(5490000,  -4080000), (4490000,  -5080000), (2540000, -5080000)]),
        (( 4, -1), 180, [(5490000,  -6080000), (4490000,  -5080000), (2540000, -5080000)]),
        (( 4,  1), 270, [(6540000,  -3030000), (4490000,  -5080000), (2540000, -5080000)]),
        (( 4, -1), 270, [(6540000,  -5030000), (6490000,  -5080000), (2540000, -5080000)]),
        (( 1, -4),   0, [(4590000,  -9080000), (2540000,  -7030000), (2540000, -5080000)]),
        ((-1, -4),   0, [(2590000,  -9080000), (2540000,  -9030000), (2540000, -5080000)]),
        (( 1, -4),  90, [(3540000, -10130000), (2540000,  -9130000), (2540000, -5080000)]),
        ((-1, -4),  90, [(1540000, -10130000), (2540000,  -9130000), (2540000, -5080000)]),
        (( 1, -4), 180, [(2490000,  -9080000), (2540000,  -9030000), (2540000, -5080000)]),
        ((-1, -4), 180, [(490000,   -9080000), (2540000,  -7030000), (2540000, -5080000)]),
        (( 1, -4), 270, [(3540000,  -8030000), (2540000,  -7030000), (2540000, -5080000)]),
        ((-1, -4), 270, [(1540000,  -8030000), (2540000,  -7030000), (2540000, -5080000)]),
        # these positions used to be difficult for router but works after adding second
        # attempt with track posture changed, if the first try failed:
        ((5.5, 5),  90, [(8040000,  -1130000), (4090000,  -5080000), (2540000, -5080000)]),
        ((7, 10),   90, [(9540000,   3870000), (9540000,   1920000), (2540000, -5080000)]),
        # special cases testing some edge cases or special conditions:
        # cases to difficult for router. Two segment track would collide with footprint:
        ((-7, 10), 90, None),
        # fmt: on
    ],
)
@pytest.mark.parametrize("side", [Side.FRONT, Side.BACK])
def test_diode_switch_routing(position, orientation, side, expected, tmpdir, request):
    board, switch, diode = get_board_with_one_switch(request, "SW_Cherry_MX_PCB_1.00u")
    key_placer = KeyPlacer(board)

    switch_pad = switch.FindPadByNumber("2")
    switch_pad_position = switch_pad.GetPosition()

    diode_position = pcbnew.wxPoint(
        switch_pad_position.x + pcbnew.FromMM(position[0]),
        switch_pad_position.y + pcbnew.FromMM(position[1]),
    )
    set_position(diode, diode_position)
    set_side(diode, side)
    diode.SetOrientationDegrees(orientation)

    key_placer.route_switch_with_diode(switch, diode, 0)
    key_placer.remove_dangling_tracks()

    board.Save(f"{tmpdir}/keyboard-before.kicad_pcb")
    generate_render(tmpdir, request)
    assert_board_tracks(expected, board)


@pytest.mark.parametrize(
    "position,orientation,expected",
    [
        # fmt: off
        # simple cases when pads in line, expecting single segment track:
        ((0,  3.8),  0, [(1050000,  3800000), ( 5000000, 3800000)]),
        ((-8, 3.8),  0, [(-6950000, 3800000), (-5000000, 3800000)]),
        # fmt: on
    ],
)
def test_diode_switch_routing_complicated_footprint(
    position, orientation, expected, tmpdir, request
):
    board, switch, diode = get_board_with_one_switch(
        request, "Kailh_socket_PG1350_optional_reversible"
    )
    key_placer = KeyPlacer(board)

    set_position(diode, pcbnew.wxPointMM(*position))
    diode.SetOrientationDegrees(orientation)

    key_placer.route_switch_with_diode(switch, diode, 0)

    board.Save(f"{tmpdir}/keyboard-before.kicad_pcb")
    generate_render(tmpdir, request)
    assert_board_tracks(expected, board)


def get_2x2_layout(request):
    with open(f"{request.fspath.dirname}/../examples/2x2/kle-internal.json", "r") as f:
        text_input = f.read()
        return json.loads(text_input)


def add_2x2_nets(board):
    net_info = board.GetNetInfo()
    net_count = board.GetNetCount()
    for i, n in enumerate(["COL1", "COL2", "ROW1", "ROW2"]):
        net = pcbnew.NETINFO_ITEM(board, n, net_count + i)
        net_info.AppendNet(net)
        board.Add(net)
    return board.GetNetInfo().NetsByName()


def get_board_for_2x2_example(request):
    board = pcbnew.CreateEmptyBoard()
    netcodes_map = add_2x2_nets(board)
    for i in range(1, 5):
        switch = add_switch_footprint(board, request, i)
        switch.FindPadByNumber("1").SetNet(netcodes_map[f"COL{i % 2 + 1}"])
        diode = add_diode_footprint(board, request, i)
        diode.FindPadByNumber("2").SetNet(netcodes_map[f"ROW{i // 3 + 1}"])
    return board


def assert_2x2_layout_switches(board: pcbnew.BOARD, key_distance: Tuple[float, float]):
    switches = [get_footprint(board, f"SW{i}") for i in range(1, 5)]
    positions = [get_position(switch) for switch in switches]
    assert positions[0] == pcbnew.wxPointMM(25, 25) + pcbnew.wxPointMM(
        key_distance[0] / 2, key_distance[1] / 2
    )
    assert positions[1] - positions[0] == pcbnew.wxPointMM(key_distance[0], 0)
    assert positions[2] - positions[0] == pcbnew.wxPointMM(0, key_distance[1])
    assert positions[3] - positions[2] == pcbnew.wxPointMM(key_distance[0], 0)
    assert positions[3] - positions[1] == pcbnew.wxPointMM(0, key_distance[1])


@pytest.mark.parametrize(
    "key_distance",
    [
        (0, 0),
        (10, 10),
        (19, 19),
        (19.05, 19.05),
        (22.222, 22.222),
        (0, 10),
        (10, 0),
        (18, 17),
        (18, 19),
    ],
)
def test_switch_distance(key_distance, tmpdir, request):
    board = get_board_for_2x2_example(request)
    layout = get_2x2_layout(request)

    key_placer = KeyPlacer(board, key_distance)
    diode_position = DEFAULT_DIODE_POSITION
    key_placer.run(
        layout,
        "SW{}",
        ElementInfo("D{}", PositionOption.DEFAULT, diode_position, ""),
        True,
    )

    board.Save(f"{tmpdir}/keyboard-before.kicad_pcb")
    generate_render(tmpdir, request)

    assert_2x2_layout_switches(board, key_distance)
    switches = [get_footprint(board, f"SW{i}") for i in range(1, 5)]
    diodes = [get_footprint(board, f"D{i}") for i in range(1, 5)]
    for switch, diode in zip(switches, diodes):
        p = diode_position.relative_position
        assert get_position(diode) == get_position(switch) + pcbnew.wxPointMM(p.x, p.y)


def test_diode_placement_ignore(tmpdir, request):
    board = get_board_for_2x2_example(request)
    layout = get_2x2_layout(request)

    key_placer = KeyPlacer(board)

    diode_info = ElementInfo(
        "D{}", PositionOption.UNCHANGED, DEFAULT_DIODE_POSITION, ""
    )
    key_placer.run(layout, "SW{}", diode_info, True)

    board.Save(f"{tmpdir}/keyboard-before.kicad_pcb")
    generate_render(tmpdir, request)

    assert_2x2_layout_switches(board, (19.05, 19.05))
    diodes = [get_footprint(board, f"D{i}") for i in range(1, 5)]
    positions = [get_position(diode) for diode in diodes]
    for pos in positions:
        assert pos == pcbnew.wxPoint(0, 0)


def test_placer_invalid_layout(request):
    board = get_board_for_2x2_example(request)

    key_placer = KeyPlacer(board)
    diode_info = ElementInfo("D{}", PositionOption.DEFAULT, DEFAULT_DIODE_POSITION, "")

    with pytest.raises(RuntimeError):
        key_placer.run({"some": "urecognized layout format"}, "SW{}", diode_info, True)
