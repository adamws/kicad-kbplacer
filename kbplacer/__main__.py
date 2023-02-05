import argparse
import json
import logging
import pcbnew

from .board_modifier import Point, Side
from .key_placer import DiodePosition, KeyPlacer
from .template_copier import TemplateCopier

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Keyboard's key autoplacer")
    parser.add_argument('-l', '--layout', required=True, help="json layout definition file")
    parser.add_argument('-b', '--board', required=True, help=".kicad_pcb file to be processed")
    parser.add_argument('-r', '--route', action="store_true", help="Enable experimental routing")
    parser.add_argument('-d', '--diode-position', help="Relative diode position")
    parser.add_argument('-t', '--template', help="Controller circuit template")

    args = parser.parse_args()
    layoutPath = args.layout
    boardPath = args.board
    routeTracks = args.route
    diodePosition = args.diode_position
    templatePath = args.template

    if routeTracks and diodePosition != None:
        parser.error("Routing with non-default diode position not supported yet")

    # set up logger
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s: %(message)s',
                        datefmt='%H:%M:%S')
    logger = logging.getLogger(__name__)

    board = pcbnew.LoadBoard(boardPath)

    if templatePath:
        copier = TemplateCopier(logger, board, templatePath, routeTracks)
        copier.Run()

    if layoutPath:
        with open(layoutPath, "r") as f:
            textInput = f.read()
            layout = json.loads(textInput)

        logger.info("User layout: {}".format(layout))

        placer = KeyPlacer(logger, board, layout)

        if diodePosition:
            x, y, orientation, side = diodePosition.split(",")
            x, y = float(x), float(y)
            orientation = float(orientation)
            side = Side[side]
            diodePosition = DiodePosition(Point(x, y), orientation, side)
        else:
            diodePosition = placer.GetDefaultDiodePosition()

        placer.Run("SW{}", "ST{}", "D{}", diodePosition, routeTracks)

    pcbnew.Refresh()
    pcbnew.SaveBoard(boardPath, board)

    logging.shutdown()
