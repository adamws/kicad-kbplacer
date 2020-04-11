from pcbnew import *
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


    def GetCurrentKey(self):
        reference = 'MX_{}'.format(self.currentKey)
        self.logger.info('Searching for {} module'.format(reference))
        self.currentKey += 1
        return self.board.FindModuleByReference(reference)

    
    def GetCurrentDiode(self):
        reference = 'D_{}'.format(self.currentDiode)
        self.logger.info('Searching for {} module'.format(reference))
        self.currentDiode += 1
        return self.board.FindModuleByReference(reference)


    def SetRelativePositionMM(self, module, referencePoint, direction):
        module.SetPosition(wxPoint(referencePoint.x + FromMM(direction[0]), referencePoint.y + FromMM(direction[1])))


    def AddTrackSegment(self, start, vector, layer=B_Cu):
        track = TRACK(self.board)
        track.SetWidth(FromMM(0.25))
        track.SetLayer(layer)
        track.SetStart(start)
        segmentEnd = wxPoint(track.GetStart().x + FromMM(vector[0]), track.GetStart().y + FromMM(vector[1]))
        track.SetEnd(segmentEnd)
        self.board.Add(track)
        track.SetLocked(True)
        return segmentEnd


    def RouteKeyWithDiode(self, key, diode):
        end = self.AddTrackSegment(diode.FindPadByName('2').GetPosition(), [-1.98, -1.98])
        self.AddTrackSegment(end, [0, -4.2])


    def RouteColumn(self, key):
        segmentStart = wxPoint(key.GetPosition().x - FromMM(3.11), key.GetPosition().y - FromMM(1.84))
        self.AddTrackSegment(segmentStart, [0, 10], layer=F_Cu)


    def Run(self, routeTracks=False):
        for key in self.layout["keys"]:
            keyModule = self.GetCurrentKey()
            position = wxPoint(self.referenceCoordinate.x + (self.keyDistance * key["x"]) + (self.keyDistance * key["width"] // 2), 
                    self.referenceCoordinate.y + (self.keyDistance * key["y"]) + (self.keyDistance * key["height"] // 2))
            keyModule.SetPosition(position)
            #rotationReference = wxPoint(self.referenceCoordinate.x + (self.keyDistance * key["rotation_x"]) + (self.keyDistance * key["width"] // 2), 
            #        self.referenceCoordinate.y + (self.keyDistance * key["rotation_y"]) + (self.keyDistance * key["height"] // 2))
            #keyModule.Rotate(rotationReference, key["rotation_angle"] * -10)

            diodeModule = self.GetCurrentDiode()
            self.SetRelativePositionMM(diodeModule, position, [5.08, 3.03])
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

        tracksCheckbox = wx.CheckBox(self, label="Add tracks")
        row2.Add(tracksCheckbox, 1, wx.EXPAND|wx.ALL, 5)

        box = wx.BoxSizer(wx.VERTICAL)

        box.Add(row1, 0, wx.EXPAND|wx.ALL, 5)
        box.Add(row2, 0, wx.EXPAND|wx.ALL, 5)

        buttons = self.CreateButtonSizer(wx.OK|wx.CANCEL)
        box.Add(buttons, 0, wx.EXPAND|wx.ALL, 5)

        self.SetSizerAndFit(box)
        self.filePicker = filePicker
        self.tracksCheckbox = tracksCheckbox


    def GetValue(self):
        return self.filePicker.GetPath()


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
                            format='%(asctime)s %(name)s %(lineno)d:%(message)s',
                            datefmt='%m-%d %H:%M:%S')
        self.logger = logging.getLogger(__name__)
        self.logger.info("Plugin executed with python version: " + repr(sys.version))


    def Run(self):
        self.Initialize()

        pcbFrame = [x for x in wx.GetTopLevelWindows() if x.GetName() == 'PcbFrame'][0]

        dlg = KeyAutoPlaceDialog(pcbFrame, 'Title', 'Caption')
        if dlg.ShowModal() == wx.ID_OK:
            layoutPath = dlg.GetValue()
            f = open(layoutPath, "r")
            textInput = f.read()
            f.close()
            layout = json.loads(textInput)
            self.logger.info("User layout: {}".format(layout))
            placer = KeyPlacer(self.logger, self.board, layout)
            placer.Run(dlg.IsTracks())


        dlg.Destroy()
        logging.shutdown()


KeyAutoPlace().register()
