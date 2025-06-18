# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import argparse
import logging
import os
import sys
from typing import List

import pcbnew

from . import __version__
from .defaults import DEFAULT_DIODE_POSITION, ZERO_POSITION
from .element_position import ElementInfo, ElementPosition, PositionOption, Side
from .kbplacer_plugin import PluginSettings, run

logger = logging.getLogger(__name__)


def check_annotation(value: str) -> None:
    if value.count("{}") != 1:
        err = (
            f"'{value}' invalid annotation specifier, "
            "it must contain exactly one '{}' placeholder."
        )
        raise ValueError(err)


class SwitchElementInfoAction(argparse.Action):
    """Simplified action producing ElementInfo which always use
    `PositionOption.DEFAULT` and `ElementPosition` with x and y 0, i.e. the only
    variable (configurable) parameters are annotation, orientation and side
    """

    def __call__(self, parser, namespace, values: str, option_string=None) -> None:
        try:
            value: ElementInfo = self.parse(values, option_string)
        except ValueError as e:
            raise argparse.ArgumentTypeError(str(e))
        setattr(namespace, self.dest, value)

    def parse(self, values: str, option_string) -> ElementInfo:
        tokens: list[str] = values.split()
        err = ""
        if len(tokens) not in [1, 3]:
            err = f"{option_string} invalid format."
            raise ValueError(err)

        annotation = tokens[0]
        check_annotation(annotation)

        if len(tokens) > 1:
            orientation = float(tokens[1])
            side = Side.get(tokens[2])
        else:
            orientation = 0
            side = Side.FRONT

        return ElementInfo(
            annotation,
            PositionOption.DEFAULT,
            ElementPosition(0, 0, orientation, side),
            "",
        )


class ElementInfoAction(argparse.Action):
    def __call__(self, parser, namespace, values: str, option_string=None) -> None:
        try:
            value: ElementInfo = self.parse(values, option_string)
        except ValueError as e:
            raise argparse.ArgumentTypeError(str(e))
        setattr(namespace, self.dest, value)

    def parse(self, values: str, option_string) -> ElementInfo:
        tokens: list[str] = values.split()
        err = ""
        if len(tokens) not in [2, 3, 6]:
            err = f"{option_string} invalid format."
            raise ValueError(err)

        annotation = tokens[0]
        check_annotation(annotation)

        option = PositionOption.get(tokens[1])
        position = None
        template_path = ""

        if len(tokens) == 2:
            if option not in [
                PositionOption.RELATIVE,
                PositionOption.DEFAULT,
                PositionOption.UNCHANGED,
            ]:
                err = (
                    f"{option_string} position option needs to be equal "
                    "RELATIVE or DEFAULT if position details not provided"
                )
                raise ValueError(err)
        elif len(tokens) == 3:
            if option not in [PositionOption.PRESET, PositionOption.RELATIVE]:
                err = (
                    f"{option_string} position option needs to be equal "
                    "RELATIVE or PRESET when providing template path"
                )
                raise ValueError(err)
        elif option != PositionOption.CUSTOM:
            err = (
                f"{option_string} position option needs to be equal CUSTOM "
                "when providing position details"
            )
            raise ValueError(err)

        if option == PositionOption.CUSTOM:
            floats = tuple(map(float, tokens[2:5]))
            side = Side.get(tokens[5])
            position = ElementPosition(floats[0], floats[1], floats[2], side)
        elif option == PositionOption.RELATIVE:
            # template path is optional for RELATIVE option:
            if len(tokens) == 3:
                template_path = tokens[2]
        elif option == PositionOption.PRESET:
            template_path = tokens[2]

        value: ElementInfo = ElementInfo(
            annotation,
            option,
            position,
            template_path,
        )
        return value


class ElementInfoListAction(ElementInfoAction):
    def __call__(self, parser, namespace, values: str, option_string=None) -> None:
        try:
            if "DEFAULT" in values:
                msg = f"{option_string} does not support DEFAULT position"
                raise ValueError(msg)
            value: List[ElementInfo] = []
            tokens: list[str] = values.split(";")
            for token in tokens:
                element_info: ElementInfo = super().parse(token.strip(), option_string)
                value.append(element_info)
        except ValueError as e:
            raise argparse.ArgumentTypeError(str(e))
        setattr(namespace, self.dest, value)


class XYAction(argparse.Action):
    def __call__(self, parser, namespace, values: str, option_string=None) -> None:
        try:
            value = tuple(map(float, values.split()))
            if len(value) != 2:
                msg = (
                    f"{option_string} must be exactly two numeric values "
                    "separated by a space."
                )
                raise ValueError(msg)
        except ValueError as e:
            raise argparse.ArgumentTypeError(str(e))
        setattr(namespace, self.dest, value)


def app() -> None:
    parser = argparse.ArgumentParser(
        description="Keyboard's key autoplacer",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "-b",
        "--board",
        required=True,
        help=".kicad_pcb file to be processed or created",
    )
    parser.add_argument(
        "-l", "--layout", required=False, default="", help="json layout definition file"
    )
    parser.add_argument(
        "--route-switches-with-diodes",
        action="store_true",
        help="Enable switch-diode routing",
    )
    parser.add_argument(
        "--route-rows-and-columns",
        action="store_true",
        help="Enable rows/columns routing",
    )
    parser.add_argument(
        "-s",
        "--switch",
        default=ElementInfo("SW{}", PositionOption.DEFAULT, ZERO_POSITION, ""),
        action=SwitchElementInfoAction,
        help=(
            "Switch information, space separated value of ANNOTATION [ORIENTATION SIDE]\n"
            "where ANNOTATION is footprint annotation string with '{}' placeholder,\n"
            "ORIENTATION is numeric value of reference orientation for each footprint\n"
            "and SIDE is either FRONT or BACK\n"
            "When only ANNOTATION defined, then orientation is 0 and side is FRONT\n"
            "for example:\n"
            "\tSW{}\n"
            "\tSW{} 0 FRONT\n"
            "\tSW{} 90 BACK\n"
            "equal 'SW{} 0 FRONT' by default"
        ),
    )
    parser.add_argument(
        "-d",
        "--diode",
        default=ElementInfo("D{}", PositionOption.DEFAULT, DEFAULT_DIODE_POSITION, ""),
        action=ElementInfoAction,
        help=(
            "Diode information, space separated value of ANNOTATION OPTION [POSITION]\n"
            "Available OPTION choices: DEFAULT, UNCHANGED, RELATIVE, PRESET and CUSTOM\n"
            "When DEFAULT or UNCHAGED, then POSITION needs to be omitted,\n"
            "when RELATIVE, then POSITION is optional path for saving kicad_pcb template file\n"
            "when PRESET, then POSITION is mandatory path to kicad_pcb template file\n"
            "when CUSTOM, then POSITION is space separated value of X Y ORIENTATION FRONT|BACK\n"
            "for example:\n"
            "\tD{} RELATIVE\n"
            "\tD{} PRESET /home/user/project/diode_preset.kicad_pcb\n"
            "\tD{} CUSTOM 5 -4.5 90 BACK\n"
            "equal 'D{} DEFAULT' by default"
        ),
    )
    parser.add_argument(
        "--additional-elements",
        default=[
            ElementInfo(
                "ST{}",
                PositionOption.CUSTOM,
                ZERO_POSITION,
                "",
            )
        ],
        action=ElementInfoListAction,
        help=(
            "List of ';' separated additional elements ELEMENT_INFO values\n"
            "ELEMENT_INFO is space separated value of ANNOTATION OPTION POSITION\n"
            "Available OPTION choices: RELATIVE, PRESET and CUSTOM\n"
            "when RELATIVE, then POSITION is optional path for saving kicad_pcb template file\n"
            "when PRESET, then POSITION is mandatory path to kicad_pcb template file\n"
            "when CUSTOM, then POSITION is space separated value of X Y ORIENTATION FRONT|BACK\n"
            "for example:\n"
            "\tST{} CUSTOM 0 0 180 BACK;LED{} RELATIVE\n"
            "equal 'ST{} CUSTOM 0 0 0 FRONT' by default"
        ),
    )
    parser.add_argument(
        "--key-distance",
        default=(19.05, 19.05),
        action=XYAction,
        help=(
            "X and Y key 1U distance in mm, as two space separated numeric values, "
            "19.05 19.05 by default"
        ),
    )
    parser.add_argument(
        "-t",
        "--template",
        required=False,
        default="",
        help="Controller circuit template",
    )
    parser.add_argument(
        "--build-board-outline",
        required=False,
        action="store_true",
        help="Enables board outline generation around switch footprints.",
    )
    parser.add_argument(
        "--outline-delta",
        required=False,
        default=0.0,
        type=float,
        help="The amount (in millimetres) to inflate/deflate board outline.",
    )
    parser.add_argument(
        "--create-from-annotated-layout",
        required=False,
        action="store_true",
        help=(
            "Enables experimental creation mode, where via-annotated kle layout is used\n"
            "for adding footprints and netlists to the newly created board file.\n"
        ),
    )
    parser.add_argument(
        "--switch-footprint",
        required=False,
        default="",
        type=str,
        help=(
            "Full path to switch footprint, required when "
            "`--create-from-annotated-layout` option used."
        ),
    )
    parser.add_argument(
        "--diode-footprint",
        required=False,
        default="",
        type=str,
        help=(
            "Full path to diode footprint, required when "
            "`--create-from-annotated-layout` option used."
        ),
    )
    parser.add_argument(
        "--log-level",
        required=False,
        default="WARNING",
        choices=logging._nameToLevel.keys(),
        type=str,
        help="Provide logging level, default=%(default)s",
    )
    parser.add_argument(
        "--optimize-diodes-orientation",
        action="store_true",
        help=(
            "Enables automatic diode orientation adjustment based on distance\n"
            "between diode and corresponding switch."
        ),
    )

    args = parser.parse_args()

    layout_path = args.layout
    board_path = args.board

    # set up logger
    logging.basicConfig(
        level=args.log_level, format="%(asctime)s: %(message)s", datefmt="%H:%M:%S"
    )

    if args.create_from_annotated_layout and os.path.isfile(board_path):
        logger.error(f"File {board_path} already exist, aborting")
        sys.exit(1)

    settings = PluginSettings(
        board_path=board_path,
        layout_path=layout_path,
        key_info=args.switch,
        key_distance=args.key_distance,
        diode_info=args.diode,
        route_switches_with_diodes=args.route_switches_with_diodes,
        optimize_diodes_orientation=args.optimize_diodes_orientation,
        route_rows_and_columns=args.route_rows_and_columns,
        additional_elements=args.additional_elements,
        generate_outline=args.build_board_outline,
        outline_delta=args.outline_delta,
        template_path=args.template,
        create_from_annotated_layout=args.create_from_annotated_layout,
        switch_footprint=args.switch_footprint,
        diode_footprint=args.diode_footprint,
    )
    board = run(settings)

    pcbnew.Refresh()
    pcbnew.SaveBoard(board_path, board)

    logging.shutdown()


if __name__ == "__main__":
    app()
