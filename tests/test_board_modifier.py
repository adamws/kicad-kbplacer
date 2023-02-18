import logging
import pcbnew
import pytest

from .conftest import generate_render, get_footprints_dir

try:
    from kbplacer.board_modifier import BoardModifier, Side
except:
    pass


logger = logging.getLogger(__name__)


def add_diode_footprint(board, footprint, request):
    library = get_footprints_dir(request)
    f = pcbnew.FootprintLoad(str(library), footprint)
    f.SetReference("D1")
    board.Add(f)
    return f


def add_track(board, start, end, layer):
    track = pcbnew.PCB_TRACK(board)
    track.SetWidth(pcbnew.FromMM(0.25))
    track.SetLayer(layer)
    track.SetStart(start)
    track.SetEnd(end)
    board.Add(track)
    return track


def pointMM(x, y):
    return pcbnew.wxPoint(pcbnew.FromMM(x), pcbnew.FromMM(y))


@pytest.mark.parametrize(
    "footprint,start,end,layer,expected",
    [
        ("D_SOD-323", pointMM(2, 0), pointMM(5, 0), pcbnew.B_Cu, False),
        ("D_SOD-323", pointMM(0, 0), pointMM(5, 0), pcbnew.B_Cu, True),
        ("D_SOD-323", pointMM(1, 0), pointMM(5, 0), pcbnew.B_Cu, False),
        ("D_SOD-323", pointMM(0, 0), pointMM(5, 0), pcbnew.F_Cu, False),
        (
            "D_DO-34_SOD68_P7.62mm_Horizontal",
            pointMM(2, 0),
            pointMM(9, 0),
            pcbnew.B_Cu,
            True,
        ),
        (
            "D_DO-34_SOD68_P7.62mm_Horizontal",
            pointMM(2, 0),
            pointMM(9, 0),
            pcbnew.F_Cu,
            True,
        ),
    ],
)
def test_track_with_footprint_collision(
    footprint, start, end, layer, expected, tmpdir, request
):
    board = pcbnew.CreateEmptyBoard()
    f = add_diode_footprint(board, footprint, request)

    modifier = BoardModifier(logger, board)
    f = modifier.GetFootprint("D1")

    # place footprint
    modifier.SetPositionByPoints(f, 0, 0)
    modifier.SetSide(f, Side.BACK)

    # create track to test
    track = add_track(board, start, end, layer)

    collide = modifier.TestTrackCollision(track)

    board.Add(track)
    board.Save("{}/keyboard-before.kicad_pcb".format(tmpdir))
    generate_render(tmpdir, request)

    assert collide == expected, "Unexpected track collision result"


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

    modifier = BoardModifier(logger, board)
    add_track(board, pointMM(2, -2), pointMM(2, 2), pcbnew.B_Cu)

    # add track to test:
    track = add_track(board, start, end, layer)

    collide = modifier.TestTrackCollision(track)

    board.Save("{}/keyboard-before.kicad_pcb".format(tmpdir))
    generate_render(tmpdir, request)
    assert collide == expected, "Unexpected track collision result"
