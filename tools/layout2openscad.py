import argparse
import json
import shutil
import sys
from enum import Enum
from pathlib import Path

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
)

from kbplacer.kle_serial import Keyboard, MatrixAnnotatedKeyboard, get_keyboard


class PlateShape(str, Enum):
    ENVELOPE = "envelope"  # minimum bounding box that encloses switches
    CONVEX_HULL = "convex_hull"  # minimum convex geometry that encloses switches


def _get_cube_hole(rotation, hole_size, plate_thickness):
    c = cube((hole_size, hole_size, 2 * plate_thickness + 2), center=True)
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
    plate_thickness=3,
    margin: float = 0,
    shape: PlateShape = PlateShape.ENVELOPE,
) -> OpenSCADObject:
    switches = []
    holes = []
    if isinstance(keyboard, MatrixAnnotatedKeyboard):
        keys = keyboard.keys_in_matrix_order()
    else:
        keys = keyboard.keys
        keys = sorted(keys, key=lambda k: [k.y, k.x])

    for k in keys:
        if k.decal:
            continue
        p = shapely.box(k.x, -k.y, k.x + k.width, -k.y - k.height)
        p = affinity.rotate(p, -k.rotation_angle, origin=(k.rotation_x, -k.rotation_y))
        switches.append(p)

        c = centroid(p)

        plate_hole = translate(
            (
                dx * c.x,
                dy * c.y,
                0,
            )
        )(_get_cube_hole(-k.rotation_angle, cutout_size, plate_thickness))
        holes.append(plate_hole)

    points = []
    for poly in switches:
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

    result = plate - hole()(*holes)
    return result


def load_keyboard(layout_path) -> Keyboard:
    with open(layout_path, "r", encoding="utf-8") as f:
        layout = json.load(f)
        _keyboard = get_keyboard(layout)
        try:
            _keyboard = MatrixAnnotatedKeyboard(_keyboard.meta, _keyboard.keys)
            _keyboard.collapse()
        except Exception:
            pass

        return _keyboard


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Keyboard layout file to OpenSCAD")
    parser.add_argument("-in", required=True, help="Layout file")
    parser.add_argument("-out", required=True, help="Output path")
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Override output if already exists",
    )
    parser.add_argument(
        "-margin",
        type=float,
        required=False,
        default=0.0,
        help="Margin too add (in mm)",
    )
    parser.add_argument(
        "-shape",
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
        "--plate_thickness",
        type=float,
        required=False,
        default=3,
        help=("Plate thickness in mm, 3 by default"),
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

    keyboard = load_keyboard(input_path)
    args = {
        "dx": args.key_distance_x,
        "dy": args.key_distance_y,
        "cutout_size": args.cutout_size,
        "plate_thickness": args.plate_thickness,
        "margin": args.margin,
        "shape": args.shape,
    }
    result = generate(keyboard, **args)

    scad_render_to_file(result, output_path, file_header="$fn = $preview ? 0 : 100;")
