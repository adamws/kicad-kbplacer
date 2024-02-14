from __future__ import annotations

import argparse
import itertools
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Iterator, Union

import drawsvg as dw
import yaml

from kbplacer.kle_serial import Key, Keyboard, MatrixAnnotatedKeyboard, get_keyboard

ORIGIN_X = 4
ORIGIN_Y = 4

KEY_WIDTH = 52
KEY_HEIGHT = 52
INNER_GAP_LEFT = 6
INNER_GAP_TOP = 4
INNER_GAP_BOTTOM = 8

LABEL_X_POSITION = [
    (INNER_GAP_LEFT + 1, "start"),
    (KEY_WIDTH / 2, "middle"),
    (KEY_WIDTH - INNER_GAP_LEFT - 1, "end"),
]
LABEL_Y_POSITION = [
    (INNER_GAP_TOP, "hanging"),
    (KEY_HEIGHT / 2, "middle"),
    (KEY_HEIGHT - INNER_GAP_BOTTOM - 2, "auto"),
    (KEY_HEIGHT - 2, "auto"),
]
LABEL_SIZES = [12, 12, 12, 7]


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
    dark_color = "#cccccc"
    light_color = "#fcfcfc"

    def border(x, y, w, h) -> dw.Rectangle:  # pyright: ignore
        return dw.Rectangle(
            x * KEY_WIDTH,
            y * KEY_HEIGHT,
            w * KEY_WIDTH,
            h * KEY_HEIGHT,
            rx="5",
            fill="none",
            stroke="black",
            stroke_width=2,
        )

    def fill(x, y, w, h) -> dw.Rectangle:  # pyright: ignore
        return dw.Rectangle(
            x * KEY_WIDTH + 1,
            y * KEY_HEIGHT + 1,
            w * KEY_WIDTH - 2,
            h * KEY_HEIGHT - 2,
            rx="5",
            fill=dark_color,
        )

    def top(x, y, w, h) -> dw.Rectangle:  # pyright: ignore
        return dw.Rectangle(
            x * KEY_WIDTH + INNER_GAP_LEFT,
            y * KEY_HEIGHT + INNER_GAP_TOP,
            w * KEY_WIDTH - 2 * INNER_GAP_LEFT,
            h * KEY_HEIGHT - INNER_GAP_TOP - INNER_GAP_BOTTOM,
            rx="5",
            fill=light_color,
        )

    if not key.decal:
        layers = ["border", "fill", "top"]
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
                    x=position_x[0],
                    y=position_y[0],
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
            x1 = KEY_WIDTH * k.x
            x2 = KEY_WIDTH * k.x + KEY_WIDTH * k.width
            y1 = KEY_HEIGHT * k.y
            y2 = KEY_HEIGHT * k.y + KEY_HEIGHT * k.height

            for x, y in [(x1, y1), (x2, y1), (x1, y2), (x2, y2)]:
                rot_x = KEY_WIDTH * k.rotation_x
                rot_y = KEY_HEIGHT * k.rotation_y
                x, y = rotate((rot_x, rot_y), (x, y), angle)
                x, y = int(x), int(y)
                if x >= max_x:
                    max_x = x
                if y >= max_y:
                    max_y = y

        else:
            # when not rotated, it is safe to check only bottom right corner:
            x = KEY_WIDTH * k.x + KEY_WIDTH * k.width
            y = KEY_HEIGHT * k.y + KEY_HEIGHT * k.height
            if x >= max_x:
                max_x = x
            if y >= max_y:
                max_y = y
    return max_x + 2 * ORIGIN_X, max_y + 2 * ORIGIN_Y


def create_images(keyboard: Union[str, Keyboard], output_path):
    if isinstance(keyboard, str):
        with open(keyboard, "r") as f:
            if keyboard.endswith("yaml") or keyboard.endswith("yml"):
                layout = yaml.safe_load(f)
            else:
                layout = json.load(f)
            _keyboard: Keyboard = get_keyboard(layout)
    else:
        _keyboard: Keyboard = keyboard

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
        x = KEY_WIDTH * k.x
        y = KEY_WIDTH * k.y

        key = build_key(k)

        args = {}
        angle = k.rotation_angle
        if angle != 0:
            rot_x = KEY_WIDTH * k.rotation_x
            rot_y = KEY_HEIGHT * k.rotation_y
            args["transform"] = f"rotate({angle} {rot_x} {rot_y})"
        d.append(dw.Use(key, x + ORIGIN_X, y + ORIGIN_Y, **args))

    d.save_svg(output_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Layout file to images")
    parser.add_argument("-in", required=True, help="Layout file")
    parser.add_argument("-out", required=True, help="Output path")
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Override output if already exists",
    )

    args = parser.parse_args()
    input_path = getattr(args, "in")
    output_path = getattr(args, "out")
    force = args.force

    if force:
        shutil.rmtree(output_path, ignore_errors=True)
    elif Path(output_path).is_file():
        print(f"Output file '{output_path}' already exists, exiting...")
        sys.exit(1)

    create_images(input_path, output_path)
