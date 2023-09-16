import argparse
import itertools
import json
import math
import os
import shutil
import sys
from pathlib import Path

import drawsvg as dw

from kbplacer.kle_serial import get_keyboard

ORIGIN_X = 4
ORIGIN_Y = 4

KEY_WIDTH = 52
KEY_HEIGHT = 52
INNER_GAP_LEFT = 6
INNER_GAP_TOP = 4
INNER_GAP_BOTTOM = 8

LABEL_SIZE = 12


def rotate(origin, point, angle):
    ox, oy = origin
    px, py = point
    radians = math.radians(angle)

    qx = ox + math.cos(radians) * (px - ox) - math.sin(radians) * (py - oy)
    qy = oy + math.sin(radians) * (px - ox) + math.cos(radians) * (py - oy)
    return qx, qy


def build_key(width, height, labels: list, decal: bool):
    key = dw.Group()
    width_px = width * KEY_WIDTH
    height_px = height * KEY_HEIGHT
    if not decal:
        key.append(
            dw.Rectangle(
                0,
                0,
                width_px,
                height_px,
                rx="5",
                fill="#cccccc",
                stroke="black",
                stroke_width=2,
            )
        )
        key.append(
            dw.Rectangle(
                INNER_GAP_LEFT,
                INNER_GAP_TOP,
                width_px - 2 * INNER_GAP_LEFT,
                height_px - INNER_GAP_TOP - INNER_GAP_BOTTOM,
                rx="5",
                fill="#fcfcfc",
                stroke="rgba(0,0,0,.1)",
                stroke_width=1,
            )
        )
    key.append(
        dw.Text(
            labels[0],
            font_size=LABEL_SIZE,
            x=INNER_GAP_LEFT + 1,
            y=INNER_GAP_TOP + LABEL_SIZE + 1,
        )
    )
    if len(labels) >= 9 and labels[8]:
        key.append(
            dw.Text(
                labels[8],
                font_size=LABEL_SIZE,
                x=width_px - INNER_GAP_LEFT - 1,
                y=height_px - LABEL_SIZE - 1,
                text_anchor="end",
            )
        )
    return key


def calcualte_canvas_size(keyboard) -> tuple[int, int]:
    max_x = 0
    max_y = 0
    for k in itertools.chain(keyboard.keys, keyboard.alternative_keys):
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


def create_images(keyboard, output_path):
    width, height = calcualte_canvas_size(keyboard)
    d = dw.Drawing(width, height)

    for k in itertools.chain(keyboard.keys, keyboard.alternative_keys):
        width = k.width
        height = k.height
        x = KEY_WIDTH * k.x
        y = KEY_WIDTH * k.y

        key = build_key(width, height, k.labels, k.decal)

        args = {}
        angle = k.rotation_angle
        if angle != 0:
            rot_x = KEY_WIDTH * k.rotation_x
            rot_y = KEY_HEIGHT * k.rotation_y
            args["transform"] = f"rotate({angle} {rot_x} {rot_y})"
        d.append(dw.Use(key, x + ORIGIN_X, y + ORIGIN_Y, **args))

    d.save_png(f"{output_path}/layout.png")
    d.save_svg(f"{output_path}/layout.svg")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VIA layout file to images")
    parser.add_argument("-in", required=True, help="Layout file")
    parser.add_argument("-out", required=True, help="Otput directory")
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Override output directory if already exists",
    )

    args = parser.parse_args()
    input_path = getattr(args, "in")
    output_path = getattr(args, "out")
    force = args.force

    if force:
        shutil.rmtree(output_path, ignore_errors=True)
    elif Path(output_path).is_dir():
        print(f"Output directory '{output_path}' already exists, exiting...")
        sys.exit(1)

    os.makedirs(output_path)

    with open(input_path, "r") as f:
        layout = json.load(f)
        keyboard = get_keyboard(layout)
        create_images(keyboard, output_path)
