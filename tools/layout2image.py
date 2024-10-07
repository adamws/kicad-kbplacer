from __future__ import annotations

import argparse
import itertools
import json
import logging
import math
import shutil
import sys
from pathlib import Path
from typing import Iterator

import drawsvg as dw
import yaml
from colormath.color_conversions import convert_color
from colormath.color_objects import LabColor, sRGBColor

from kbplacer.kle_serial import Key, Keyboard, MatrixAnnotatedKeyboard, get_keyboard

logger = logging.getLogger(__name__)

KEY_WIDTH_PX = 52
KEY_HEIGHT_PX = KEY_WIDTH_PX
KEY_CORNER_RADIUS = 5
KEY_STROKE_WIDTH = 2
FILL_GAP = KEY_STROKE_WIDTH / 2
KEYTOP_GAP_LEFT_PX = 6
KEYTOP_GAP_TOP_PX = 4
KEYTOP_GAP_BOTTOM_PX = 8

ORIGIN_X = 2 + KEY_STROKE_WIDTH
ORIGIN_Y = ORIGIN_X

LABEL_X_POSITION = [
    (lambda _: KEYTOP_GAP_LEFT_PX + 1, "start"),
    (lambda width: width * KEY_WIDTH_PX / 2, "middle"),
    (lambda width: width * KEY_WIDTH_PX - KEYTOP_GAP_LEFT_PX - 1, "end"),
]
LABEL_Y_POSITION = [
    (lambda _: KEYTOP_GAP_TOP_PX + 1, "hanging"),
    (lambda height: height * KEY_HEIGHT_PX / 2, "middle"),
    (lambda height: height * KEY_HEIGHT_PX - KEYTOP_GAP_BOTTOM_PX - 2, "auto"),
    (lambda height: height * KEY_HEIGHT_PX - 2, "auto"),
]
LABEL_SIZES = [12, 12, 12, 7]


def lighten_color(hex_color: str) -> str:
    color = sRGBColor.new_from_rgb_hex(hex_color)
    lab_color = convert_color(color, LabColor)
    lab_color.lab_l = min(100, lab_color.lab_l * 1.2)
    rgb = convert_color(lab_color, sRGBColor)
    return sRGBColor(
        rgb.clamped_rgb_r, rgb.clamped_rgb_g, rgb.clamped_rgb_b
    ).get_rgb_hex()


def rotate(origin, point, angle):
    ox, oy = origin
    px, py = point
    radians = math.radians(angle)

    qx = ox + math.cos(radians) * (px - ox) - math.sin(radians) * (py - oy)
    qy = oy + math.sin(radians) * (px - ox) + math.cos(radians) * (py - oy)
    return qx, qy


def build_key(key: Key):
    group = dw.Group()
    not_rectangle = key.width != key.width2 or key.height != key.height2

    # some layouts used to fail due to: 'input #ccccccc is not in #RRGGBB format',
    # truncate too long strings, if color is still illegal then use default
    dark_color = key.color[0:7]
    try:
        sRGBColor.new_from_rgb_hex(dark_color)
    except Exception:
        logger.warning(f"Illegal color ('{dark_color}') value found, using default")
        dark_color = "#cccccc"
    light_color = lighten_color(dark_color)

    def border(x, y, w, h) -> dw.Rectangle:  # pyright: ignore
        return dw.Rectangle(
            x * KEY_WIDTH_PX,
            y * KEY_HEIGHT_PX,
            w * KEY_WIDTH_PX,
            h * KEY_HEIGHT_PX,
            rx=f"{KEY_CORNER_RADIUS}",
            fill="none",
            stroke="black",
            stroke_width=KEY_STROKE_WIDTH,
        )

    def fill(x, y, w, h) -> dw.Rectangle:  # pyright: ignore
        return dw.Rectangle(
            x * KEY_WIDTH_PX + FILL_GAP,
            y * KEY_HEIGHT_PX + FILL_GAP,
            w * KEY_WIDTH_PX - 2 * FILL_GAP,
            h * KEY_HEIGHT_PX - 2 * FILL_GAP,
            rx=f"{KEY_CORNER_RADIUS - FILL_GAP}",
            fill=dark_color,
        )

    def keytop(x, y, w, h) -> dw.Rectangle:  # pyright: ignore
        return dw.Rectangle(
            x * KEY_WIDTH_PX + KEYTOP_GAP_LEFT_PX,
            y * KEY_HEIGHT_PX + KEYTOP_GAP_TOP_PX,
            w * KEY_WIDTH_PX - 2 * KEYTOP_GAP_LEFT_PX,
            h * KEY_HEIGHT_PX - KEYTOP_GAP_TOP_PX - KEYTOP_GAP_BOTTOM_PX,
            rx=f"{KEY_CORNER_RADIUS}",
            fill=light_color,
        )

    if not key.decal:
        layers = ["border", "fill", "keytop"]
        for layer in layers:
            group.append(locals()[layer](0, 0, key.width, key.height))
            if not_rectangle:
                group.append(locals()[layer](key.x2, key.y2, key.width2, key.height2))

    for i, label in enumerate(key.labels):
        if label:
            lines = label.split("<br>")
            position_x = LABEL_X_POSITION[i % 3]
            position_y = LABEL_Y_POSITION[int(i / 3)]
            label_size = LABEL_SIZES[int(i / 3)]
            group.append(
                dw.Text(
                    lines,
                    font_size=label_size,
                    x=position_x[0](key.width),
                    y=position_y[0](key.height),
                    text_anchor=position_x[1],
                    dominant_baseline=position_y[1],
                )
            )
    return group


def calcualte_canvas_size(key_iterator: Iterator) -> tuple[int, int]:
    max_x = 0
    max_y = 0
    for k in key_iterator:
        angle = k.rotation_angle
        if angle != 0:
            # when rotated, check each corner
            x1 = KEY_WIDTH_PX * k.x
            x2 = KEY_WIDTH_PX * k.x + KEY_WIDTH_PX * k.width
            y1 = KEY_HEIGHT_PX * k.y
            y2 = KEY_HEIGHT_PX * k.y + KEY_HEIGHT_PX * k.height

            for x, y in [(x1, y1), (x2, y1), (x1, y2), (x2, y2)]:
                rot_x = KEY_WIDTH_PX * k.rotation_x
                rot_y = KEY_HEIGHT_PX * k.rotation_y
                x, y = rotate((rot_x, rot_y), (x, y), angle)
                x, y = int(x), int(y)
                if x >= max_x:
                    max_x = x
                if y >= max_y:
                    max_y = y

        else:
            # when not rotated, it is safe to check only bottom right corner:
            x = KEY_WIDTH_PX * k.x + KEY_WIDTH_PX * k.width
            y = KEY_HEIGHT_PX * k.y + KEY_HEIGHT_PX * k.height
            if x >= max_x:
                max_x = x
            if y >= max_y:
                max_y = y
    return max_x + 2 * ORIGIN_X, max_y + 2 * ORIGIN_Y


def create_images(input_path: str, output_path):
    if input_path != "-":
        with open(input_path, "r", encoding="utf-8") as f:
            if input_path.endswith("yaml") or input_path.endswith("yml"):
                layout = yaml.safe_load(f)
            else:
                layout = json.load(f)
    else:
        try:
            layout = yaml.safe_load(sys.stdin)
        except Exception:
            layout = json.load(sys.stdin)

    _keyboard: Keyboard = get_keyboard(layout)

    def _get_iterator():
        if isinstance(_keyboard, MatrixAnnotatedKeyboard):
            return itertools.chain(_keyboard.keys, _keyboard.alternative_keys)
        else:
            return iter(_keyboard.keys)

    width, height = calcualte_canvas_size(_get_iterator())
    d = dw.Drawing(width, height)

    for k in _get_iterator():
        width = k.width
        height = k.height
        x = KEY_WIDTH_PX * k.x
        y = KEY_WIDTH_PX * k.y

        key = build_key(k)

        args = {}
        angle = k.rotation_angle
        if angle != 0:
            rot_x = KEY_WIDTH_PX * k.rotation_x
            rot_y = KEY_HEIGHT_PX * k.rotation_y
            args["transform"] = f"rotate({angle} {rot_x} {rot_y})"
        d.append(dw.Use(key, x + ORIGIN_X, y + ORIGIN_Y, **args))

    d.save_svg(output_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Layout file to images")
    parser.add_argument(
        "-in", nargs="?", type=str, default="-", help="Input path or '-' for stdin"
    )
    parser.add_argument("-out", required=True, help="Output path")
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Override output if already exists",
    )
    parser.add_argument(
        "--log-level",
        required=False,
        default="WARNING",
        choices=logging._nameToLevel.keys(),
        type=str,
        help="Provide logging level, default=%(default)s",
    )

    args = parser.parse_args()
    input_path = getattr(args, "in")
    output_path = getattr(args, "out")
    force = args.force

    # set up logger
    logging.basicConfig(
        level=args.log_level, format="%(asctime)s: %(message)s", datefmt="%H:%M:%S"
    )

    if force:
        shutil.rmtree(output_path, ignore_errors=True)
    elif Path(output_path).is_file():
        logger.error(f"Output file '{output_path}' already exists, exiting...")
        sys.exit(1)

    create_images(input_path, output_path)
