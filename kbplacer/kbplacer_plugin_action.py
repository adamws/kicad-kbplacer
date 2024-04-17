from __future__ import annotations

import logging
import os
import sys

import pcbnew
import wx

from .kbplacer_dialog import KbplacerDialog, load_window_state_from_log
from .kbplacer_plugin import run_from_gui

logger = logging.getLogger(__name__)


class KbplacerPluginAction(pcbnew.ActionPlugin):
    def defaults(self) -> None:
        self.name = "Keyboard Plugin"
        self.category = "Mechanical Keyboard Helper"
        self.description = "Automated placement and routing for keyboard PCBs"
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

        self.board_path = os.path.abspath(board_file)
        # go to the project folder - so that log will be in proper place
        os.chdir(os.path.dirname(self.board_path))

        # Remove all handlers associated with the root logger object.
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)

        log_file = "kbplacer.log"

        # if log file already exist (from previous plugin run),
        # try to get window state from it, must be done before setting up new logger
        self.window_state = load_window_state_from_log(log_file)

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

        dlg = KbplacerDialog(pcb_frame, "kbplacer", initial_state=self.window_state)
        modal_return = dlg.ShowModal()
        gui_state = dlg.get_window_state()
        logger.info(f"GUI state: {gui_state}")

        if modal_return == wx.ID_OK:
            run_from_gui(self.board_path, gui_state)

        dlg.Destroy()
        logging.shutdown()
