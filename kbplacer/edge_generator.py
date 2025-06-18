# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import logging
import re
import sys
from typing import List, cast

import pcbnew

from .board_modifier import KICAD_VERSION

logger = logging.getLogger(__name__)


def convex_hull(points):
    """Computes the convex hull of a set of 2D points.

    Input: an iterable sequence of (x, y) pairs representing the points.
    Output: a list of vertices of the convex hull in counter-clockwise order,
      starting from the vertex with the lexicographically smallest coordinates.
    Implements Andrew's monotone chain algorithm. O(n log n) complexity.

    Source: https://algorithmist.com/wiki/Monotone_chain_convex_hull.py
    """

    # Sort the points lexicographically (tuples are compared lexicographically).
    # Remove duplicates to detect the case we have just one unique point.
    points = sorted(set(points))

    # Boring case: no points or a single point, possibly repeated multiple times.
    if len(points) <= 1:
        return points

    # 2D cross product of OA and OB vectors, i.e. z-component of their 3D cross product.
    # Returns a positive value, if OAB makes a counter-clockwise turn,
    # negative for clockwise turn, and zero if the points are collinear.
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    # Build lower hull
    lower = []
    for p in points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    # Build upper hull
    upper = []
    for p in reversed(points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    # Concatenation of the lower and upper hulls gives the convex hull.
    # Last point of each list is omitted because it is repeated
    # at the beginning of the other list.
    return lower[:-1] + upper[:-1]


def build_board_outline_around_footprints(
    board: pcbnew.BOARD, outline_delta: float, footprints: List[pcbnew.FOOTPRINT]
) -> None:
    if not footprints:
        msg = "Footprints for generating board edge not set"
        raise Exception(msg)

    hulls = [f.GetBoundingHull() for f in footprints]
    points = []
    for hull in hulls:
        for i in range(0, hull.OutlineCount()):
            for p in hull.Outline(i).CPoints():
                points.append((p.x, p.y))
    result = convex_hull(points)
    shape_line = pcbnew.SHAPE_LINE_CHAIN()
    for r in result:
        shape_line.Append(r[0], r[1])

    # Only this combination of platform and version triggers error pop-up about
    # outline not being closed (assert failed).
    # Checked with `test_board_outline_building` and values
    # are the same on all platforms. This should be false-positive since boards
    # with outline generated with this method can be successfully rendered
    # with KiCad's 3d viewer. Calling `SetClosed` makes pop-up go away.
    if KICAD_VERSION >= (9, 0, 0) and sys.platform == "win32":
        shape_line.SetClosed(True)

    outline = pcbnew.SHAPE_POLY_SET()
    outline.AddOutline(shape_line)

    def _inflate_outline(outline, delta_mm):
        if KICAD_VERSION < (8, 0, 0):
            outline.Inflate(delta_mm, 10, pcbnew.SHAPE_POLY_SET.CHAMFER_ALL_CORNERS)
        else:
            outline.Inflate(delta_mm, pcbnew.CORNER_STRATEGY_CHAMFER_ALL_CORNERS, 0)

    def _deflate_outline(outline, delta_mm):
        if KICAD_VERSION < (8, 0, 0):
            outline.Deflate(delta_mm, 10, pcbnew.SHAPE_POLY_SET.CHAMFER_ALL_CORNERS)
        else:
            outline.Deflate(delta_mm, pcbnew.CORNER_STRATEGY_CHAMFER_ALL_CORNERS, 0)

    delta_mm = cast(int, pcbnew.FromMM(abs(outline_delta)))
    if outline_delta > 0:
        _inflate_outline(outline, delta_mm)
    elif outline_delta < 0:
        _deflate_outline(outline, delta_mm)

    points = []
    for i in range(0, outline.OutlineCount()):
        for p in outline.Outline(i).CPoints():
            points.append((p.x, p.y))
    # add first point to the end, easier zip iterate for closed shape:
    points.append(points[0])
    for start, end in zip(points, points[1:]):
        segment = pcbnew.PCB_SHAPE(board)
        segment.SetShape(pcbnew.SHAPE_T_SEGMENT)
        segment.SetLayer(pcbnew.Edge_Cuts)
        if KICAD_VERSION < (7, 0, 0):
            segment.SetStart(pcbnew.wxPoint(*start))
            segment.SetEnd(pcbnew.wxPoint(*end))
        else:
            segment.SetStart(pcbnew.VECTOR2I(*start))
            segment.SetEnd(pcbnew.VECTOR2I(*end))
        segment.SetWidth(pcbnew.FromMM(0.4))
        board.Add(segment)


def build_board_outline(
    board: pcbnew.BOARD, outline_delta: float, footprint_annotation_format: str
) -> None:
    selected_footprints = []
    if KICAD_VERSION >= (7, 0, 0):
        selection: pcbnew.DRAWINGS = pcbnew.GetCurrentSelection()
        if len(selection) != 0:
            # else use only selected footprints
            logger.info("Running board edge generation around selected footprints")
            selected_footprints = [
                f.Cast() for f in selection if isinstance(f.Cast(), pcbnew.FOOTPRINT)
            ]
            if not selected_footprints:
                logger.info("No footprints selected")

    if not selected_footprints:
        # if nothing selected use all switches
        logger.info(
            "Running board edge generation around footprints with annotation "
            f"matching '{footprint_annotation_format}' format"
        )
        footprints = board.GetFootprints()
        pattern = re.compile(footprint_annotation_format.format("(\\d)+"))
        selected_footprints = [
            f for f in footprints if re.match(pattern, f.GetReference())
        ]

    build_board_outline_around_footprints(board, outline_delta, selected_footprints)
