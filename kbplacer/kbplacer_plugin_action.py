# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import logging
import os
import sys

import pcbnew
import wx

from . import __version__
from .error_dialog import ErrorDialog
from .kbplacer_dialog import KbplacerDialog, load_window_state_from_log
from .kbplacer_plugin import run_from_gui
from .plugin_error import PluginError
from .warning_dialog import get_warnings_from_log

logger = logging.getLogger(__name__)


class KbplacerPluginAction(pcbnew.ActionPlugin):
    def defaults(self) -> None:
        self.name = "Keyboard Plugin"
        self.category = "Mechanical Keyboard Helper"
        self.description = "Automated placement and routing for keyboard PCBs"
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")

    def initialize(self) -> None:
        version = pcbnew.Version()
        if int(version.split(".")[0]) < 6:
            msg = f"KiCad version {version} is not supported"
            raise RuntimeError(msg)
        if sys.version_info < (3, 8):
            vinfo = sys.version_info
            version_str = f"{vinfo.major}.{vinfo.minor}.{vinfo.micro}"
            msg = f"Python {version_str} is not supported"
            raise RuntimeError(msg)

        self.board = pcbnew.GetBoard()
        board_file = self.board.GetFileName()
        if not board_file:
            msg = "Could not locate .kicad_pcb file, open or create it first"
            raise PluginError(msg)

        self.board_path = os.path.abspath(board_file)
        # go to the project folder - so that log will be in proper place
        os.chdir(os.path.dirname(self.board_path))

        # Remove all handlers associated with the root logger object.
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)

        self.log_file = "kbplacer.log"

        # if log file already exist (from previous plugin run),
        # try to get window state from it, must be done before setting up new logger
        self.window_state = load_window_state_from_log(self.log_file)

        # set up logger
        logging.basicConfig(
            level=logging.DEBUG,
            filename=self.log_file,
            filemode="w",
            format="%(levelname)s: %(filename)s:%(lineno)d: %(message)s",
        )
        logger.info(f"Plugin version: {__version__}")
        logger.info(f"Python version: {repr(sys.version)}")
        logger.info(f"KiCad version: {version} with {wx.version()}")

    def __run(self) -> None:
        self.window = wx.GetActiveWindow()
        self.initialize()
        dlg = KbplacerDialog(self.window, "kbplacer", initial_state=self.window_state)
        if dlg.ShowModal() == wx.ID_OK:
            gui_state = dlg.get_window_state()
            logger.info(f"GUI state: {gui_state}")
            run_from_gui(self.board_path, gui_state)
        else:
            # field validators are not executed on cancel so getting window
            # state might raise an exception. Since we are cancelling,
            # do not bother user with them.
            try:
                gui_state = dlg.get_window_state()
                logger.info(f"GUI state: {gui_state}")
            except Exception:
                pass

        dlg.Destroy()
        logging.shutdown()

    def Run(self) -> None:
        try:
            self.__run()
            if warning := get_warnings_from_log(self.window, self.log_file):
                warning.ShowModal()
        except Exception as e:
            error = ErrorDialog(self.window, e)
            error.ShowModal()
