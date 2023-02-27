import logging
import json
import os
import pcbnew
import sys
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
        self.board = pcbnew.GetBoard()

        # go to the project folder - so that log will be in proper place
        os.chdir(os.path.dirname(os.path.abspath(self.board.GetFileName())))

        # Remove all handlers associated with the root logger object.
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)

        # set up logger
        logging.basicConfig(level=logging.DEBUG,
                            filename="kbplacer.log",
                            filemode='w',
                            format='%(asctime)s %(name)s %(lineno)d: %(message)s',
                            datefmt='%H:%M:%S')
        self.logger = logging.getLogger(__name__)
        self.logger.info("Plugin executed with python version: " + repr(sys.version))

    def Run(self):
        self.Initialize()

        pcbFrame = [x for x in wx.GetTopLevelWindows() if x.GetName() == 'PcbFrame'][0]

        dlg = KbplacerDialog(pcbFrame, 'Title', 'Caption')
        if dlg.ShowModal() == wx.ID_OK:
            layoutPath = dlg.GetLayoutPath()
            if layoutPath:
                with open(layoutPath, "r") as f:
                    textInput = f.read()
                layout = json.loads(textInput)
                self.logger.info("User layout: {}".format(layout))
                placer = KeyPlacer(self.logger, self.board, layout)
                keyFormat = dlg.GetKeyAnnotationFormat()
                stabilizerFormat = dlg.GetStabilizerAnnotationFormat()
                diodeFormat = dlg.GetDiodeAnnotationFormat()
                diodePosition = placer.GetDiodePosition(
                    keyFormat,
                    diodeFormat,
                    dlg.IsFirstPairUsedAsTemplate(),
                )
                placer.Run(
                    keyFormat,
                    stabilizerFormat,
                    diodeFormat,
                    diodePosition,
                    dlg.IsTracks(),
                )
            templatePath = dlg.GetTemplatePath()
            if templatePath:
                templateCopier = TemplateCopier(self.logger, self.board, templatePath, dlg.IsTracks())
                templateCopier.Run()


        dlg.Destroy()
        logging.shutdown()
