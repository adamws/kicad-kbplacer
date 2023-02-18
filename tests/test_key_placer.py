import logging
import pcbnew
import pytest

from .conftest import generate_render, get_footprints_dir

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


def add_diode_footprint(board, request):
    library = get_footprints_dir(request)
    f = pcbnew.FootprintLoad(str(library), "D_SOD-323")
    f.SetReference("D1")
    board.Add(f)
    return f


def add_switch_footprint(board, request):
    library = get_footprints_dir(request)
    sw = pcbnew.FootprintLoad(str(library), "SW_Cherry_MX_PCB_1.00u")
    sw.SetReference("SW1")
    board.Add(sw)
    return sw


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
    switch = add_switch_footprint(board, request)
    diode = add_diode_footprint(board, request)

    keyPlacer = KeyPlacer(logger, board, None)

    keyPlacer.SetPosition(switch, pcbnew.wxPoint(0, 0))
    switchPadPosition = switch.FindPadByNumber("2").GetPosition()

    diodePosition = pcbnew.wxPoint(
        switchPadPosition.x + pcbnew.FromMM(position[0]),
        switchPadPosition.y + pcbnew.FromMM(position[1]),
    )
    keyPlacer.SetPosition(diode, diodePosition)
    keyPlacer.SetSide(diode, side)
    diode.SetOrientationDegrees(orientation)

    keyPlacer.RouteSwitchWithDiode(switch, diode, 0)
    keyPlacer.RemoveDanglingTracks()

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
