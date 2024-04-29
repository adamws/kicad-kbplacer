import pcbnew
import pytest

from kbplacer.board_modifier import (
    get_orientation,
    get_position,
    get_side,
    set_position,
    set_rotation,
    set_side,
)
from kbplacer.element_position import Side
from kbplacer.template_copier import copy_from_template_to_board

from .conftest import add_switch_footprint, add_track, generate_render

TRACK_START = pcbnew.wxPointMM(0, 5)
TRACK_END = pcbnew.wxPointMM(19.05, 5)


def prepare_source_board(tmpdir, request) -> str:
    source_board_path = f"{tmpdir}/source.kicad_pcb"
    source_board = pcbnew.CreateEmptyBoard()

    for i in range(0, 2):
        sw = add_switch_footprint(source_board, request, i)
        set_position(sw, pcbnew.wxPointMM(i * 19.05, 0))
        set_rotation(sw, 45 * i)

    add_track(source_board, TRACK_START, TRACK_END, pcbnew.B_Cu)

    source_board.Save(source_board_path)
    return source_board_path


def prepare_target_board(request):
    target_board = pcbnew.CreateEmptyBoard()
    footprints = []
    for i in range(0, 2):
        sw = add_switch_footprint(target_board, request, i)
        assert get_position(sw) == pcbnew.wxPoint(0, 0)
        footprints.append(sw)

    # change side of one footprint and rotate the other
    # to test if template copier properly handle it
    set_side(footprints[0], Side.BACK)
    set_rotation(footprints[1], 30)

    return target_board, footprints


@pytest.mark.parametrize("copy_tracks", [True, False])
def test_template_copy(copy_tracks, tmpdir, request) -> None:
    source_board_path = prepare_source_board(tmpdir, request)
    target_board, footprints = prepare_target_board(request)

    generate_render(request, source_board_path)

    copy_from_template_to_board(target_board, source_board_path, copy_tracks)

    pcb_path = f"{tmpdir}/test.kicad_pcb"
    target_board.Save(pcb_path)
    generate_render(request, pcb_path)

    for i, f in enumerate(footprints):
        assert get_position(f) == pcbnew.wxPointMM(i * 19.05, 0)
        assert get_side(f) == Side.FRONT
        assert get_orientation(f) == 45 * i
    expected_tracks_count = 1 if copy_tracks else 0
    assert len(target_board.GetTracks()) == expected_tracks_count
    if expected_tracks_count:
        t = target_board.GetTracks()[0]
        assert t.GetStart() == TRACK_START
        assert t.GetEnd() == TRACK_END
