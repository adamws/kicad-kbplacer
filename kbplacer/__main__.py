import argparse
import json
import logging
import pcbnew

from typing import Optional, Tuple

from .defaults import DEFAULT_DIODE_POSITION
from .element_position import ElementPosition, Point, PositionOption, Side
from .key_placer import KeyPlacer
from .template_copier import TemplateCopier


class ElementInfoAction(argparse.Action):
    def __call__(self, parser, namespace, values: str, option_string=None) -> None:
        tokens: list[str] = values.split()
        err = ""
        if len(tokens) != 2 and len(tokens) != 6:
            err = f"{option_string} invalid format."
            raise ValueError(err)
        else:
            annotation = tokens[0]
            if annotation.count("{}") != 1:
                err = (
                    f"'{annotation}' invalid annotation specifier, "
                    "it must contain eqactly one '{}' placeholder."
                )
                raise ValueError(err)

            option = PositionOption.get(tokens[1])
            position = None
            if len(tokens) == 2:
                if (
                    option != PositionOption.CURRENT_RELATIVE
                    and option != PositionOption.DEFAULT
                ):
                    err = (
                        f"{option_string} positon option needs to be equal CURRENT_RELATIVE or DEFAULT "
                        "if position details not provided"
                    )
                    raise ValueError(err)
            else:
                if option != PositionOption.CUSTOM:
                    err = (
                        f"{option_string} position option needs to be equal CUSTOM "
                        "when providing position details"
                    )
                    raise ValueError(err)
                else:
                    floats = tuple(map(float, tokens[2:5]))
                    side = Side.get(tokens[5])
                    position = ElementPosition(
                        Point(floats[0], floats[1]), floats[2], side
                    )

            value: Tuple[str, PositionOption, Optional[ElementPosition]] = (
                annotation,
                option,
                position,
            )
            setattr(namespace, self.dest, value)


class XYAction(argparse.Action):
    def __call__(self, parser, namespace, values: str, option_string=None) -> None:
        try:
            value = tuple(map(float, values.split()))
            if len(value) != 2:
                msg = f"{option_string} must be exactly two numeric values separated by a space."
                raise ValueError(msg)
        except ValueError as e:
            raise argparse.ArgumentTypeError(str(e))
        setattr(namespace, self.dest, value)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Keyboard's key autoplacer",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "-l", "--layout", required=True, help="json layout definition file"
    )
    parser.add_argument(
        "-b", "--board", required=True, help=".kicad_pcb file to be processed"
    )
    parser.add_argument(
        "-r", "--route", action="store_true", help="Enable experimental routing"
    )
    parser.add_argument(
        "-d",
        "--diode",
        default=("D{}", PositionOption.DEFAULT, None),
        action=ElementInfoAction,
        help=(
            "Diode information, space separated value of ANNOTATION POSITION_OPTION [POSITION].\n"
            "Avaiable POSITION_OPTION choices: DEFAULT, CURRENT_RELATIVE and CUSTOM\n"
            "When DEFAULT of CURRENT_RELATIVE, then POSITION needs to be ommited,\n"
            "when CUSTOM then POSITION is space separated value of X Y ORIENTATION FRONT|BACK\n"
            "for example:\n"
            "\tD{} DEFAULT\n"
            "\tD{} CUSTOM 5 -4.5 90 BACK"
        ),
    )
    parser.add_argument(
        "--key-distance",
        default=(19.05, 19.05),
        action=XYAction,
        help="X and Y key 1U distance in mm, as two space separated numeric values, 19.05 19.05 by default",
    )
    parser.add_argument("-t", "--template", help="Controller circuit template")

    args = parser.parse_args()
    layout_path = args.layout
    board_path = args.board
    route_tracks = args.route
    diode = args.diode
    key_distance = args.key_distance
    template_path = args.template

    # set up logger
    logging.basicConfig(
        level=logging.DEBUG, format="%(asctime)s: %(message)s", datefmt="%H:%M:%S"
    )
    logger = logging.getLogger(__name__)

    board = pcbnew.LoadBoard(board_path)

    if layout_path:
        with open(layout_path, "r") as footprint:
            text_input = footprint.read()
            layout = json.loads(text_input)

        logger.info(f"User layout: {layout}")

        placer = KeyPlacer(logger, board, layout, key_distance)

        if diode[1] == PositionOption.CURRENT_RELATIVE:
            diode_position = placer.get_current_relative_element_position(
                "SW{}", diode[0]
            )
        elif diode[1] == PositionOption.DEFAULT:
            diode_position = DEFAULT_DIODE_POSITION
        elif diode[1] == PositionOption.CUSTOM:
            diode_position = diode[2]
        else:
            msg = f"Unsupported position option found: {diode[1]}"
            raise ValueError(msg)

        additional_elements = [("ST{}", ElementPosition(Point(0, 0), 0, Side.FRONT))]
        placer.run(
            "SW{}",
            diode[0],
            diode_position,
            route_tracks,
            additional_elements=additional_elements,
        )

    if template_path:
        copier = TemplateCopier(logger, board, template_path, route_tracks)
        copier.run()

    pcbnew.Refresh()
    pcbnew.SaveBoard(board_path, board)

    logging.shutdown()
