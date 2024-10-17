import argparse
import json
import logging
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml
from skip import Schematic

from kbplacer.kle_serial import MatrixAnnotatedKeyboard, get_keyboard

logger = logging.getLogger(__name__)

ORIGIN = (18, 18)
UNIT = 1.27

COLUMN_DISTANCE = 10
ROW_DISTANCE = 16

TEMPLATE = """(kicad_sch (version 20230121) (generator eeschema) (uuid 9e45a776-7007-48ff-b543-dc98423173b7) (paper "{page_size}")(lib_symbols (symbol "Device:D_Small" (pin_numbers hide) (pin_names (offset 0.254) hide) (in_bom yes) (on_board yes) (property "Reference" "D" (at -1.27 2.032 0) (effects (font (size 1.27 1.27)) (justify left))) (property "Value" "D_Small" (at -3.81 -2.032 0) (effects (font (size 1.27 1.27)) (justify left))) (property "Footprint" "" (at 0 0 90) (effects (font (size 1.27 1.27)) hide)) (property "Datasheet" "~" (at 0 0 90) (effects (font (size 1.27 1.27)) hide)) (property "Sim.Device" "D" (at 0 0 0) (effects (font (size 1.27 1.27)) hide)) (property "Sim.Pins" "1=K 2=A" (at 0 0 0) (effects (font (size 1.27 1.27)) hide)) (property "ki_keywords" "diode" (at 0 0 0) (effects (font (size 1.27 1.27)) hide)) (property "ki_description" "Diode, small symbol" (at 0 0 0) (effects (font (size 1.27 1.27)) hide)) (property "ki_fp_filters" "TO-???* *_Diode_* *SingleDiode* D_*" (at 0 0 0) (effects (font (size 1.27 1.27)) hide)) (symbol "D_Small_0_1" (polyline (pts (xy -0.762 -1.016) (xy -0.762 1.016)) (stroke (width 0.254) (type default)) (fill (type none))) (polyline (pts (xy -0.762 0) (xy 0.762 0)) (stroke (width 0) (type default)) (fill (type none))) (polyline (pts (xy 0.762 -1.016) (xy -0.762 0) (xy 0.762 1.016) (xy 0.762 -1.016)) (stroke (width 0.254) (type default)) (fill (type none)))) (symbol "D_Small_1_1" (pin passive line (at -2.54 0 0) (length 1.778) (name "K" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27))))) (pin passive line (at 2.54 0 180) (length 1.778) (name "A" (effects (font (size 1.27 1.27)))) (number "2" (effects (font (size 1.27 1.27))))))) (symbol "Switch:SW_Push_45deg" (pin_numbers hide) (pin_names (offset 1.016) hide) (in_bom yes) (on_board yes) (property "Reference" "SW" (at 3.048 1.016 0) (effects (font (size 1.27 1.27)) (justify left))) (property "Value" "SW_Push_45deg" (at 0 -3.81 0) (effects (font (size 1.27 1.27)))) (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide)) (property "Datasheet" "~" (at 0 0 0) (effects (font (size 1.27 1.27)) hide)) (property "ki_keywords" "switch normally-open pushbutton push-button" (at 0 0 0) (effects (font (size 1.27 1.27)) hide)) (property "ki_description" "Push button switch, normally open, two pins, 45° tilted" (at 0 0 0) (effects (font (size 1.27 1.27)) hide)) (symbol "SW_Push_45deg_0_1" (circle (center -1.1684 1.1684) (radius 0.508) (stroke (width 0) (type default)) (fill (type none))) (polyline (pts (xy -0.508 2.54) (xy 2.54 -0.508)) (stroke (width 0) (type default)) (fill (type none))) (polyline (pts (xy 1.016 1.016) (xy 2.032 2.032)) (stroke (width 0) (type default)) (fill (type none))) (polyline (pts (xy -2.54 2.54) (xy -1.524 1.524) (xy -1.524 1.524)) (stroke (width 0) (type default)) (fill (type none))) (polyline (pts (xy 1.524 -1.524) (xy 2.54 -2.54) (xy 2.54 -2.54) (xy 2.54 -2.54)) (stroke (width 0) (type default)) (fill (type none))) (circle (center 1.143 -1.1938) (radius 0.508) (stroke (width 0) (type default)) (fill (type none))) (pin passive line (at -2.54 2.54 0) (length 0) (name "1" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27))))) (pin passive line (at 2.54 -2.54 180) (length 0) (name "2" (effects (font (size 1.27 1.27)))) (number "2" (effects (font (size 1.27 1.27)))))))) (symbol (lib_id "Switch:SW_Push_45deg") (at 0 0 0) (unit 1) (in_bom yes) (on_board yes) (dnp no) (uuid 19751ded-3cc5-4b31-aeeb-fd1357dc1d55) (property "Reference" "SW1" (at 0 -5.08 0) (effects (font (size 1.27 1.27)))) (property "Value" "SW_Push" (at 0 -3.81 0) (effects (font (size 1.27 1.27)) hide)) (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide)) (property "Datasheet" "~" (at 0 0 0) (effects (font (size 1.27 1.27)) hide)) (pin "1" (uuid 94c53fa6-dd8d-4e6d-9c1a-277431558d0a)) (pin "2" (uuid ef827767-19b4-4ee5-b4b6-65189b88f8ee)) (instances (project "template" (path "/9e45a776-7007-48ff-b543-dc98423173b7" (reference "SW1") (unit 1))))) (symbol (lib_id "Device:D_Small") (at 2.54 6.35 90) (unit 1) (in_bom yes) (on_board yes) (dnp no) (uuid feb0fa1f-f7ed-4393-bef6-632a7fa048d6) (property "Reference" "D1" (at 3.81 5.08 90) (effects (font (size 1.27 1.27)) (justify right))) (property "Value" "D" (at 3.81 7.62 90) (effects (font (size 1.27 1.27)) (justify right) hide)) (property "Footprint" "" (at 2.54 6.35 90) (effects (font (size 1.27 1.27)) hide)) (property "Datasheet" "~" (at 2.54 6.35 90) (effects (font (size 1.27 1.27)) hide)) (property "Sim.Device" "D" (at 2.54 6.35 0) (effects (font (size 1.27 1.27)) hide)) (property "Sim.Pins" "1=K 2=A" (at 2.54 6.35 0) (effects (font (size 1.27 1.27)) hide)) (pin "1" (uuid 004cc590-2791-46a0-9480-7962783605a4)) (pin "2" (uuid 428af732-f843-4705-863e-a0095a5fb80a)) (instances (project "template" (path "/9e45a776-7007-48ff-b543-dc98423173b7" (reference "D1") (unit 1))))) (sheet_instances (path "/" (page "1"))))"""


def _x(x: int) -> float:
    return (ORIGIN[0] * UNIT) + (x * UNIT)


def _y(y: int) -> float:
    return (ORIGIN[1] * UNIT) + (y * UNIT)


def load_keyboard(layout_path) -> MatrixAnnotatedKeyboard:
    with open(layout_path, "r", encoding="utf-8") as f:
        if layout_path.endswith("yaml") or layout_path.endswith("yml"):
            layout = yaml.safe_load(f)
        else:
            layout = json.load(f)
        _keyboard = get_keyboard(layout)
        if not isinstance(_keyboard, MatrixAnnotatedKeyboard):
            try:
                _keyboard = MatrixAnnotatedKeyboard(_keyboard.meta, _keyboard.keys)
            except Exception as e:
                msg = (
                    f"Layout from {_keyboard} is not convertible to "
                    "matrix annotated keyboard which is required for schematic create"
                )
                raise RuntimeError(msg) from e
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


def create_schematic(
    input_path, output_path, switch_footprint="", diode_footprint=""
) -> None:
    keyboard = load_keyboard(input_path)
    matrix = [
        (parse_annotation(pos[0])[1], parse_annotation(pos[1])[1])
        for pos in (
            MatrixAnnotatedKeyboard.get_matrix_position(k)
            for k in keyboard.keys_in_matrix_order()
        )
    ]

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
    if switch_footprint:
        base_switch.property.Footprint.value = switch_footprint
    base_diode = sch.symbol.reference_startswith("D")[0]
    if diode_footprint:
        base_diode.property.Footprint.value = diode_footprint

    progress: Dict[Tuple[int, int], List[str]] = defaultdict(list)

    current_ref = 1
    labels = set()

    for row, column in matrix:
        position = (row, column)
        logger.debug(f"row: {row} column: {column}")
        row_label = f"{row_label_prefix}{row}"
        column_label = f"{column_label_prefix}{column}"

        used_slots = len(progress[position])
        if used_slots > 3:
            # clamp to maximum value (use same slot for all 3+ alternative keys)
            # schematic readability will suffer but such layouts are uncommon anyway
            used_slots = 3

        switch = base_switch.clone()
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
        else:
            junc = sch.junction.new()
            junc.move(wire.end)

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
            else:
                junc = sch.junction.new()
                junc.move(wire.end)
            current_ref += 1

        progress[position].append(switch_reference)

    base_switch.delete()
    base_diode.delete()

    sch.write(output_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Keyboard layout to KiCad schematic",
    )

    parser.add_argument("-in", required=True, help="Layout file")
    parser.add_argument("-out", required=True, help="Output path")
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Override output if already exists",
    )
    parser.add_argument("-swf", required=False, help="Switch footprint")
    parser.add_argument("-df", required=False, help="Diode footprint")
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
    switch_footprint = getattr(args, "swf")
    diode_footprint = getattr(args, "df")

    # set up logger
    logging.basicConfig(
        level=args.log_level, format="%(asctime)s: %(message)s", datefmt="%H:%M:%S"
    )

    if force:
        shutil.rmtree(output_path, ignore_errors=True)
    elif Path(output_path).is_file():
        logger.error(f"Output file '{output_path}' already exists, exiting...")
        sys.exit(1)

    create_schematic(input_path, output_path, switch_footprint, diode_footprint)
