# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import logging
from typing import List, Tuple
from unittest.mock import MagicMock, patch

import pcbnew
import pytest

from kbplacer.board_modifier import set_position
from kbplacer.edge_generator import build_board_outline, convex_hull

from .conftest import KICAD_VERSION, add_switch_footprint, add_track, save_and_render

logger = logging.getLogger(__name__)

KEY_DISTANCE = 20


def get_board_with_switch_array(
    request, count: int = 1
) -> Tuple[pcbnew.BOARD, List[pcbnew.FOOTPRINT]]:
    board = pcbnew.CreateEmptyBoard()

    position = pcbnew.VECTOR2I_MM(0, 0)
    switches = []
    for i in range(count):
        switch = add_switch_footprint(board, request, i + 1)

        position = position + pcbnew.VECTOR2I_MM(KEY_DISTANCE, 0)
        set_position(switch, position)

        switches.append(switch)

    return board, switches


def test_edge_generator_around_switches(request, tmpdir) -> None:
    board, switches = get_board_with_switch_array(request, count=5)

    area = board.GetBoardEdgesBoundingBox().GetArea()
    assert area == 0

    build_board_outline(board, 0, "SW{}")

    bbox = board.GetBoardEdgesBoundingBox()
    assert bbox.GetArea() != 0
    for s in switches:
        assert bbox.Contains(s.GetPosition())

    save_and_render(board, tmpdir, request)


@pytest.mark.skipif(
    KICAD_VERSION < (7, 0, 0), reason="GetCurrentSelection API not available"
)
@patch("pcbnew.GetCurrentSelection")
def test_edge_generator_around_selection(
    mock_selection: MagicMock, request, tmpdir
) -> None:
    board, switches = get_board_with_switch_array(request, count=5)

    area = board.GetBoardEdgesBoundingBox().GetArea()
    assert area == 0

    bounded = switches[0:2]
    not_bounded = switches[2:]
    mock_selection.return_value = bounded

    build_board_outline(board, 0, "SW{}")

    bbox = board.GetBoardEdgesBoundingBox()
    assert bbox.GetArea() != 0
    for s in bounded:
        assert bbox.Contains(s.GetPosition())
    for s in not_bounded:
        assert not bbox.Contains(s.GetPosition())

    save_and_render(board, tmpdir, request)


@pytest.mark.skipif(
    KICAD_VERSION < (7, 0, 0), reason="GetCurrentSelection API not available"
)
@patch("pcbnew.GetCurrentSelection")
def test_edge_generator_around_invalid_selection(
    mock_selection: MagicMock, request
) -> None:
    board, _ = get_board_with_switch_array(request, count=5)

    track = add_track(
        board, pcbnew.VECTOR2I_MM(0, 0), pcbnew.VECTOR2I_MM(10, 10), pcbnew.F_Cu
    )
    mock_selection.return_value = [track]

    # selection of wrong type and nothing match defined annotation, should raise exception
    with pytest.raises(Exception, match="Footprints for generating board edge not set"):
        build_board_outline(board, 0, "D{}")


def test_edge_generator_around_empty_list(request) -> None:
    board, _ = get_board_with_switch_array(request, count=5)

    # nothing selected and nothing match defined annotation, should raise exception
    with pytest.raises(Exception, match="Footprints for generating board edge not set"):
        build_board_outline(board, 0, "D{}")


class TestConvexHull:
    def test_empty_input(self):
        assert convex_hull([]) == []

    def test_single_point(self):
        assert convex_hull([(1, 1)]) == [(1, 1)]

    def test_duplicate_points(self):
        assert convex_hull([(1, 1), (1, 1), (1, 1)]) == [(1, 1)]

    def test_two_points(self):
        assert convex_hull([(0, 0), (1, 1)]) == [(0, 0), (1, 1)]

    def test_three_points_triangle(self):
        points = [(0, 0), (1, 1), (1, 0)]
        expected = [(0, 0), (1, 0), (1, 1)]
        assert convex_hull(points) == expected

    def test_square(self):
        points = [(0, 0), (1, 0), (1, 1), (0, 1)]
        expected = [(0, 0), (1, 0), (1, 1), (0, 1)]
        assert convex_hull(points) == expected

    def test_collinear_points(self):
        points = [(0, 0), (1, 1), (2, 2), (3, 3)]
        expected = [(0, 0), (3, 3)]
        assert convex_hull(points) == expected

    def test_complex_shape(self):
        points = [(0, 3), (1, 1), (2, 2), (4, 4), (0, 0), (1, 2), (3, 1), (3, 3)]
        expected = [(0, 0), (3, 1), (4, 4), (0, 3)]
        assert convex_hull(points) == expected

    def test_concave_shape(self):
        points = [(0, 0), (2, 0), (2, 2), (0, 2), (1, 1)]
        expected = [(0, 0), (2, 0), (2, 2), (0, 2)]
        assert convex_hull(points) == expected

    def test_points_with_negative_coords(self):
        points = [(-1, -1), (-2, -3), (4, 5), (3, 1), (-3, 0)]
        expected = [(-3, 0), (-2, -3), (3, 1), (4, 5)]
        assert convex_hull(points) == expected
