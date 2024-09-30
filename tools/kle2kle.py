import argparse
import json
import math
import sys
from typing import List, Tuple

from kbplacer import kle_serial
from kbplacer.kle_serial import (
    Key,
    Keyboard,
    KeyDefault,
    MatrixAnnotatedKeyboard,
    parse_kle,
)


def get_key_center(key: Key) -> Tuple[float, float]:
    x = key.x + (key.width / 2)
    y = key.y + (key.height / 2)

    rot_origin_x = key.rotation_x
    rot_origin_y = key.rotation_y
    angle = 1 * key.rotation_angle
    angle_rad = angle * math.pi / 180

    x = x - rot_origin_x
    y = y - rot_origin_y

    x1 = (x * math.cos(angle_rad)) - (y * math.sin(angle_rad))
    y1 = (x * math.sin(angle_rad)) + (y * math.cos(angle_rad))

    x = x1 + rot_origin_x
    y = y1 + rot_origin_y

    return x, y


def annotate_keys(keys: List[Key]) -> None:
    for key in keys:
        x, y = get_key_center(key)
        x, y = int(x), int(y)
        key.set_label(MatrixAnnotatedKeyboard.MATRIX_COORDINATES_LABEL, f"{y},{x}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KLE edit")
    parser.add_argument("-in", required=True, help="Layout file")
    parser.add_argument("-out", required=False, help="Result file")
    parser.add_argument(
        "-text", required=False, action="store_true", help="Print KLE raw data"
    )

    parser.add_argument(
        "-remove-labels", action="store_true", help="Remove all key labels"
    )
    parser.add_argument(
        "-reset-colors", action="store_true", help="Reset colors to defaults"
    )
    parser.add_argument(
        "-annotate",
        action="store_true",
        help=(
            "Automatically annotate keys with row,column labels. "
            "All labels must be empty. Can be combined with -remove-labels action."
        ),
    )

    args = parser.parse_args()
    input_path = getattr(args, "in")
    output_path = getattr(args, "out")
    print_result = args.text
    remove_labels = args.remove_labels
    reset_colors = args.reset_colors
    annotate = args.annotate

    with open(input_path, "r", encoding="utf-8") as input_file:
        layout = json.load(input_file)

    keyboard = None
    try:
        keyboard = parse_kle(layout)
        output_format = "KLE_RAW"
    except Exception:
        keyboard = Keyboard.from_json(layout)
        output_format = "KLE_INTERNAL"

    if keyboard == None:
        print(f"Unable to get keyboard layout from file '{input_file}'")
        sys.exit(1)

    if remove_labels:
        for k in keyboard.keys:
            k.labels = []

    if reset_colors:
        for k in keyboard.keys:
            k.color = kle_serial.DEFAULT_KEY_COLOR
            k.textColor = []
            k.default = KeyDefault()

    if annotate:
        annotate_keys(keyboard.keys)

    if print_result:
        raw_kle = keyboard.to_kle()
        print(raw_kle)

    if output_format == "KLE_INTERNAL":
        result = json.loads(keyboard.to_json())
    else:  # KLE_RAW
        result = json.loads("[" + keyboard.to_kle() + "]")

    if output_path:
        with open(output_path, "w", encoding="utf-8") as output_file:
            json.dump(result, output_file, indent=2)
