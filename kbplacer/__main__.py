import argparse
import json
import logging

import pcbnew

from .board_modifier import Point, Side
from .key_placer import DiodePosition, KeyPlacer
from .template_copier import TemplateCopier

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Keyboard's key autoplacer")
    parser.add_argument(
        "-l", "--layout", required=True, help="json layout definition file"
    )
    parser.add_argument(
        "-b", "--board", required=True, help=".kicad_pcb file to be processed"
    )
    parser.add_argument(
        "-r", "--route", action="store_true", help="Enable experimental routing"
    )
    parser.add_argument("-d", "--diode-position", help="Relative diode position")
    parser.add_argument(
        "--key-distance",
        default=19.05,
        type=float,
        help="Key 1U distance, 19.05 mm by default",
    )
    parser.add_argument("-t", "--template", help="Controller circuit template")

    args = parser.parse_args()
    layout_path = args.layout
    board_path = args.board
    route_tracks = args.route
    diode_position = args.diode_position
    key_distance = args.key_distance
    template_path = args.template

    # set up logger
    logging.basicConfig(
        level=logging.DEBUG, format="%(asctime)s: %(message)s", datefmt="%H:%M:%S"
    )
    logger = logging.getLogger(__name__)

    board = pcbnew.LoadBoard(board_path)

    if layout_path:
        with open(layout_path, "r") as f:
            text_input = f.read()
            layout = json.loads(text_input)

        logger.info(f"User layout: {layout}")

        placer = KeyPlacer(logger, board, layout, key_distance)

        if diode_position == "USE_CURRENT":
            diode_position = placer.get_diode_position("SW{}", "D{}", True)
        elif diode_position == "NONE" or diode_position == "SKIP":
            diode_position = None
        elif diode_position is not None:
            x, y, orientation, side = diode_position.split(",")
            x, y = float(x), float(y)
            orientation = float(orientation)
            side = Side[side]
            diode_position = DiodePosition(Point(x, y), orientation, side)
        else:
            diode_position = placer.get_default_diode_position()

        placer.run("SW{}", "ST{}", "D{}", diode_position, route_tracks)

    if template_path:
        copier = TemplateCopier(logger, board, template_path, route_tracks)
        copier.run()

    pcbnew.Refresh()
    pcbnew.SaveBoard(board_path, board)

    logging.shutdown()
