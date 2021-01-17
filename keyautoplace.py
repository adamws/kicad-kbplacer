from pcbnew import *
import argparse
import wx
import os
import sys
import json
import itertools
import logging


class KeyPlacer():
    def __init__(self, logger, board, layout):
        self.logger = logger
        self.board = board
        self.layout = layout
        self.keyDistance = 19050000
        self.currentKey = 1
        self.currentDiode = 1
        self.referenceCoordinate = wxPoint(FromMM(25), FromMM(25))


    def GetModule(self, reference):
        self.logger.info(f"Searching for {reference} module")
        module = self.board.FindModuleByReference(reference)
        if module == None:
            self.logger.error("Module not found")
            raise Exception(f"Cannot find module {reference}")
        return module

    def GetCurrentKey(self, keyFormat):
        key = self.GetModule(keyFormat.format(self.currentKey))
        self.currentKey += 1
        return key


    def GetCurrentDiode(self, diodeFormat):
        diode = self.GetModule(diodeFormat.format(self.currentDiode))
        self.currentDiode += 1
        return diode


    def SetPosition(self, module, position):
        self.logger.info(f"Setting {module.GetReference()} module position: {position}")
        module.SetPosition(position)


    def SetRelativePositionMM(self, module, referencePoint, direction):
        position = wxPoint(referencePoint.x + FromMM(direction[0]), referencePoint.y + FromMM(direction[1]))
        self.SetPosition(module, position)


    def AddTrackSegment(self, start, vector, layer=B_Cu):
        track = TRACK(self.board)
        track.SetWidth(FromMM(0.25))
        track.SetLayer(layer)
        track.SetStart(start)
        segmentEnd = wxPoint(track.GetStart().x + FromMM(vector[0]), track.GetStart().y + FromMM(vector[1]))
        track.SetEnd(segmentEnd)

        layerName = self.board.GetLayerName(layer)
        self.logger.info(f"Adding track segment ({layerName}): [{start}, {segmentEnd}]")
        self.board.Add(track)

        track.SetLocked(True)
        return segmentEnd


    def RouteKeyWithDiode(self, key, diode):
        end = self.AddTrackSegment(diode.FindPadByName('2').GetPosition(), [-1.98, -1.98])
        self.AddTrackSegment(end, [0, -4.2])


    def RouteColumn(self, key):
        segmentStart = wxPoint(key.GetPosition().x - FromMM(3.11), key.GetPosition().y - FromMM(1.84))
        self.AddTrackSegment(segmentStart, [0, 10], layer=F_Cu)


    def Rotate(self, module, rotationReference, angle):
        self.logger.info("Rotating {module.GetReference()} module: rotationReference: {rotationReference}, rotationAngle: {angle}")
        module.Rotate(rotationReference, angle * -10)


    def Run(self, keyFormat, diodeFormat, routeTracks=False):
        for key in self.layout["keys"]:
            keyModule = self.GetCurrentKey(keyFormat)

            position = wxPoint((self.keyDistance * key["x"]) + (self.keyDistance * key["width"] // 2),
                (self.keyDistance * key["y"]) + (self.keyDistance * key["height"] // 2)) + self.referenceCoordinate
            self.SetPosition(keyModule, position)

            angle = key["rotation_angle"]
            if angle != 0:
                rotationReference = wxPoint((self.keyDistance * key["rotation_x"]), (self.keyDistance * key["rotation_y"])) + self.referenceCoordinate
                self.Rotate(keyModule, rotationReference, angle)

            diodeModule = self.GetCurrentDiode(diodeFormat)
            self.SetRelativePositionMM(diodeModule, position, [5.08, 3.03])
            if angle != 0:
                self.Rotate(diodeModule, rotationReference, angle)
                if not diodeModule.IsFlipped():
                    diodeModule.Flip(diodeModule.GetPosition())
                diodeModule.SetOrientationDegrees(keyModule.GetOrientationDegrees() - 270)
            else:
                diodeModule.SetOrientationDegrees(270)
                if not diodeModule.IsFlipped():
                    diodeModule.Flip(diodeModule.GetPosition())


            if routeTracks == True:
                self.RouteKeyWithDiode(keyModule, diodeModule)
                self.RouteColumn(keyModule)


class KeyAutoPlaceDialog(wx.Dialog):
    def __init__(self, parent, title, caption):
        style = wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER
        super(KeyAutoPlaceDialog, self).__init__(parent, -1, title, style=style)
        row1 = wx.BoxSizer(wx.HORIZONTAL)

        text = wx.StaticText(self, -1, "Select kle json file:")
        row1.Add(text, 0, wx.LEFT|wx.RIGHT|wx.ALIGN_CENTER_VERTICAL, 5)

        filePicker = wx.FilePickerCtrl(self, -1)
        row1.Add(filePicker, 1, wx.EXPAND|wx.ALL, 5)

        row2 = wx.BoxSizer(wx.HORIZONTAL)

        keyAnnotationLabel = wx.StaticText(self, -1, "Key annotation format string:")
        row2.Add(keyAnnotationLabel, 1, wx.LEFT|wx.RIGHT|wx.ALIGN_CENTER_VERTICAL, 5)

        keyAnnotationFormat = wx.TextCtrl(self, value='MX{}')
        row2.Add(keyAnnotationFormat, 1, wx.EXPAND|wx.ALL, 5)

        row3 = wx.BoxSizer(wx.HORIZONTAL)

        diodeAnnotationLabel = wx.StaticText(self, -1, "Diode annotation format string:")
        row3.Add(diodeAnnotationLabel, 1, wx.LEFT|wx.RIGHT|wx.ALIGN_CENTER_VERTICAL, 5)

        diodeAnnotationFormat = wx.TextCtrl(self, value='D{}')
        row3.Add(diodeAnnotationFormat, 1, wx.EXPAND|wx.ALL, 5)

        row4 = wx.BoxSizer(wx.HORIZONTAL)

        tracksCheckbox = wx.CheckBox(self, label="Add tracks")
        tracksCheckbox.SetValue(True)
        row4.Add(tracksCheckbox, 1, wx.EXPAND|wx.ALL, 5)

        box = wx.BoxSizer(wx.VERTICAL)

        box.Add(row1, 0, wx.EXPAND|wx.ALL, 5)
        box.Add(row2, 0, wx.EXPAND|wx.ALL, 5)
        box.Add(row3, 0, wx.EXPAND|wx.ALL, 5)
        box.Add(row4, 0, wx.EXPAND|wx.ALL, 5)

        buttons = self.CreateButtonSizer(wx.OK|wx.CANCEL)
        box.Add(buttons, 0, wx.EXPAND|wx.ALL, 5)

        self.SetSizerAndFit(box)
        self.filePicker = filePicker
        self.keyAnnotationFormat = keyAnnotationFormat
        self.diodeAnnotationFormat = diodeAnnotationFormat
        self.tracksCheckbox = tracksCheckbox


    def GetJsonPath(self):
        return self.filePicker.GetPath()


    def GetKeyAnnotationFormat(self):
        return self.keyAnnotationFormat.GetValue()


    def GetDiodeAnnotationFormat(self):
        return self.diodeAnnotationFormat.GetValue()


    def IsTracks(self):
        return self.tracksCheckbox.GetValue()


class KeyAutoPlace(ActionPlugin):
    def defaults(self):
        self.name = "KeyAutoPlace"
        self.category = "Mechanical Keybaord Helper"
        self.description = "Auto placement for key switches and diodes"


    def Initialize(self):
        self.board = GetBoard()

        # go to the project folder - so that log will be in proper place
        os.chdir(os.path.dirname(os.path.abspath(self.board.GetFileName())))

        # Remove all handlers associated with the root logger object.
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)

        # set up logger
        logging.basicConfig(level=logging.DEBUG,
                            filename="keyautoplace.log",
                            filemode='w',
                            format='%(asctime)s %(name)s %(lineno)d: %(message)s',
                            datefmt='%H:%M:%S')
        self.logger = logging.getLogger(__name__)
        self.logger.info("Plugin executed with python version: " + repr(sys.version))


    def Run(self):
        self.Initialize()

        pcbFrame = [x for x in wx.GetTopLevelWindows() if x.GetName() == 'PcbFrame'][0]

        dlg = KeyAutoPlaceDialog(pcbFrame, 'Title', 'Caption')
        if dlg.ShowModal() == wx.ID_OK:
            layoutPath = dlg.GetJsonPath()
            with open(layoutPath, "r") as f:
                textInput = f.read()
            layout = json.loads(textInput)
            self.logger.info(f"User layout: {layout}")
            placer = KeyPlacer(self.logger, self.board, layout)
            placer.Run(dlg.GetKeyAnnotationFormat(), dlg.GetDiodeAnnotationFormat(), dlg.IsTracks())


        dlg.Destroy()
        logging.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Keyboard's key autoplacer")
    parser.add_argument('-l', '--layout', required=True, help="json layout definition file")
    parser.add_argument('-b', '--board', required=True, help=".kicad_pcb file to be processed")

    args = parser.parse_args()
    layoutPath = args.layout
    boardPath = args.board

    # set up logger
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s: %(message)s',
                        datefmt='%H:%M:%S')
    logger = logging.getLogger(__name__)

    with open(layoutPath, "r") as f:
        textInput = f.read()
        layout = json.loads(textInput)

    logger.info(f"User layout: {layout}")

    board = LoadBoard(boardPath)
    placer = KeyPlacer(logger, board, layout)
    placer.Run("MX{}", "D{}", False)

    Refresh()
    SaveBoard(boardPath, board)

    logging.shutdown()

else:
    KeyAutoPlace().register()
