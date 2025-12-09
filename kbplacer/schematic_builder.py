# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import argparse
import logging
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .board_modifier import KICAD_VERSION
from .kle_serial import (
    Key,
    MatrixAnnotatedKeyboard,
    get_keyboard_from_file,
)

try:
    from skip import Schematic
except ImportError:
    _has_schematic = False
else:
    _has_schematic = True


logger = logging.getLogger(__name__)

ORIGIN = (18, 18)
UNIT = 1.27

COLUMN_DISTANCE = 10
ROW_DISTANCE = 16

TEMPLATE = """\
(kicad_sch
    (version 20250114)
    (generator "eeschema")
    (generator_version "9.0")
    (uuid "9e45a776-7007-48ff-b543-dc98423173b7")
    (paper "{page_size}")
    (lib_symbols
        (symbol "Device:D_Small"
            (pin_numbers
                (hide yes)
            )
            (pin_names
                (offset 0.254)
                (hide yes)
            )
            (exclude_from_sim no)
            (in_bom yes)
            (on_board yes)
            (property "Reference" "D"
                (at -1.27 2.032 0)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                    (justify left)
                )
            )
            (property "Value" "D_Small"
                (at -3.81 -2.032 0)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                    (justify left)
                )
            )
            (property "Footprint" ""
                (at 0 0 90)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                    (hide yes)
                )
            )
            (property "Datasheet" "~"
                (at 0 0 90)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                    (hide yes)
                )
            )
            (property "Description" "Diode, small symbol"
                (at 0 0 0)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                    (hide yes)
                )
            )
            (property "Sim.Device" "D"
                (at 0 0 0)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                    (hide yes)
                )
            )
            (property "Sim.Pins" "1=K 2=A"
                (at 0 0 0)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                    (hide yes)
                )
            )
            (property "ki_keywords" "diode"
                (at 0 0 0)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                    (hide yes)
                )
            )
            (property "ki_fp_filters" "TO-???* *_Diode_* *SingleDiode* D_*"
                (at 0 0 0)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                    (hide yes)
                )
            )
            (symbol "D_Small_0_1"
                (polyline
                    (pts
                        (xy -0.762 0) (xy 0.762 0)
                    )
                    (stroke
                        (width 0)
                        (type default)
                    )
                    (fill
                        (type none)
                    )
                )
                (polyline
                    (pts
                        (xy -0.762 -1.016) (xy -0.762 1.016)
                    )
                    (stroke
                        (width 0.254)
                        (type default)
                    )
                    (fill
                        (type none)
                    )
                )
                (polyline
                    (pts
                        (xy 0.762 -1.016) (xy -0.762 0) (xy 0.762 1.016) (xy 0.762 -1.016)
                    )
                    (stroke
                        (width 0.254)
                        (type default)
                    )
                    (fill
                        (type none)
                    )
                )
            )
            (symbol "D_Small_1_1"
                (pin passive line
                    (at -2.54 0 0)
                    (length 1.778)
                    (name "K"
                        (effects
                            (font
                                (size 1.27 1.27)
                            )
                        )
                    )
                    (number "1"
                        (effects
                            (font
                                (size 1.27 1.27)
                            )
                        )
                    )
                )
                (pin passive line
                    (at 2.54 0 180)
                    (length 1.778)
                    (name "A"
                        (effects
                            (font
                                (size 1.27 1.27)
                            )
                        )
                    )
                    (number "2"
                        (effects
                            (font
                                (size 1.27 1.27)
                            )
                        )
                    )
                )
            )
            (embedded_fonts no)
        )
        (symbol "Switch:SW_Push_45deg"
            (pin_numbers
                (hide yes)
            )
            (pin_names
                (offset 1.016)
                (hide yes)
            )
            (exclude_from_sim no)
            (in_bom yes)
            (on_board yes)
            (property "Reference" "SW"
                (at 3.048 1.016 0)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                    (justify left)
                )
            )
            (property "Value" "SW_Push_45deg"
                (at 0 -3.81 0)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                )
            )
            (property "Footprint" ""
                (at 0 0 0)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                    (hide yes)
                )
            )
            (property "Datasheet" "~"
                (at 0 0 0)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                    (hide yes)
                )
            )
            (property "Description" "Push button switch, normally open, two pins, 45° tilted"
                (at 0 0 0)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                    (hide yes)
                )
            )
            (property "ki_keywords" "switch normally-open pushbutton push-button"
                (at 0 0 0)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                    (hide yes)
                )
            )
            (symbol "SW_Push_45deg_0_1"
                (polyline
                    (pts
                        (xy -2.54 2.54) (xy -1.524 1.524) (xy -1.524 1.524)
                    )
                    (stroke
                        (width 0)
                        (type default)
                    )
                    (fill
                        (type none)
                    )
                )
                (circle
                    (center -1.1684 1.1684)
                    (radius 0.508)
                    (stroke
                        (width 0)
                        (type default)
                    )
                    (fill
                        (type none)
                    )
                )
                (polyline
                    (pts
                        (xy -0.508 2.54) (xy 2.54 -0.508)
                    )
                    (stroke
                        (width 0)
                        (type default)
                    )
                    (fill
                        (type none)
                    )
                )
                (polyline
                    (pts
                        (xy 1.016 1.016) (xy 2.032 2.032)
                    )
                    (stroke
                        (width 0)
                        (type default)
                    )
                    (fill
                        (type none)
                    )
                )
                (circle
                    (center 1.143 -1.1938)
                    (radius 0.508)
                    (stroke
                        (width 0)
                        (type default)
                    )
                    (fill
                        (type none)
                    )
                )
                (polyline
                    (pts
                        (xy 1.524 -1.524) (xy 2.54 -2.54) (xy 2.54 -2.54) (xy 2.54 -2.54)
                    )
                    (stroke
                        (width 0)
                        (type default)
                    )
                    (fill
                        (type none)
                    )
                )
                (pin passive line
                    (at -2.54 2.54 0)
                    (length 0)
                    (name "1"
                        (effects
                            (font
                                (size 1.27 1.27)
                            )
                        )
                    )
                    (number "1"
                        (effects
                            (font
                                (size 1.27 1.27)
                            )
                        )
                    )
                )
                (pin passive line
                    (at 2.54 -2.54 180)
                    (length 0)
                    (name "2"
                        (effects
                            (font
                                (size 1.27 1.27)
                            )
                        )
                    )
                    (number "2"
                        (effects
                            (font
                                (size 1.27 1.27)
                            )
                        )
                    )
                )
            )
            (embedded_fonts no)
        )
    )
    (symbol
        (lib_id "Switch:SW_Push_45deg")
        (at 0 0 0)
        (unit 1)
        (exclude_from_sim no)
        (in_bom yes)
        (on_board yes)
        (dnp no)
        (uuid "19751ded-3cc5-4b31-aeeb-fd1357dc1d55")
        (property "Reference" "SW1"
            (at 0 -5.08 0)
            (effects
                (font
                    (size 1.27 1.27)
                )
            )
        )
        (property "Value" "SW_Push"
            (at 0 -3.81 0)
            (effects
                (font
                    (size 1.27 1.27)
                )
                (hide yes)
            )
        )
        (property "Footprint" ""
            (at 0 0 0)
            (effects
                (font
                    (size 1.27 1.27)
                )
                (hide yes)
            )
        )
        (property "Datasheet" "~"
            (at 0 0 0)
            (effects
                (font
                    (size 1.27 1.27)
                )
                (hide yes)
            )
        )
        (property "Description" ""
            (at 0 0 0)
            (effects
                (font
                    (size 1.27 1.27)
                )
            )
        )
        (pin "1"
            (uuid "94c53fa6-dd8d-4e6d-9c1a-277431558d0a")
        )
        (pin "2"
            (uuid "ef827767-19b4-4ee5-b4b6-65189b88f8ee")
        )
        (instances
            (project "template"
                (path "/9e45a776-7007-48ff-b543-dc98423173b7"
                    (reference "SW1")
                    (unit 1)
                )
            )
        )
    )
    (symbol
        (lib_id "Device:D_Small")
        (at 2.54 6.35 90)
        (unit 1)
        (exclude_from_sim no)
        (in_bom yes)
        (on_board yes)
        (dnp no)
        (uuid "feb0fa1f-f7ed-4393-bef6-632a7fa048d6")
        (property "Reference" "D1"
            (at 3.81 5.08 90)
            (effects
                (font
                    (size 1.27 1.27)
                )
                (justify right)
            )
        )
        (property "Value" "D"
            (at 3.81 7.62 90)
            (effects
                (font
                    (size 1.27 1.27)
                )
                (justify right)
                (hide yes)
            )
        )
        (property "Footprint" ""
            (at 2.54 6.35 90)
            (effects
                (font
                    (size 1.27 1.27)
                )
                (hide yes)
            )
        )
        (property "Datasheet" "~"
            (at 2.54 6.35 90)
            (effects
                (font
                    (size 1.27 1.27)
                )
                (hide yes)
            )
        )
        (property "Description" ""
            (at 2.54 6.35 0)
            (effects
                (font
                    (size 1.27 1.27)
                )
            )
        )
        (property "Sim.Device" "D"
            (at 2.54 6.35 0)
            (effects
                (font
                    (size 1.27 1.27)
                )
                (hide yes)
            )
        )
        (property "Sim.Pins" "1=K 2=A"
            (at 2.54 6.35 0)
            (effects
                (font
                    (size 1.27 1.27)
                )
                (hide yes)
            )
        )
        (pin "1"
            (uuid "004cc590-2791-46a0-9480-7962783605a4")
        )
        (pin "2"
            (uuid "428af732-f843-4705-863e-a0095a5fb80a")
        )
        (instances
            (project "template"
                (path "/9e45a776-7007-48ff-b543-dc98423173b7"
                    (reference "D1")
                    (unit 1)
                )
            )
        )
    )
    (sheet_instances
        (path "/"
            (page "1")
        )
    )
    (embedded_fonts no)
)
"""


def _x(x: int) -> float:
    return (ORIGIN[0] * UNIT) + (x * UNIT)


def _y(y: int) -> float:
    return (ORIGIN[1] * UNIT) + (y * UNIT)


def load_keyboard(layout_path) -> MatrixAnnotatedKeyboard:
    _keyboard = get_keyboard_from_file(layout_path)
    _keyboard = MatrixAnnotatedKeyboard.from_keyboard(_keyboard)
    _keyboard.collapse()
    return _keyboard


def get_lowest_paper_size(size):
    matrix_size_to_paper = {(8, 19): "A4", (11, 30): "A3", (17, 44): "A2"}
    smallest_size = None
    for key in sorted(matrix_size_to_paper):
        if size[0] <= key[0] and size[1] <= key[1]:
            smallest_size = matrix_size_to_paper[key]
            break
    if smallest_size is None:
        smallest_size = "A1"
    return smallest_size


def parse_annotation(annotation: str) -> Tuple[Optional[str], int]:
    pattern = r"^([A-Za-z]*)(\d+)$"

    match = re.match(pattern, annotation)
    if match:
        prefix, digits = match.groups()
        return prefix if prefix else None, int(digits)
    msg = "Unexpected annotation format"
    raise RuntimeError(msg)


def get_or_default(value: Optional[str], default: str) -> str:
    return value if value else default


def _is_valid_template(s: str) -> bool:
    try:
        s.format(1)
        return True
    except (ValueError, IndexError, KeyError):
        return False


def _is_width_supported(key: Key) -> bool:
    # probably should use some searching to see if given footprint exist,
    # for now just assume that any library supports following widths:
    supported_widths = [
        1,
        1.25,
        1.5,
        1.75,
        2,
        2.25,
        2.5,
        2.75,
        3,
        4,
        4.5,
        5.5,
        6,
        6.25,
        6.5,
        7,
    ]
    return key.width in supported_widths


def _is_iso_enter(key: Key) -> bool:
    return (
        key.width == 1.25 and key.height == 2 and key.width2 == 1.5 and key.height2 == 1
    )


def create_schematic(
    keyboard: MatrixAnnotatedKeyboard,
    output_path,
    switch_footprint="",
    diode_footprint="",
) -> None:
    if not _has_schematic:
        msg = "Requires optional schematic dependencies"
        raise ImportError(msg)
    if KICAD_VERSION < (9, 0, 0):
        msg = "Requires KiCad 9.0 or higher"
        raise RuntimeError(msg)

    matrix = [
        (parse_annotation(pos[0])[1], parse_annotation(pos[1])[1])
        for pos in (
            MatrixAnnotatedKeyboard.get_matrix_position(k)
            for k in keyboard.keys_in_matrix_order()
        )
    ]
    keys = [k for k in keyboard.keys_in_matrix_order()]

    logger.debug(f"Matrix: {matrix}")

    # deduce label names from annotation of first key,
    # if annotations are comma separated numbers then use default 'ROW'/'COL' names,
    # otherwise use same prefix as in annotation
    first_key = keyboard.keys[0]
    first_key_matrix_position = MatrixAnnotatedKeyboard.get_matrix_position(first_key)
    row_label_prefix = get_or_default(
        parse_annotation(first_key_matrix_position[0])[0], "ROW"
    )
    column_label_prefix = get_or_default(
        parse_annotation(first_key_matrix_position[1])[0], "COL"
    )

    logger.debug(
        f"Labels prefixes: for rows: '{row_label_prefix}', "
        f"for columns: '{column_label_prefix}'"
    )

    # rows and columns does not necessarily contain each value from min to max,
    # i.e. matrix can have columns numbers: 1, 2, 4, 5. Because whole
    # element placing and wiring logic depends on fixed positions calculated
    # from row/column values, the following `rows` and `columns` variables
    # represents maximum size (using mentioned example, columns = 5 (and not 4).
    # Even though the whole column 3 will be empty, it is easier to draw that.
    # We also assume that both rows and columns starts from 0 and can't be negative.
    rows = max(set([x[0] for x in matrix]))
    columns = max(set([x[1] for x in matrix]))
    logger.debug(f"Matrix size: {rows}x{columns}")

    with open(output_path, "w") as f:
        size = (rows, columns)
        f.write(TEMPLATE.format(page_size=get_lowest_paper_size(size)))

    sch = Schematic(output_path)
    base_switch = sch.symbol.reference_startswith("SW")[0]
    switch_footprint_format = False
    if switch_footprint:
        base_switch.property.Footprint.value = switch_footprint
        switch_footprint_format = _is_valid_template(switch_footprint)
    base_diode = sch.symbol.reference_startswith("D")[0]
    if diode_footprint:
        base_diode.property.Footprint.value = diode_footprint

    progress: Dict[Tuple[int, int], List[str]] = defaultdict(list)

    current_ref = 1
    labels = set()
    labels_positions = dict()

    for key, (row, column) in zip(keys, matrix):
        position = (row, column)
        logger.debug(f"row: {row} column: {column}")
        row_label = f"{row_label_prefix}{row}"
        column_label = f"{column_label_prefix}{column}"

        used_slots = len(progress[position])
        # clamp to maximum value (use same slot for all 3+ alternative keys)
        # schematic readability will suffer but such layouts are uncommon anyway
        used_slots = min(used_slots, 3)

        switch = base_switch.clone()
        if switch_footprint_format:
            if not _is_width_supported(key) or _is_iso_enter(key):
                key_width = 1
            else:
                key_width = key.width
            switch.property.Footprint.value = switch_footprint.format(key_width)
        if used_slots == 0:
            switch_reference = f"SW{current_ref}"
        else:
            default_switch = progress[position][0]
            switch_reference = f"{default_switch}_{used_slots}"
        switch.setAllReferences(switch_reference)
        switch_x = _x(COLUMN_DISTANCE * int(column) + 5)
        switch_y = _y(ROW_DISTANCE * int(row) + used_slots)
        switch.move(switch_x, switch_y)
        if used_slots != 0:
            junc = sch.junction.new()
            junc.move(switch.pin.n2.location.x, switch.pin.n2.location.y)
        wire = sch.wire.new()
        wire.start_at(switch.pin.n1)
        wire.delta_x = -1 * UNIT
        wire.delta_y = 0
        if column_label not in labels and used_slots == 0:
            column_wire = sch.wire.new()
            column_wire.start_at(wire.end)
            column_wire.delta_x = 0
            column_wire.delta_y = (ROW_DISTANCE * (rows - row) + 15) * UNIT

            label = sch.global_label.new()
            label.move(column_wire.end.value[0], column_wire.end.value[1], 270)
            label.value = column_label
            labels.add(column_label)
            labels_positions[column_label] = label.at
        else:
            junc = sch.junction.new()
            junc.move(wire.end)
            # must add explicit wire from junction back to label
            # kicad will be able to open and fix the schematic automatically
            # if we don't do it, but we want to avoid using eeschema in our workflow
            wire = sch.wire.new()
            wire.start_at(junc.at)
            wire.end_at(labels_positions[column_label])

        if used_slots == 0:
            diode = base_diode.clone()
            diode.setAllReferences(f"D{current_ref}")
            diode_x = switch_x + 2 * UNIT
            diode_y = switch_y + 7 * UNIT
            diode.move(diode_x, diode_y)
            wire = sch.wire.new()
            wire.start_at(switch.pin.n2)
            wire.end_at(diode.pin.K)
            wire = sch.wire.new()
            wire.start_at(diode.pin.A)
            wire.delta_x = 0
            wire.delta_y = 1 * UNIT
            if row_label not in labels:
                row_wire = sch.wire.new()
                row_wire.start_at(wire.end)
                row_wire.delta_x = (COLUMN_DISTANCE * (columns - column) + 5) * UNIT
                row_wire.delta_y = 0

                label = sch.global_label.new()
                label.move(row_wire.end.value[0], row_wire.end.value[1], 0)
                label.effects.justify.value = "left"
                label.value = row_label
                labels.add(row_label)
                labels_positions[row_label] = label.at
            else:
                junc = sch.junction.new()
                junc.move(wire.end)
                # explicit wire from junction to label (same as for columns)
                wire = sch.wire.new()
                wire.start_at(junc.at)
                wire.end_at(labels_positions[row_label])

            current_ref += 1

        progress[position].append(switch_reference)

    base_switch.delete()
    base_diode.delete()

    sch.write(output_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Keyboard layout to KiCad schematic",
    )

    parser.add_argument("-i", "--in", required=True, help="Layout file")
    parser.add_argument("-o", "--out", required=True, help="Output path")
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Override output if already exists",
    )
    parser.add_argument(
        "-swf", "--switch-footprint", required=False, help="Switch footprint"
    )
    parser.add_argument(
        "-df", "--diode-footprint", required=False, help="Diode footprint"
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
    switch_footprint = args.switch_footprint
    diode_footprint = args.diode_footprint

    # set up logger
    logging.basicConfig(
        level=args.log_level, format="%(asctime)s: %(message)s", datefmt="%H:%M:%S"
    )

    if force:
        shutil.rmtree(output_path, ignore_errors=True)
    elif Path(output_path).is_file():
        logger.error(f"Output file '{output_path}' already exists, exiting...")
        sys.exit(1)

    keyboard = load_keyboard(input_path)
    sch = create_schematic(keyboard, output_path, switch_footprint, diode_footprint)
