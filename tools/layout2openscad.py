# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import argparse
import shutil
import sys
from enum import Enum
from pathlib import Path
from typing import List

import shapely
from shapely import MultiPoint, affinity, centroid, envelope
from solid import (
    OpenSCADObject,
    cube,
    hole,
    linear_extrude,
    polygon,
    rotate,
    scad_render_to_file,
    translate,
    union,
)

from kbplacer.kle_serial import (
    Keyboard,
    MatrixAnnotatedKeyboard,
    get_keyboard_from_file,
)


class PlateShape(str, Enum):
    ENVELOPE = "envelope"  # minimum bounding box that encloses switches
    CONVEX_HULL = "convex_hull"  # minimum convex geometry that encloses switches


def _get_cube(rotation, x, y, z):
    c = cube((x, y, z), center=True)
    if rotation == 0:
        return c
    else:
        return rotate(rotation)(c)


def generate(
    keyboard: Keyboard,
    *,
    dx: float = 19.05,
    dy: float = 19.05,
    cutout_size=14.0,
    cutout_outline_thickness=0,
    plate_thickness=3,
    margin: float = 0,
    shape: PlateShape = PlateShape.ENVELOPE,
    outline_ignore: List[int] = [],
    align_origin=False,
    ignore_alternative=False,
) -> OpenSCADObject:
    # for keeping track of switches polygons in order to calculate plate shape later
    # normally would include all switch polygons but could be filtered
    outline_switches = []

    holes = []

    cutout_outline_width = 2.0
    add_hole_outline = cutout_outline_thickness != 0
    holes_outlines = []

    if isinstance(keyboard, MatrixAnnotatedKeyboard):
        keys = keyboard.keys_in_matrix_order()
        if ignore_alternative:
            keys = [
                k for k in keys if MatrixAnnotatedKeyboard.get_layout_option(k) == 0
            ]
    else:
        keys = keyboard.keys
        keys = sorted(keys, key=lambda k: [k.y, k.x])

    offset = None
    for i, k in enumerate(keys):
        if k.decal:
            continue
        p = shapely.box(k.x, -k.y, k.x + k.width, -k.y - k.height)
        p = affinity.rotate(p, -k.rotation_angle, origin=(k.rotation_x, -k.rotation_y))

        # if align option enabled then use center of first switch as reference point (0, 0)
        if align_origin:
            if offset == None:
                offset = centroid(p)
            p = affinity.translate(p, -offset.x, -offset.y, 0)

        if i not in outline_ignore:
            outline_switches.append(p)

        # get switch center and create cube hole based on it
        c = centroid(p)

        plate_hole = translate((dx * c.x, dy * c.y, 0))(
            _get_cube(
                -k.rotation_angle,
                cutout_size,
                cutout_size,
                2 * (plate_thickness + cutout_outline_thickness),
            )
        )
        holes.append(plate_hole)
        if add_hole_outline:
            size = cutout_size + cutout_outline_width
            hole_outline = translate((dx * c.x, dy * c.y, plate_thickness))(
                _get_cube(-k.rotation_angle, size, size, cutout_outline_thickness)
            )
            holes_outlines.append(hole_outline)

    points = []
    for poly in outline_switches:
        for c in poly.exterior.coords:
            points.append((c[0] * dx, c[1] * dy))

    if shape == PlateShape.ENVELOPE:
        plate_polygon = envelope(MultiPoint(points))
    else:  # PlateShape.CONVEX_HULL:
        plate_polygon = MultiPoint(points).convex_hull

    if margin:
        plate_polygon = plate_polygon.buffer(margin)

    _, coords, _ = shapely.to_ragged_array([plate_polygon])
    plate = linear_extrude(height=plate_thickness)(polygon(coords))

    plate_and_hole_outlines = union()(plate, *holes_outlines)
    result = plate_and_hole_outlines - hole()(*holes)
    return result


def load_keyboard(layout_path) -> Keyboard:
    _keyboard = get_keyboard_from_file(layout_path)
    try:
        _keyboard = MatrixAnnotatedKeyboard.from_keyboard(_keyboard)
        _keyboard.collapse()
    except Exception:
        pass

    return _keyboard


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Keyboard layout file to OpenSCAD")
    parser.add_argument("-i", "--in", required=True, help="Layout file")
    parser.add_argument("-o", "--out", required=True, help="Output path")
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Override output if already exists",
    )
    parser.add_argument(
        "--margin",
        type=float,
        required=False,
        default=0.0,
        help="Margin too add (in mm)",
    )
    parser.add_argument(
        "--shape",
        type=PlateShape,
        choices=list(PlateShape),
        required=False,
        default=PlateShape.ENVELOPE,
        help="Plate shape",
    )
    parser.add_argument(
        "--key-distance-x",
        type=float,
        required=False,
        default=19.05,
        help=("1U distance in mm between two keys in X direction, 19.05 by default"),
    )
    parser.add_argument(
        "--key-distance-y",
        type=float,
        required=False,
        default=19.05,
        help=("1U distance in mm between two keys in Y direction, 19.05 by default"),
    )
    parser.add_argument(
        "--cutout-size",
        type=float,
        required=False,
        default=14,
        help=("Size of switch cutout, 14 by default"),
    )
    parser.add_argument(
        "--cutout-outline-thickness",
        type=float,
        required=False,
        default=0,
        help=("Thickness for per-key outline, for prototyping"),
    )
    parser.add_argument(
        "--plate-thickness",
        type=float,
        required=False,
        default=3,
        help=("Plate thickness in mm, 3 by default"),
    )
    parser.add_argument(
        "--align-origin",
        action="store_true",
        help=("Place first layout switch at (0,0,0)"),
    )
    parser.add_argument(
        "--ignore-alternative-layouts",
        action="store_true",
        help=("Ignore alternative layout keys"),
    )
    parser.add_argument(
        "--outline-ignore-keys",
        required=False,
        default="",
        help=(
            "Comma separated list of key indexes to ignore when calculating plate shape"
        ),
    )

    args = parser.parse_args()
    input_path = getattr(args, "in")
    output_path = getattr(args, "out")
    force = args.force

    if force:
        shutil.rmtree(output_path, ignore_errors=True)
    elif Path(output_path).is_file():
        print(
            f"Output file '{output_path}' already exists, exiting...", file=sys.stderr
        )
        sys.exit(1)

    outline_ignore = []
    if args.outline_ignore_keys:
        outline_ignore = [int(val) for val in args.outline_ignore_keys.split(",")]

    keyboard = load_keyboard(input_path)
    args = {
        "dx": args.key_distance_x,
        "dy": args.key_distance_y,
        "cutout_size": args.cutout_size,
        "cutout_outline_thickness": args.cutout_outline_thickness,
        "plate_thickness": args.plate_thickness,
        "margin": args.margin,
        "shape": args.shape,
        "outline_ignore": outline_ignore,
        "align_origin": args.align_origin,
        "ignore_alternative": args.ignore_alternative_layouts,
    }
    result = generate(keyboard, **args)

    scad_render_to_file(result, output_path, file_header="$fn = $preview ? 0 : 100;")
