# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import argparse
import json

from pyurlon import stringify

from kbplacer.kle_serial import Keyboard, get_keyboard_from_file

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KLE format converter")
    parser.add_argument(
        "-i",
        "--in",
        nargs="?",
        type=str,
        default="-",
        help="Input path or '-' for stdin",
    )

    args = parser.parse_args()
    input_path = getattr(args, "in")

    keyboard: Keyboard = get_keyboard_from_file(input_path)
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
