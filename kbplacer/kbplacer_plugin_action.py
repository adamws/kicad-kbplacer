import json
import logging
import os
import sys

import pcbnew
import wx

from .kbplacer_dialog import KbplacerDialog
from .key_placer import KeyPlacer
from .template_copier import TemplateCopier


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

        # set up logger
        logging.basicConfig(
            level=logging.DEBUG,
            filename="kbplacer.log",
            filemode="w",
            format="[%(filename)s:%(lineno)d]: %(message)s",
        )
        self.logger = logging.getLogger(__name__)
        self.logger.info(f"Plugin executed with KiCad version: {version}")
        self.logger.info(f"Plugin executed with python version: {repr(sys.version)}")

    def Run(self) -> None:
        self.Initialize()

        pcb_frame = [x for x in wx.GetTopLevelWindows() if x.GetName() == "PcbFrame"][0]

        dlg = KbplacerDialog(pcb_frame, "kbplacer")
        if dlg.ShowModal() == wx.ID_OK:
            if layout_path := dlg.get_layout_path():
                with open(layout_path, "r") as f:
                    text_input = f.read()
                layout = json.loads(text_input)
                placer = KeyPlacer(self.logger, self.board, dlg.get_key_distance())
                key_format = dlg.get_key_annotation_format()
                diode_info = dlg.get_diode_position_info()
                additional_elements = dlg.get_additional_elements_info()

                placer.run(
                    layout,
                    key_format,
                    diode_info,
                    dlg.is_tracks(),
                    additional_elements=additional_elements,
                )
            if template_path := dlg.get_template_path():
                template_copier = TemplateCopier(
                    self.logger, self.board, template_path, dlg.is_tracks()
                )
                template_copier.run()

        dlg.Destroy()
        logging.shutdown()
