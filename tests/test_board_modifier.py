import enum
import logging

import pcbnew
import pytest

from .conftest import (
    KICAD_VERSION,
    add_track,
    generate_render,
    get_footprints_dir,
    pointMM,
    update_netinfo,
)

try:
    from kbplacer.board_modifier import (
        BoardModifier,
        set_position_by_points,
        set_side,
    )
    from kbplacer.element_position import Side
except:
    pass


logger = logging.getLogger(__name__)


class TrackToElementPosition(enum.Enum):
    APART = 1
    STARTS_AT = 2
    GOES_THROUGH = 3


class TrackSide(enum.Enum):
    SAME = 1
    OPPOSITE = 2


def add_diode_footprint(board, footprint, request):
    library = get_footprints_dir(request)
    f = pcbnew.FootprintLoad(str(library), footprint)
    f.SetReference("D1")
    board.Add(f)
    return f


def add_nets(board, netnames):
    net_count = board.GetNetCount()
    for i, n in enumerate(netnames):
        net = pcbnew.NETINFO_ITEM(board, n, net_count + i)
        update_netinfo(board, net)
        board.Add(net)


def __get_parameters():
    examples = ["D_SOD-323", "D_DO-34_SOD68_P7.62mm_Horizontal"]
    positions = list(TrackToElementPosition)
    sides = list(TrackSide)
    netlists = [("", ""), ("", "n1"), ("n1", ""), ("n1", "n1"), ("n1", "n2")]
    test_params = []
    for example in examples:
        for position in positions:
            for side in sides:
                for netlist in netlists:
                    param = pytest.param(example, position, side, netlist)
                    test_params.append(param)
    return test_params


@pytest.mark.parametrize("footprint,position,side,netlist", __get_parameters())
def test_track_with_pad_collision(footprint, position, side, netlist, tmpdir, request):
    board = pcbnew.CreateEmptyBoard()
    netnames = [n for n in netlist if n != ""]
    add_nets(board, netnames)

    logger.info("Board nets:")
    netcodes_map = board.GetNetInfo().NetsByName()
    for v in netcodes_map.itervalues():
        logger.info(f"Net: {v.GetNetCode()}:{v.GetNetname()}")

    diode = add_diode_footprint(board, footprint, request)
    pad = diode.FindPadByNumber("2")
    pad_netlist = netlist[0]
    if pad_netlist:
        pad.SetNet(netcodes_map[pad_netlist])

    modifier = BoardModifier(board)
    set_position_by_points(diode, 0, 0)
    set_side(diode, Side.BACK)

    pad_position = pad.GetPosition()
    if KICAD_VERSION >= (7, 0, 0):
        pad_position = pcbnew.wxPoint(pad_position.x, pad_position.y)

    # create track to test
    if position == TrackToElementPosition.APART:
        start = pad_position.__add__(pcbnew.wxPoint(pad.GetSizeX() / 2, 0))
        start = start.__add__(pcbnew.wxPoint(pcbnew.FromMM(0.5), 0))
    elif position == TrackToElementPosition.STARTS_AT:
        start = pad_position
    elif position == TrackToElementPosition.GOES_THROUGH:
        start = pad_position.__sub__(pcbnew.wxPoint(pad.GetSizeX() / 2, 0))
        start = start.__sub__(pcbnew.wxPoint(pcbnew.FromMM(0.5), 0))
    else:
        assert False, "Unexpected position option"

    end = start.__add__(pcbnew.wxPoint(pcbnew.FromMM(5), 0))

    if side == TrackSide.SAME:
        layer = pcbnew.B_Cu
    elif side == TrackSide.OPPOSITE:
        layer = pcbnew.F_Cu
    else:
        assert False, "Unexpected side option"

    track = add_track(board, start, end, layer)
    track_netlist = netlist[1]
    if track_netlist:
        track.SetNet(netcodes_map[track_netlist])

    if not pad.IsOnLayer(track.GetLayer()) or position == TrackToElementPosition.APART:
        expected_collision_result = False
    elif track_netlist and track_netlist == pad_netlist:
        # same non '0' netlist never colide
        expected_collision_result = False
    elif track_netlist == "" and position == TrackToElementPosition.STARTS_AT:
        expected_collision_result = False
    else:
        expected_collision_result = True

    pad_netlist_str = pad_netlist if pad_netlist else "''"
    track_netlist_str = track_netlist if track_netlist else "''"
    logger.info(f"Pad net: {pad_netlist_str}, track net: {track_netlist_str}")
    if expected_collision_result:
        logger.info("Expecting collision")
    else:
        logger.info("Expecting no collision")

    collide = modifier.test_track_collision(track)

    board.Add(track)
    board.BuildListOfNets()
    board.Save(f"{tmpdir}/keyboard-before.kicad_pcb")
    generate_render(tmpdir, request)

    assert collide == expected_collision_result, "Unexpected track collision result"


def add_track_segments_test(steps, tmpdir, request):
    board = pcbnew.CreateEmptyBoard()
    f = add_diode_footprint(board, "D_SOD-323", request)

    modifier = BoardModifier(board)
    # place footprint
    set_position_by_points(f, 0, 0)
    set_side(f, Side.BACK)

    start = f.FindPadByNumber("2").GetPosition()
    for step in steps:
        direction, should_succeed = step
        start = modifier.add_track_segment(start, direction)
        if should_succeed:
            assert type(start) != type(None), "Unexpected track add failure"
        else:
            assert type(start) == type(None), "Unexpected track success"

    board.Save(f"{tmpdir}/keyboard-before.kicad_pcb")
    generate_render(tmpdir, request)


def test_track_with_track_collision_close_to_footprint(tmpdir, request):
    steps = []
    # adding track which starts at pad but is so short it barely
    # reaches out of it meaning that next track starting there might
    # be incorrectly detected as colliding with pad
    steps.append((pcbnew.wxPoint(-pcbnew.FromMM(0.4), 0), True))
    steps.append((pcbnew.wxPoint(0, pcbnew.FromMM(1)), True))
    add_track_segments_test(steps, tmpdir, request)


def test_track_with_track_collision_close_to_footprints_one_good_one_bad(
    tmpdir, request
):
    steps = []
    # same as 'test_track_with_track_collision_close_to_footprint' but second segment
    # instead going down (where there is nothing to collide with), it goes to left and
    # reaches second pad of diode which should be detected as collision,
    # hence segment should not be added
    steps.append((pcbnew.wxPoint(-pcbnew.FromMM(0.4), 0), True))
    steps.append((pcbnew.wxPoint(-pcbnew.FromMM(5), 0), False))
    add_track_segments_test(steps, tmpdir, request)


def test_track_with_track_collision_close_to_footprint_many_small_tracks(
    tmpdir, request
):
    steps = []
    # kind of ridiculous example but all tracks here should succeed, such
    # scenario should never happen under normal circumstances
    steps.append((pcbnew.wxPoint(-pcbnew.FromMM(0.4), 0), True))
    steps.append((pcbnew.wxPoint(0, -pcbnew.FromMM(0.4)), True))
    steps.append((pcbnew.wxPoint(pcbnew.FromMM(0.4), 0), True))
    steps.append((pcbnew.wxPoint(0, pcbnew.FromMM(0.4)), True))
    add_track_segments_test(steps, tmpdir, request)


@pytest.mark.parametrize(
    "start,end,layer,expected",
    [
        (pointMM(0, 0), pointMM(4, 0), pcbnew.B_Cu, True),
        (pointMM(0, 0), pointMM(4, 0), pcbnew.F_Cu, False),
        (pointMM(2, -2), pointMM(4, -2), pcbnew.B_Cu, False),
        (pointMM(2, 2), pointMM(4, 2), pcbnew.B_Cu, False),
    ],
)
def test_track_with_track_collision(start, end, layer, expected, tmpdir, request):
    board = pcbnew.CreateEmptyBoard()

    modifier = BoardModifier(board)
    add_track(board, pointMM(2, -2), pointMM(2, 2), pcbnew.B_Cu)

    # add track to test:
    track = add_track(board, start, end, layer)

    collide = modifier.test_track_collision(track)

    board.Save(f"{tmpdir}/keyboard-before.kicad_pcb")
    generate_render(tmpdir, request)
    assert collide == expected, "Unexpected track collision result"
