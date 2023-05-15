import json
import logging
import pcbnew
import pytest

from .conftest import generate_render, add_switch_footprint, add_diode_footprint

try:
    from kbplacer.key_placer import KeyPlacer
    from kbplacer.board_modifier import Side
except:
    # satisfy import issues when running examples tests
    # in docker image on CI.
    # these tests should not be executed but pytest
    # would fail to collect test information without that:
    from enum import Flag

    class Side(Flag):
        FRONT = False
        BACK = True


logger = logging.getLogger(__name__)


def equal_ignore_order(a, b):
    unmatched = list(b)
    for element in a:
        try:
            unmatched.remove(element)
        except ValueError:
            return False
    return not unmatched


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
        # special cases testing some edge cases or special conditions:
        # this position should be possible to route but resulting corner is to close to pad
        ((5.5, 5), 90, None),
        # cases to difficult for router. Two segment track would collide with footprint:
        ((-7, 10), 90, None),
        ((7, 10), 90, None),
        # fmt: on
    ],
)
@pytest.mark.parametrize("side", [Side.FRONT, Side.BACK])
def test_diode_switch_routing(position, orientation, side, expected, tmpdir, request):
    if expected:
        expected = [pcbnew.wxPoint(x[0], x[1]) for x in expected]
    board = pcbnew.CreateEmptyBoard()
    switch = add_switch_footprint(board, request, 1)
    diode = add_diode_footprint(board, request, 1)

    key_placer = KeyPlacer(logger, board, None)

    key_placer.set_position(switch, pcbnew.wxPoint(0, 0))
    switch_pad_position = switch.FindPadByNumber("2").GetPosition()

    diode_position = pcbnew.wxPoint(
        switch_pad_position.x + pcbnew.FromMM(position[0]),
        switch_pad_position.y + pcbnew.FromMM(position[1]),
    )
    key_placer.set_position(diode, diode_position)
    key_placer.set_side(diode, side)
    diode.SetOrientationDegrees(orientation)

    key_placer.route_switch_with_diode(switch, diode, 0)
    key_placer.remove_dangling_tracks()

    board.Save("{}/keyboard-before.kicad_pcb".format(tmpdir))
    generate_render(tmpdir, request)

    points = []
    for track in board.GetTracks():
        start = track.GetStart()
        if start not in points:
            points.append(start)
        end = track.GetEnd()
        if end not in points:
            points.append(end)

    if expected == None:
        assert len(points) == 0
    else:
        assert equal_ignore_order(points, expected)


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


def assert_2x2_layout_switches(key_placer, key_distance):
    switches = [key_placer.get_footprint(f"SW{i}") for i in range(1, 5)]
    positions = [key_placer.get_position(switch) for switch in switches]
    assert positions[0] == pcbnew.wxPointMM(25, 25) + pcbnew.wxPointMM(
        key_distance / 2, key_distance / 2
    )
    assert positions[1] - positions[0] == pcbnew.wxPointMM(key_distance, 0)
    assert positions[2] - positions[0] == pcbnew.wxPointMM(0, key_distance)
    assert positions[3] - positions[2] == pcbnew.wxPointMM(key_distance, 0)
    assert positions[3] - positions[1] == pcbnew.wxPointMM(0, key_distance)


@pytest.mark.parametrize("key_distance", [0, 10, 19, 19.05, 22.222])
def test_switch_distance(key_distance, tmpdir, request):
    board = get_board_for_2x2_example(request)
    layout = get_2x2_layout(request)

    key_placer = KeyPlacer(logger, board, layout, key_distance)
    diode_position = key_placer.get_default_diode_position()
    key_placer.run("SW{}", "", "D{}", diode_position, True)

    board.Save("{}/keyboard-before.kicad_pcb".format(tmpdir))
    generate_render(tmpdir, request)

    assert_2x2_layout_switches(key_placer, key_distance)
    switches = [key_placer.get_footprint(f"SW{i}") for i in range(1, 5)]
    diodes = [key_placer.get_footprint(f"D{i}") for i in range(1, 5)]
    for switch, diode in zip(switches, diodes):
        p = diode_position.relative_position
        assert key_placer.get_position(diode) == key_placer.get_position(
            switch
        ) + pcbnew.wxPointMM(p.x, p.y)


def test_diode_placement_ignore(tmpdir, request):
    board = get_board_for_2x2_example(request)
    layout = get_2x2_layout(request)

    key_placer = KeyPlacer(logger, board, layout)
    key_placer.run("SW{}", "", "D{}", None, True)

    board.Save("{}/keyboard-before.kicad_pcb".format(tmpdir))
    generate_render(tmpdir, request)

    assert_2x2_layout_switches(key_placer, 19.05)
    diodes = [key_placer.get_footprint(f"D{i}") for i in range(1, 5)]
    positions = [key_placer.get_position(diode) for diode in diodes]
    for pos in positions:
        assert pos == pcbnew.wxPoint(0, 0)
