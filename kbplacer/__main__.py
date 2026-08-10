# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import List

import pcbnew

from . import __version__
from .defaults import DEFAULT_DIODE_POSITION, ZERO_POSITION
from .element_position import ElementInfo, ElementPosition, PositionOption, Side
from .footprint_loader import FootprintIdentifier
from .kbplacer_plugin import PluginSettings, run_board, run_schematic
from .kle_serial import get_keyboard_from_file, keyboard_to_url
from .schematic_project import (
    hierarchical_root_filename,
    plan_sheet_filenames,
    resolve_bundle_strategy,
)

logger = logging.getLogger(__name__)


def check_annotation(value: str) -> None:
    if value.count("{}") != 1:
        err = (
            f"'{value}' invalid annotation specifier, "
            "it must contain exactly one '{}' placeholder."
        )
        raise ValueError(err)


class FootprintIdentifierAction(argparse.Action):
    """Validates footprint identifier format.

    Expected format: path/to/library.pretty:FootprintName
    """

    def __call__(self, parser, namespace, values: str, option_string=None) -> None:
        try:
            value = self.validate(values, option_string)
        except ValueError as e:
            raise argparse.ArgumentTypeError(str(e))
        setattr(namespace, self.dest, value)

    def validate(self, value: str, option_string) -> str:
        if not value:  # Allow empty string (default value)
            return value

        # Pre-validate to provide better error messages
        if value.count(":") < 1:
            err = (
                f"'{value}' invalid footprint identifier, "
                "it must contain at least one ':' separator."
            )
            raise ValueError(err)

        # Check for Windows path that's missing second colon
        if len(value) >= 3 and value[1:3] == ":\\":
            second_colon_pos = value.find(":", 2)
            if second_colon_pos == -1:
                err = (
                    f"'{value}' invalid footprint identifier, "
                    "Windows path must contain ':' separator after library path."
                )
                raise ValueError(err)

        # Use FootprintIdentifier to parse and validate format
        try:
            identifier = FootprintIdentifier.from_str(value)
        except ValueError as e:
            # Re-raise with original error message from FootprintIdentifier
            raise ValueError(str(e))

        # CLI-specific validations
        if not identifier.library_path.endswith(".pretty"):
            err = (
                f"'{value}' invalid footprint identifier, "
                "library path must end with '.pretty'."
            )
            raise ValueError(err)

        if not identifier.footprint_name:
            err = (
                f"'{value}' invalid footprint identifier, "
                "footprint name cannot be empty."
            )
            raise ValueError(err)

        return value


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
        "--pcb-file",
        required=False,
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
        default=None,
        action=XYAction,
        help=(
            "X and Y key 1U distance in mm, as two space separated numeric values.\n"
            "If not specified, uses spacing from keyboard metadata or defaults to 19.05 19.05"
        ),
    )
    parser.add_argument(
        "--layout-offset",
        default=None,
        action=XYAction,
        help=(
            "X and Y placement offset for the keyboard layout in mm, "
            "as two space separated numeric values.\n"
            "If not specified, offset is auto-calculated to align the first key to a grid\n"
            "with an offset to avoid pcbnew's Drawing Sheet borders."
        ),
    )
    parser.add_argument(
        "--encoder-adjustment",
        default=None,
        action=XYAction,
        help=(
            "X and Y adjustment offset for encoder footprints in mm, "
            "as two space separated numeric values.\n"
            "Applied to encoder keys (sm='rot_ec11') to compensate for "
            "the footprint reference point not being at the body center.\n"
            'For example: --encoder-adjustment "-7.5 -2.5"'
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
        "--create-pcb-file",
        required=False,
        action="store_true",
        help=(
            "Enables experimental creation mode, where via-annotated kle layout is used\n"
            "for adding footprints and netlists to the newly created board file."
        ),
    )
    parser.add_argument(
        "--create-led-pcb-elements",
        required=False,
        action="store_true",
        help=(
            "Adds one LED and one decoupling capacitor footprint per unique key\n"
            "position to the board created by `--create-pcb-file`.\n"
            "Requires `--create-pcb-file`, `--led-footprint` and `--led-capacitor-footprint`.\n"
            "Positioning of the created footprints is controlled via\n"
            '`--additional-elements`, e.g. "LED{} RELATIVE;C{} RELATIVE"'
        ),
    )
    parser.add_argument(
        "--create-sch-file",
        required=False,
        action="store_true",
        help=(
            "Creates key matrix schematic out of via-annotated kle layout, bundled\n"
            "into a KiCad project (a `.kicad_pro` is always written alongside it).\n"
            "Requires kbplacer installation with optional `schematic` dependencies."
        ),
    )
    parser.add_argument(
        "--sch-file",
        required=False,
        default="",
        help=(
            ".kicad_sch file to be created if `--create-sch-file` option used.\n"
            "Using `--pcb-file` path with extension changed to `.kicad_sch` if not defined.\n"
            "Its basename (or `--pcb-file`'s, when given) also becomes the project's\n"
            "basename; if `--create-led-sch-file` is also used, that sheet is named\n"
            "`<basename>-led-chain.kicad_sch` regardless of `--led-sch-file`'s value."
        ),
    )
    parser.add_argument(
        "--create-led-sch-file",
        required=False,
        action="store_true",
        help=(
            "Creates the LED-chain schematic sheet (LEDs, decoupling capacitors\n"
            "unless `--skip-led-decoupling`, per-LED VCC/GND, and the DIN/DOUT\n"
            "daisy chain), bundled into the same KiCad project as `--create-sch-file`.\n"
            "Requires KiCad 9.0 or higher, whether used alone or together with\n"
            "`--create-sch-file`."
        ),
    )
    parser.add_argument(
        "--led-sch-file",
        required=False,
        default="",
        help=(
            ".kicad_sch file to be created if `--create-led-sch-file` option used\n"
            "and no other schematic type is requested (its basename becomes the\n"
            "project's basename in that case). Ignored otherwise."
        ),
    )
    parser.add_argument(
        "--bundle-strategy",
        required=False,
        default=None,
        choices=["flat", "hierarchical"],
        help=(
            "How multiple requested schematic sheets are tied together into one\n"
            "KiCad project. `flat`: every sheet is its own top-level sheet, linked\n"
            "purely through the `.kicad_pro` (KiCad 10.0+ only, when more than one\n"
            "sheet is requested). `hierarchical`: a root `.kicad_sch` containing\n"
            "references to each requested sheet, in the traditional KiCad\n"
            "hierarchical-sheet style (KiCad 9.0+). Defaults to auto-selecting\n"
            "`flat` on KiCad 10.0+ and `hierarchical` below that. Ignored when a\n"
            "single sheet type is requested (nothing to bundle)."
        ),
    )
    parser.add_argument(
        "--switch-footprint",
        required=False,
        default="",
        action=FootprintIdentifierAction,
        help=(
            "Switch footprint identifier.\n"
            "Identifier is constructed by concatenating path to library directory\n"
            "with ':' and footprint name (without file extension), for example:\n"
            "/usr/share/kicad/footprints/Button_Switch_Keyboard.pretty:SW_Cherry_MX_1.00u_PCB\n"
            "Required when `--create-pcb-file` or `--create-sch-file` options used."
        ),
    )
    parser.add_argument(
        "--diode-footprint",
        required=False,
        default="",
        action=FootprintIdentifierAction,
        help=(
            "Diode footprint identifier.\n"
            "Identifier is constructed by concatenating path to library directory\n"
            "with ':' and footprint name (without file extension), for example:\n"
            "/usr/share/kicad/footprints/Diode_SMD.pretty:D_SOD-123F\n"
            "Required when `--create-pcb-file` or `--create-sch-file` options used."
        ),
    )
    parser.add_argument(
        "--stabilizer-footprint",
        required=False,
        default="",
        action=FootprintIdentifierAction,
        help=(
            "Switch stabilizer footprint identifier.\n"
            "Follows same semantic as --switch-footprint option.\n"
        ),
    )
    parser.add_argument(
        "--encoder-footprint",
        required=False,
        default="",
        action=FootprintIdentifierAction,
        help=(
            "Encoder footprint identifier.\n"
            "Follows same semantic as --switch-footprint option.\n"
            "Required when `--create-pcb-file` or `--create-sch-file` is used\n"
            "with a layout containing encoders."
        ),
    )
    parser.add_argument(
        "--led-footprint",
        required=False,
        default="",
        action=FootprintIdentifierAction,
        help=(
            "LED footprint identifier.\n"
            "Follows same semantic as --switch-footprint option.\n"
            "Only SK6812MINI-E-pinout-compatible footprints are supported\n"
            "(pad 1=GND, 2=DIN, 3=VCC, 4=DOUT).\n"
            "Required when `--create-led-pcb-elements` is used; also applied\n"
            "to the LED-chain schematic's Footprint field when\n"
            "`--create-led-sch-file` is used (that path requires KiCad 9.0\n"
            "or higher, see `--create-led-sch-file`; `--create-led-pcb-elements`\n"
            "has no such requirement)."
        ),
    )
    parser.add_argument(
        "--led-capacitor-footprint",
        required=False,
        default="",
        action=FootprintIdentifierAction,
        help=(
            "Decoupling capacitor footprint identifier for the LED chain.\n"
            "Follows same semantic as --switch-footprint option.\n"
            "Required when `--create-led-pcb-elements` is used, unless\n"
            "`--skip-led-decoupling` is also given; also applied to the\n"
            "LED-chain schematic's Footprint field when `--create-led-sch-file`\n"
            "is used (that path requires KiCad 9.0 or higher, see\n"
            "`--create-led-sch-file`; `--create-led-pcb-elements` has no such\n"
            "requirement)."
        ),
    )
    parser.add_argument(
        "--skip-led-decoupling",
        required=False,
        action="store_true",
        help=(
            "Do not create per-LED decoupling capacitors when building the\n"
            "LED-chain schematic (`--create-led-sch-file`, which requires\n"
            "KiCad 9.0 or higher) or PCB elements (`--create-led-pcb-elements`,\n"
            "which has no such requirement). Decoupling is recommended but\n"
            "often skipped in practice."
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
        "--log-format",
        required=False,
        default="%(asctime)s: %(message)s",
        type=str,
        help="Provide logging format, default='%(default)s'",
    )
    parser.add_argument(
        "--optimize-diodes-orientation",
        action="store_true",
        help=(
            "Enables automatic diode orientation adjustment based on distance\n"
            "between diode and corresponding switch."
        ),
    )
    parser.add_argument(
        "--start-index",
        required=False,
        default=1,
        type=int,
        help=(
            "Starting index for footprint numbering (default: %(default)s).\n"
            "Controls which number to use when matching the first switch footprint.\n"
            "Example: --start-index 0 starts from SW0 instead of SW1."
        ),
    )
    parser.add_argument(
        "--no-stabilizers",
        dest="add_stabilizers",
        action="store_false",
        help=(
            "Disable stabilizer creation when using `--create-pcb-file` or\n"
            "`--create-sch-file` options."
        ),
    )
    parser.add_argument(
        "--max-keys",
        required=False,
        default=None,
        type=int,
        help=argparse.SUPPRESS,
    )

    args = parser.parse_args()

    layout_path = args.layout
    pcb_file_path = args.pcb_file

    # set up logger
    logging.basicConfig(
        level=args.log_level, format=args.log_format, datefmt="%H:%M:%S"
    )

    if args.create_pcb_file and os.path.isfile(pcb_file_path):
        logger.error(f"File {pcb_file_path} already exist, aborting")
        sys.exit(1)

    if args.create_led_pcb_elements and not args.create_pcb_file:
        logger.error("--create-led-pcb-elements requires --create-pcb-file")
        sys.exit(1)

    if args.create_led_pcb_elements and not args.led_footprint:
        logger.error(
            "--led-footprint is required when --create-led-pcb-elements is used"
        )
        sys.exit(1)

    if (
        args.create_led_pcb_elements
        and not args.skip_led_decoupling
        and not args.led_capacitor_footprint
    ):
        logger.error(
            "--led-capacitor-footprint is required when --create-led-pcb-elements "
            "is used, unless --skip-led-decoupling is also given"
        )
        sys.exit(1)

    requested_sheet_types = []
    if args.create_sch_file:
        requested_sheet_types.append("key_matrix")
    if args.create_led_sch_file:
        requested_sheet_types.append("led_chain")

    if requested_sheet_types:
        # Project basename: `--pcb-file`'s stem when given (matching today's
        # `--sch-file` default-derivation precedent), otherwise whichever
        # explicit schematic path was given, in priority order.
        if pcb_file_path:
            basename_source = pcb_file_path
        elif args.create_sch_file and args.sch_file:
            basename_source = args.sch_file
        elif args.create_led_sch_file and args.led_sch_file:
            basename_source = args.led_sch_file
        else:
            basename_source = None

        if not basename_source:
            logger.error(
                "Could not determine project basename: provide --pcb-file, "
                "--sch-file, or --led-sch-file"
            )
            sys.exit(1)

        basename_path = Path(basename_source)
        project_basename = basename_path.stem
        project_dir = basename_path.parent
        project_path = str(project_dir / f"{project_basename}.kicad_pro")

        resolved_strategy = resolve_bundle_strategy(args.bundle_strategy)
        planned_filenames = dict(
            plan_sheet_filenames(
                project_basename, requested_sheet_types, strategy=resolved_strategy
            )
        )
        sch_path = (
            str(project_dir / planned_filenames["key_matrix"])
            if args.create_sch_file
            else ""
        )
        led_sch_path = (
            str(project_dir / planned_filenames["led_chain"])
            if args.create_led_sch_file
            else ""
        )

        existence_checks = [
            project_dir / filename for filename in planned_filenames.values()
        ] + [Path(project_path)]
        if resolved_strategy == "hierarchical" and len(requested_sheet_types) > 1:
            existence_checks.append(
                project_dir / hierarchical_root_filename(project_basename)
            )

        for output_path in existence_checks:
            if output_path.is_file():
                logger.error(f"File {output_path} already exist, aborting")
                sys.exit(1)
    else:
        sch_path = ""
        led_sch_path = ""
        project_path = ""

    if layout_path:
        keyboard = get_keyboard_from_file(layout_path)
        keyboard_url = keyboard_to_url(keyboard)

        logger.info(f"User layout: {keyboard_url}")

        # Validate max-keys if specified
        if args.max_keys is not None:
            try:
                num_keys = len(keyboard.keys)
            except Exception as e:
                logger.error(f"Failed to validate layout: {e}")
                sys.exit(1)

            if num_keys > args.max_keys:
                logger.error(
                    f"Layout has {num_keys} keys, which exceeds the maximum of {args.max_keys}"
                )
                sys.exit(1)

    args.switch.start_index = args.start_index

    settings = PluginSettings(
        pcb_file_path=pcb_file_path,
        layout_path=layout_path,
        key_info=args.switch,
        key_distance=args.key_distance,
        layout_offset=args.layout_offset,
        diode_info=args.diode,
        route_switches_with_diodes=args.route_switches_with_diodes,
        optimize_diodes_orientation=args.optimize_diodes_orientation,
        route_rows_and_columns=args.route_rows_and_columns,
        additional_elements=args.additional_elements,
        generate_outline=args.build_board_outline,
        outline_delta=args.outline_delta,
        template_path=args.template,
        create_pcb_file=args.create_pcb_file,
        create_sch_file=args.create_sch_file,
        sch_file_path=sch_path,
        switch_footprint=args.switch_footprint,
        diode_footprint=args.diode_footprint,
        stabilizer_footprint=args.stabilizer_footprint,
        encoder_footprint=args.encoder_footprint,
        add_stabilizers=args.add_stabilizers,
        encoder_adjustment=args.encoder_adjustment,
        create_led_sch_file=args.create_led_sch_file,
        led_sch_file_path=led_sch_path,
        project_path=project_path,
        led_footprint=args.led_footprint,
        cap_footprint=args.led_capacitor_footprint,
        create_led_pcb_elements=args.create_led_pcb_elements,
        skip_led_decoupling=args.skip_led_decoupling,
        bundle_strategy=args.bundle_strategy,
    )

    if args.create_sch_file or args.create_led_sch_file:
        run_schematic(settings)

    if pcb_file_path:
        board = run_board(settings)

        pcbnew.Refresh()
        pcbnew.SaveBoard(pcb_file_path, board)

    logging.shutdown()


if __name__ == "__main__":
    app()
