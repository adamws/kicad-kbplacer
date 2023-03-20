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
    def defaults(self):
        self.name = "Keyboard placer"
        self.category = "Mechanical Keybaord Helper"
        self.description = "Auto placement for key switches and diodes"

    def Initialize(self):
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

    def Run(self):
        self.Initialize()

        pcbFrame = [x for x in wx.GetTopLevelWindows() if x.GetName() == "PcbFrame"][0]

        dlg = KbplacerDialog(pcbFrame, "kbplacer")
        if dlg.ShowModal() == wx.ID_OK:
            layoutPath = dlg.get_layout_path()
            if layoutPath:
                with open(layoutPath, "r") as f:
                    textInput = f.read()
                layout = json.loads(textInput)
                self.logger.info(f"User layout: {layout}")
                placer = KeyPlacer(self.logger, self.board, layout)
                keyFormat = dlg.get_key_annotation_format()
                stabilizerFormat = dlg.get_stabilizer_annotation_format()
                diodeFormat = dlg.get_diode_annotation_format()
                diodePosition = placer.get_diode_position(
                    keyFormat,
                    diodeFormat,
                    dlg.is_first_pair_used_as_template(),
                )
                placer.run(
                    keyFormat,
                    stabilizerFormat,
                    diodeFormat,
                    diodePosition,
                    dlg.is_tracks(),
                )
            templatePath = dlg.get_template_path()
            if templatePath:
                templateCopier = TemplateCopier(
                    self.logger, self.board, templatePath, dlg.is_tracks()
                )
                templateCopier.run()

        dlg.Destroy()
        logging.shutdown()
