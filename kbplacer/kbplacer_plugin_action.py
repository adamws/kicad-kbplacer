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
        self.category = "Mechanical Keybaord Helper"
        self.description = "Auto placement for key switches and diodes"
        self.show_toolbar_button = True
        self.icon_file_name = os.path.join(os.path.dirname(__file__), "icon.png")

    def Initialize(self) -> None:
        version = pcbnew.Version()
        if int(version.split(".")[0]) < 6:
            msg = f"KiCad version {version} is not supported"
            raise Exception(msg)
        self.board = pcbnew.GetBoard()

        # go to the project folder - so that log will be in proper place
        os.chdir(os.path.dirname(os.path.abspath(self.board.GetFileName())))

        # Remove all handlers associated with the root logger object.
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)

        # set up logger
        logging.basicConfig(
            level=logging.DEBUG,
            filename="kbplacer.log",
            filemode="w",
            format="%(asctime)s %(name)s %(lineno)d: %(message)s",
            datefmt="%H:%M:%S",
        )
        self.logger = logging.getLogger(__name__)
        self.logger.info("Plugin executed with KiCad version: " + version)
        self.logger.info("Plugin executed with python version: " + repr(sys.version))

    def Run(self) -> None:
        self.Initialize()

        pcb_frame = [x for x in wx.GetTopLevelWindows() if x.GetName() == "PcbFrame"][0]

        dlg = KbplacerDialog(pcb_frame, "kbplacer")
        if dlg.ShowModal() == wx.ID_OK:
            layout_path = dlg.get_layout_path()
            if layout_path:
                with open(layout_path, "r") as f:
                    text_input = f.read()
                layout = json.loads(text_input)
                self.logger.info(f"User layout: {layout}")
                placer = KeyPlacer(self.logger, self.board, layout)
                key_format = dlg.get_key_annotation_format()
                stabilizer_format = dlg.get_stabilizer_annotation_format()
                diode_format = dlg.get_diode_annotation_format()
                diode_position = placer.get_diode_position(
                    key_format,
                    diode_format,
                    dlg.is_first_pair_used_as_template(),
                )
                placer.run(
                    key_format,
                    stabilizer_format,
                    diode_format,
                    diode_position,
                    dlg.is_tracks(),
                )
            template_path = dlg.get_template_path()
            if template_path:
                template_copier = TemplateCopier(
                    self.logger, self.board, template_path, dlg.is_tracks()
                )
                template_copier.run()

        dlg.Destroy()
        logging.shutdown()
