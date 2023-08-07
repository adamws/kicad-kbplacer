import logging

import pcbnew
import pytest

from .conftest import add_switch_footprint, add_track, generate_render

try:
    from kbplacer.board_modifier import get_position, set_position
    from kbplacer.template_copier import TemplateCopier
except:
    pass


logger = logging.getLogger(__name__)


TRACK_START = pcbnew.wxPointMM(0, 5)
TRACK_END = pcbnew.wxPointMM(19.05, 5)


def prepare_source_board(tmpdir, request) -> str:
    source_board_path = f"{tmpdir}/source.kicad_pcb"
    source_board = pcbnew.CreateEmptyBoard()

    for i in range(0, 2):
        sw = add_switch_footprint(source_board, request, i)
        set_position(sw, pcbnew.wxPointMM(i * 19.05, 0))

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

    return target_board, footprints


@pytest.mark.parametrize("copy_tracks", [True, False])
def test_template_copy(copy_tracks, tmpdir, request):
    source_board_path = prepare_source_board(tmpdir, request)
    target_board, footprints = prepare_target_board(request)

    TemplateCopier(logger, target_board, source_board_path, copy_tracks).run()

    target_board.Save(f"{tmpdir}/keyboard-before.kicad_pcb")
    generate_render(tmpdir, request)

    for i, f in enumerate(footprints):
        assert get_position(f) == pcbnew.wxPointMM(i * 19.05, 0)
    expected_tracks_count = 1 if copy_tracks else 0
    assert len(target_board.GetTracks()) == expected_tracks_count
    if expected_tracks_count:
        t = target_board.GetTracks()[0]
        assert t.GetStart() == TRACK_START
        assert t.GetEnd() == TRACK_END
