import enum
import logging
from typing import List, Tuple

import pcbnew
import pytest

from kbplacer.board_modifier import (
    BoardModifier,
    get_footprint,
    get_optional_footprint,
    set_position_by_points,
    set_side,
)
from kbplacer.element_position import Side

from .conftest import (
    KICAD_VERSION,
    add_track,
    generate_render,
    get_footprints_dir,
    pointMM,
    prepare_project_file,
    update_netinfo,
)

logger = logging.getLogger(__name__)


class TrackToElementPosition(enum.Enum):
    APART = 1
    STARTS_AT = 2
    GOES_THROUGH = 3


class TrackSide(enum.Enum):
    SAME = 1
    OPPOSITE = 2


def add_diode_footprint(board, footprint, request, reference: str = "D1"):
    library = get_footprints_dir(request)
    f = pcbnew.FootprintLoad(str(library), footprint)
    f.SetReference(reference)
    board.Add(f)
    return f


def add_nets(board, netnames) -> None:
    net_count = board.GetNetCount()
    for i, n in enumerate(netnames):
        net = pcbnew.NETINFO_ITEM(board, n, net_count + i)
        update_netinfo(board, net)
        board.Add(net)


def save_and_render(board: pcbnew.BOARD, tmpdir, request) -> None:
    pcb_path = f"{tmpdir}/test.kicad_pcb"
    board.Save(pcb_path)
    generate_render(request, pcb_path)


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
def test_track_with_pad_collision(
    footprint, position, side, netlist, tmpdir, request
) -> None:
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
    if KICAD_VERSION < (7, 0, 0):
        pad_position = pcbnew.VECTOR2I(pad_position)

    # create track to test
    if position == TrackToElementPosition.APART:
        start = pad_position + pcbnew.VECTOR2I(pad.GetSizeX() // 2, 0)
        start = start + pcbnew.VECTOR2I_MM(0.5, 0)
    elif position == TrackToElementPosition.STARTS_AT:
        start = pad_position
    elif position == TrackToElementPosition.GOES_THROUGH:
        start = pad_position - pcbnew.VECTOR2I(pad.GetSizeX() // 2, 0)
        start = start - pcbnew.VECTOR2I_MM(0.5, 0)
    else:
        assert False, "Unexpected position option"

    end = start + pcbnew.VECTOR2I_MM(5, 0)

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
    save_and_render(board, tmpdir, request)

    assert collide == expected_collision_result, "Unexpected track collision result"


def add_track_segments_test(
    steps: List[Tuple[pcbnew.VECTOR2I, bool]], tmpdir, request
) -> None:
    board = pcbnew.CreateEmptyBoard()
    f = add_diode_footprint(board, "D_SOD-323", request)

    modifier = BoardModifier(board)
    # place footprint
    set_position_by_points(f, 0, 0)
    set_side(f, Side.BACK)

    start = f.FindPadByNumber("2").GetPosition()

    for step in steps:
        direction, should_succeed = step
        assert start
        if KICAD_VERSION < (7, 0, 0):
            start = pcbnew.VECTOR2I(start)
        end = start + pcbnew.VECTOR2I(*direction)
        start = modifier.add_track_segment_by_points(start, end)
        if should_succeed:
            assert type(start) != type(None), "Unexpected track add failure"
        else:
            assert type(start) == type(None), "Unexpected track success"

    save_and_render(board, tmpdir, request)


def test_track_with_track_collision_close_to_footprint(tmpdir, request) -> None:
    steps = []
    # adding track which starts at pad but is so short it barely
    # reaches out of it meaning that next track starting there might
    # be incorrectly detected as colliding with pad
    steps.append((pcbnew.VECTOR2I_MM(-0.4, 0), True))
    steps.append((pcbnew.VECTOR2I_MM(0, 1), True))
    add_track_segments_test(steps, tmpdir, request)


def test_track_with_track_collision_close_to_footprints_one_good_one_bad(
    tmpdir, request
) -> None:
    steps = []
    # same as 'test_track_with_track_collision_close_to_footprint' but second segment
    # instead going down (where there is nothing to collide with), it goes to left and
    # reaches second pad of diode which should be detected as collision,
    # hence segment should not be added
    steps.append((pcbnew.VECTOR2I_MM(-0.4, 0), True))
    steps.append((pcbnew.VECTOR2I_MM(-5, 0), False))
    add_track_segments_test(steps, tmpdir, request)


def test_track_with_track_collision_close_to_footprint_many_small_tracks(
    tmpdir, request
) -> None:
    steps = []
    # kind of ridiculous example but all tracks here should succeed, such
    # scenario should never happen under normal circumstances
    steps.append((pcbnew.VECTOR2I_MM(-0.4, 0), True))
    steps.append((pcbnew.VECTOR2I_MM(0, -0.4), True))
    steps.append((pcbnew.VECTOR2I_MM(0.4, 0), True))
    steps.append((pcbnew.VECTOR2I_MM(0, 0.4), True))
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
def test_track_with_track_collision(
    start, end, layer, expected, tmpdir, request
) -> None:
    board = pcbnew.CreateEmptyBoard()

    modifier = BoardModifier(board)
    add_track(board, pointMM(2, -2), pointMM(2, 2), pcbnew.B_Cu)

    # add track to test:
    track = add_track(board, start, end, layer)

    collide = modifier.test_track_collision(track)

    save_and_render(board, tmpdir, request)
    assert collide == expected, "Unexpected track collision result"


def test_track_use_netclass_settings(tmpdir, request) -> None:
    pcb_path = f"{tmpdir}/test.kicad_pcb"

    prepare_project_file(request, pcb_path)
    board = pcbnew.NewBoard(pcb_path)

    netclasses = board.GetNetClasses()
    # must be defined in used project file:
    custom_netclasses = ["Custom1", "Custom2"]

    netnames = ["n1", "n2"]
    add_nets(board, netnames)

    netcodes_map = board.GetNetInfo().NetsByName()

    footprint = "D_SOD-323"
    for i in range(2):
        diode = add_diode_footprint(board, footprint, request, f"D{i + 1}")
        for j in range(2):
            pad = diode.FindPadByNumber(f"{j + 1}")
            pad_netlist = netnames[j]
            net = netcodes_map[pad_netlist]
            if KICAD_VERSION < (7, 0, 0):
                net.SetNetClass(netclasses.Find(custom_netclasses[j]))
            else:
                net.SetNetClass(netclasses[custom_netclasses[j]])
            pad.SetNet(net)
        if KICAD_VERSION < (7, 0, 0):
            diode.Move(pcbnew.wxPointMM(0, i * 5))
        else:
            diode.Move(pcbnew.VECTOR2I_MM(0, i * 5))

    d1 = get_footprint(board, "D1")
    d2 = get_footprint(board, "D2")

    modifier = BoardModifier(board)
    for i in range(2):
        modifier.route(d1.FindPadByNumber(f"{i + 1}"), d2.FindPadByNumber(f"{i + 1}"))

    save_and_render(board, tmpdir, request)

    tracks = board.GetTracks()
    assert len(tracks) == 2
    tracks.sort(key=lambda t: t.GetPosition()[0])
    assert tracks[0].GetWidth() == pcbnew.FromMM(0.2)
    assert tracks[1].GetWidth() == pcbnew.FromMM(0.4)


def test_find_footprint_raises_when_not_found() -> None:
    board = pcbnew.CreateEmptyBoard()
    with pytest.raises(RuntimeError, match=r"Cannot find footprint SW1"):
        get_footprint(board, "SW1")


def test_find_optional_footprint_return_none_when_not_found() -> None:
    board = pcbnew.CreateEmptyBoard()
    assert get_optional_footprint(board, "SW1") is None
