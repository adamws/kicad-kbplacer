from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Tuple

import pcbnew
import wx

from .kbplacer_dialog import KbplacerDialog
from .key_placer import KeyPlacer
from .template_copier import TemplateCopier

logger = logging.getLogger(__name__)


def load_window_state(filepath: str) -> Tuple[Any, bool]:
    with open(filepath, "r") as f:
        for line in f:
            if "GUI state:" in line:
                try:
                    return json.loads(line[line.find("{") :]), False
                except:
                    return None, True
    return None, False


class KbplacerPluginAction(pcbnew.ActionPlugin):
    def defaults(self) -> None:
        self.name = "Keyboard placer"
        self.category = "Mechanical Keyboard Helper"
        self.description = "Auto placement for key switches and diodes"
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")

    def Initialize(self) -> None:
        version = pcbnew.Version()
        if int(version.split(".")[0]) < 6:
            msg = f"KiCad version {version} is not supported"
            raise Exception(msg)
        if sys.version_info < (3, 8):
            vinfo = sys.version_info
            version_str = f"{vinfo.major}.{vinfo.minor}.{vinfo.micro}"
            msg = f"Python {version_str} is not supported"
            raise Exception(msg)

        self.board = pcbnew.GetBoard()

        board_file = self.board.GetFileName()
        if not board_file:
            msg = "Could not locate .kicad_pcb file, open or create it first"
            raise Exception(msg)

        # go to the project folder - so that log will be in proper place
        os.chdir(os.path.dirname(os.path.abspath(board_file)))

        # Remove all handlers associated with the root logger object.
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)

        self.window_state = None
        self.window_state_error = False
        log_file = "kbplacer.log"

        # if log file already exist (from previous plugin run),
        # try to get window state from it
        if os.path.isfile(log_file):
            self.window_state, self.window_state_error = load_window_state(log_file)

        # set up logger
        logging.basicConfig(
            level=logging.DEBUG,
            filename=log_file,
            filemode="w",
            format="[%(filename)s:%(lineno)d]: %(message)s",
        )
        logger.info(f"Plugin executed with KiCad version: {version}")
        logger.info(f"Plugin executed with python version: {repr(sys.version)}")

    def Run(self) -> None:
        self.Initialize()

        pcb_frame = [x for x in wx.GetTopLevelWindows() if x.GetName() == "PcbFrame"][0]

        if self.window_state_error:
            logger.info(
                "Found corrupted cached window state, skipping state restoration"
            )
            self.window_state = None

        dlg = KbplacerDialog(pcb_frame, "kbplacer", initial_state=self.window_state)
        if dlg.ShowModal() == wx.ID_OK:
            gui_state = dlg.get_window_state()
            logger.info(f"GUI state: {gui_state}")

            if layout_path := dlg.get_layout_path():
                with open(layout_path, "r") as f:
                    layout = json.load(f)
            else:
                layout = {}

            key_format = dlg.get_key_annotation_format()
            diode_info = dlg.get_diode_position_info()
            additional_elements = dlg.get_additional_elements_info()

            placer = KeyPlacer(self.board, dlg.get_key_distance())
            placer.run(
                layout,
                key_format,
                diode_info,
                dlg.route_switches_with_diodes(),
                dlg.route_rows_and_columns(),
                additional_elements=additional_elements,
            )

            if template_path := dlg.get_template_path():
                template_copier = TemplateCopier(
                    self.board, template_path, dlg.route_rows_and_columns()
                )
                template_copier.run()
        else:
            gui_state = dlg.get_window_state()
            logger.info(f"GUI state: {gui_state}")

        dlg.Destroy()
        logging.shutdown()
