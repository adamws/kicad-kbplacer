import argparse
import json
import sys

import yaml
from pyurlon import stringify

from kbplacer.kle_serial import Keyboard, get_keyboard

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KLE format converter")
    parser.add_argument(
        "-in", nargs="?", type=str, default="-", help="Input path or '-' for stdin"
    )

    args = parser.parse_args()
    input_path = getattr(args, "in")

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

    keyboard: Keyboard = get_keyboard(layout)
    kle_raw = json.loads("[" + keyboard.to_kle() + "]")

    # keyboard-layout-editor uses old version of urlon,
    # for this reason each `_` in metadata value must be replaced with `-`
    # and all `$` in resulting url with `_`.
    # see https://github.com/cerebral/urlon/commit/efbdc00af4ec48cabb28372e6f3fcc0c0a30a4c7
    if isinstance(kle_raw[0], dict):
        for k, v in kle_raw[0].items():
            kle_raw[0][k] = v.replace("_", "-")
    kle_url = stringify(kle_raw)
    kle_url = kle_url.replace("$", "_")
    kle_url = "http://www.keyboard-layout-editor.com/##" + kle_url
    print(kle_url)
