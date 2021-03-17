from pcbnew import *
import math
import argparse
import wx
import os
import sys
import json
import itertools
import logging
import re


def PositionInRotatedCoordinates(point, angle):
    """
    Map position in xy-Cartesian coordinate system to x'y'-Cartesian which has same origin
    but axes are rotated by angle

    :param point: A point to be mapped
    :param angle: Rotation angle (in degrees) of x'y'-Cartesian coordinates
    :type point: wxPoint
    :type angle: float
    :return: Result position in x'y'-Cartesian coordinates
    :rtype: wxPoint
    """
    x, y = point.x, point.y
    angle = math.radians(angle)
    xr = (x * math.cos(angle)) + (y * math.sin(angle))
    yr = (-x * math.sin(angle)) + (y * math.cos(angle))
    return wxPoint(xr, yr)


def PositionInCartesianCoordinates(point, angle):
    """Performs inverse operation to PositionInRotatedCoordinates i.e.
    map position in rotated (by angle) x'y'-Cartesian to xy-Cartesian

    :param point: A point to be mapped
    :param angle: Rotation angle (in degrees) of x'y'-Cartesian coordinates
    :type point: wxPoint
    :type angle: float
    :return: Result position in xy-Cartesian coordinates
    :rtype: wxPoint
    """
    xr, yr = point.x, point.y
    angle = math.radians(angle)
    x = (xr * math.cos(angle)) - (yr * math.sin(angle))
    y = (xr * math.sin(angle)) + (yr * math.cos(angle))
    return wxPoint(x, y)


class BoardModifier():
    def __init__(self, logger, board):
        self.logger = logger
        self.board = board

    def GetModule(self, reference):
        self.logger.info("Searching for {} module".format(reference))
        module = self.board.FindModuleByReference(reference)
        if module == None:
            self.logger.error("Module not found")
            raise Exception("Cannot find module {}".format(reference))
        return module

    def SetPosition(self, module, position):
        self.logger.info("Setting {} module position: {}".format(module.GetReference(), position))
        module.SetPosition(position)

    def SetRelativePositionMM(self, module, referencePoint, direction):
        position = wxPoint(referencePoint.x + FromMM(direction[0]), referencePoint.y + FromMM(direction[1]))
        self.SetPosition(module, position)

    def AddTrackSegment(self, start, vector, layer=B_Cu):
        track = TRACK(self.board)
        track.SetWidth(FromMM(0.25))
        track.SetLayer(layer)
        track.SetStart(start)
        segmentEnd = wxPoint(track.GetStart().x + vector[0], track.GetStart().y + vector[1])
        track.SetEnd(segmentEnd)

        layerName = self.board.GetLayerName(layer)
        self.logger.info("Adding track segment ({}): [{}, {}]".format(layerName, start, segmentEnd))
        self.board.Add(track)

        return segmentEnd

    def AddTrackSegmentByPoints(self, start, stop, layer=B_Cu):
        track = TRACK(self.board)
        track.SetWidth(FromMM(0.25))
        track.SetLayer(layer)
        track.SetStart(start)
        track.SetEnd(stop)

        layerName = self.board.GetLayerName(layer)
        self.logger.info("Adding track segment ({}): [{}, {}]".format(layerName, start, stop))
        self.board.Add(track)

        return stop

    def Rotate(self, module, rotationReference, angle):
        self.logger.info("Rotating {} module: rotationReference: {}, rotationAngle: {}".format(module.GetReference(), rotationReference, angle))
        module.Rotate(rotationReference, angle * -10)


class TemplateCopier(BoardModifier):
    def __init__(self, logger, board, templatePath, routeTracks):
        super().__init__(logger, board)
        self.template = LoadBoard(templatePath)
        self.boardNetsByName = board.GetNetsByName()
        self.routeTracks = routeTracks

    # Copy positions of elements and tracks from template to board.
    # This method does not copy parts itself - parts to be positioned need to be present in board
    # prior to calling this.
    def Run(self):
        module = self.template.GetModules().GetFirst()

        while module:
            reference = module.GetReference()
            destinationModule = self.GetModule(reference)

            layer = module.GetLayerName()
            position = module.GetPosition()
            orientation = module.GetOrientation()

            if layer == "B.Cu" and destinationModule.GetLayerName() != "B.Cu":
                destinationModule.Flip(destinationModule.GetCenter())
            self.SetPosition(destinationModule, position)
            destinationModule.SetOrientation(orientation)
            module = module.Next()

        if self.routeTracks:
            track = self.template.GetTracks().GetFirst()
            track = track.Next()
            while track:
                # clone track but remap netinfo because net codes in template might be different.
                # use net names for remmaping (names in template and bourd under modification must match)
                clone = track.Duplicate()
                netName = clone.GetNetname()
                netCode = clone.GetNetCode()
                netInfoInBoard = self.boardNetsByName[netName]
                self.logger.info("Cloning track from template: {}:{} -> {}:{}"
                        .format(netName, netCode, netInfoInBoard.GetNetname(), netInfoInBoard.GetNet()))
                clone.SetNet(netInfoInBoard)
                self.board.Add(clone)
                track = track.Next()


class KeyPlacer(BoardModifier):
    def __init__(self, logger, board, layout):
        super().__init__(logger, board)
        self.layout = layout
        self.keyDistance = 19050000
        self.currentKey = 1
        self.currentDiode = 1
        self.referenceCoordinate = wxPoint(FromMM(25), FromMM(25))

    def GetCurrentKey(self, keyFormat, stabilizerFormat):
        key = self.GetModule(keyFormat.format(self.currentKey))

        # in case of perigoso/keyswitch-kicad-library, stabilizer holes are not part of of switch footprint and needs to be handled
        # separately, check if there is stabilizer with id matching current key and return it
        # stabilizer will be None if not found
        stabilizer = self.board.FindModuleByReference(stabilizerFormat.format(self.currentKey))
        self.currentKey += 1

        return key, stabilizer

    def GetCurrentDiode(self, diodeFormat):
        diode = self.GetModule(diodeFormat.format(self.currentDiode))
        self.currentDiode += 1
        return diode

    def RouteSwitchWithDiode(self, switch, diode, angle):
        self.logger.info("Routing {} with {}".format(switch.GetReference(), diode.GetReference()))

        switchPadPosition = switch.FindPadByName("2").GetPosition()
        diodePadPosition = diode.FindPadByName("2").GetPosition()

        self.logger.debug("switchPadPosition: {}, diodePadPosition: {}".format(switchPadPosition, diodePadPosition))

        if angle != 0:
            self.logger.info("Routing at {} degree angle".format(angle))
            switchPadPositionR = PositionInRotatedCoordinates(switchPadPosition, angle)
            diodePadPositionR = PositionInRotatedCoordinates(diodePadPosition, angle)

            self.logger.debug("In rotated coordinates: switchPadPosition: {}, diodePadPosition: {}".format(
                switchPadPositionR, diodePadPositionR))

            x_diff = abs(diodePadPositionR.x - switchPadPositionR.x)

            corner = wxPoint(diodePadPositionR.x - x_diff, diodePadPositionR.y - x_diff)
            corner = PositionInCartesianCoordinates(corner, angle)
        else:
            x_diff = abs(diodePadPosition.x - switchPadPosition.x)
            corner = wxPoint(diodePadPosition.x - x_diff, diodePadPosition.y - x_diff)

        # first segment: at 45 degree angle (might be in rotated coordinate system) towards switch pad
        self.AddTrackSegmentByPoints(diodePadPosition, corner)
        # second segment: up to switch pad
        self.AddTrackSegmentByPoints(corner, switchPadPosition)

    def Run(self, keyFormat, stabilizerFormat, diodeFormat, routeTracks=False):
        column_switch_pads = {}
        row_diode_pads = {}
        for key in self.layout["keys"]:
            switchModule, stabilizer = self.GetCurrentKey(keyFormat, stabilizerFormat)

            width = key["width"]
            height = key["height"]
            position = wxPoint((self.keyDistance * key["x"]) + (self.keyDistance * width // 2),
                (self.keyDistance * key["y"]) + (self.keyDistance * height // 2)) + self.referenceCoordinate
            self.SetPosition(switchModule, position)

            if stabilizer:
                self.SetPosition(stabilizer, position)
                # recognize special case of of ISO enter:
                width2 = key["width2"]
                height2 = key["height2"]
                if width == 1.25 and height == 2 and width2 == 1.5 and height2 == 1:
                    stabilizer.SetOrientationDegrees(90)

            diodeModule = self.GetCurrentDiode(diodeFormat)
            self.SetRelativePositionMM(diodeModule, position, [5.08, 3.03])

            angle = key["rotation_angle"]
            if angle != 0:
                rotationReference = wxPoint((self.keyDistance * key["rotation_x"]), (self.keyDistance * key["rotation_y"])) + self.referenceCoordinate
                self.Rotate(switchModule, rotationReference, angle)
                if stabilizer:
                    self.Rotate(stabilizer, rotationReference, angle)
                self.Rotate(diodeModule, rotationReference, angle)
                if not diodeModule.IsFlipped():
                    diodeModule.Flip(diodeModule.GetPosition())
                diodeModule.SetOrientationDegrees(switchModule.GetOrientationDegrees() - 270)
            else:
                if diodeModule.GetOrientationDegrees() != 90.0:
                    diodeModule.SetOrientationDegrees(270)
                if not diodeModule.IsFlipped():
                    diodeModule.Flip(diodeModule.GetPosition())

            # append pad:
            pad = switchModule.FindPadByName("1")
            net_name = pad.GetNetname()
            match = re.match(r"^COL(\d+)$", net_name)
            if match:
                column_number = match.groups()[0]
                column_switch_pads.setdefault(column_number, []).append(pad)
            else:
                self.logger.warning("Switch pad without recognized net name found.")
            # append diode:
            pad = diodeModule.FindPadByName("1")
            net_name = pad.GetNetname()
            match = re.match(r"^ROW(\d+)$", net_name)
            if match:
                row_number = match.groups()[0]
                row_diode_pads.setdefault(row_number, []).append(pad)
            else:
                self.logger.warning("Switch pad without recognized net name found.")

            if routeTracks:
                self.RouteSwitchWithDiode(switchModule, diodeModule, angle)

        if routeTracks:
            # very naive routing approach, will fail in some scenarios:
            for column in column_switch_pads:
                pads = column_switch_pads[column]
                positions = [pad.GetPosition() for pad in pads]
                for pos1, pos2 in zip(positions, positions[1:]):
                    # connect two pads together
                    if pos1.x == pos2.x:
                        self.AddTrackSegmentByPoints(pos1, pos2, layer=F_Cu)
                    else:
                        # two segment track
                        y_diff = abs(pos1.y - pos2.y)
                        x_diff = abs(pos1.x - pos2.x)
                        vector = [0, (y_diff - x_diff)]
                        if vector[1] <= 0:
                            self.logger.warning("Switch pad to far to route 2 segment track with 45 degree angles")
                        else:
                            lastPosition = self.AddTrackSegment(pos1, vector, layer=F_Cu)
                            self.AddTrackSegmentByPoints(lastPosition, pos2, layer=F_Cu)

            for row in row_diode_pads:
                pads = row_diode_pads[row]
                positions = [pad.GetPosition() for pad in pads]
                for pos1, pos2 in zip(positions, positions[1:]):
                    if pos1.y == pos2.y:
                        self.AddTrackSegmentByPoints(pos1, pos2)
                    else:
                        self.logger.warning("Automatic diode routing supported only when diodes aligned vertically")


class KeyAutoPlaceDialog(wx.Dialog):
    def __init__(self, parent, title, caption):
        style = wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER
        super(KeyAutoPlaceDialog, self).__init__(parent, -1, title, style=style)
        row1 = wx.BoxSizer(wx.HORIZONTAL)

        text = wx.StaticText(self, -1, "Select kle json file:")
        row1.Add(text, 0, wx.LEFT|wx.RIGHT|wx.ALIGN_CENTER_VERTICAL, 5)

        layoutFilePicker = wx.FilePickerCtrl(self, -1)
        row1.Add(layoutFilePicker, 1, wx.EXPAND|wx.ALL, 5)

        row2 = wx.BoxSizer(wx.HORIZONTAL)

        keyAnnotationLabel = wx.StaticText(self, -1, "Key annotation format string:")
        row2.Add(keyAnnotationLabel, 1, wx.LEFT|wx.RIGHT|wx.ALIGN_CENTER_VERTICAL, 5)

        keyAnnotationFormat = wx.TextCtrl(self, value='SW{}')
        row2.Add(keyAnnotationFormat, 1, wx.EXPAND|wx.ALL, 5)

        row3 = wx.BoxSizer(wx.HORIZONTAL)

        stabilizerAnnotationLabel = wx.StaticText(self, -1, "Key annotation format string:")
        row3.Add(stabilizerAnnotationLabel, 1, wx.LEFT|wx.RIGHT|wx.ALIGN_CENTER_VERTICAL, 5)

        stabilizerAnnotationFormat = wx.TextCtrl(self, value='ST{}')
        row3.Add(stabilizerAnnotationFormat, 1, wx.EXPAND|wx.ALL, 5)

        row4 = wx.BoxSizer(wx.HORIZONTAL)

        diodeAnnotationLabel = wx.StaticText(self, -1, "Diode annotation format string:")
        row4.Add(diodeAnnotationLabel, 1, wx.LEFT|wx.RIGHT|wx.ALIGN_CENTER_VERTICAL, 5)

        diodeAnnotationFormat = wx.TextCtrl(self, value='D{}')
        row4.Add(diodeAnnotationFormat, 1, wx.EXPAND|wx.ALL, 5)

        row5 = wx.BoxSizer(wx.HORIZONTAL)

        tracksCheckbox = wx.CheckBox(self, label="Add tracks")
        tracksCheckbox.SetValue(True)
        row5.Add(tracksCheckbox, 1, wx.EXPAND|wx.ALL, 5)

        row6 = wx.BoxSizer(wx.HORIZONTAL)

        text = wx.StaticText(self, -1, "Select controler circuit template:")
        row6.Add(text, 0, wx.LEFT|wx.RIGHT|wx.ALIGN_CENTER_VERTICAL, 5)

        templateFilePicker = wx.FilePickerCtrl(self, -1)
        row6.Add(templateFilePicker, 1, wx.EXPAND|wx.ALL, 5)

        box = wx.BoxSizer(wx.VERTICAL)

        box.Add(row1, 0, wx.EXPAND|wx.ALL, 5)
        box.Add(row2, 0, wx.EXPAND|wx.ALL, 5)
        box.Add(row3, 0, wx.EXPAND|wx.ALL, 5)
        box.Add(row4, 0, wx.EXPAND|wx.ALL, 5)
        box.Add(row5, 0, wx.EXPAND|wx.ALL, 5)
        box.Add(row6, 0, wx.EXPAND|wx.ALL, 5)

        buttons = self.CreateButtonSizer(wx.OK|wx.CANCEL)
        box.Add(buttons, 0, wx.EXPAND|wx.ALL, 5)

        self.SetSizerAndFit(box)
        self.layoutFilePicker = layoutFilePicker
        self.keyAnnotationFormat = keyAnnotationFormat
        self.stabilizerAnnotationFormat = stabilizerAnnotationFormat
        self.diodeAnnotationFormat = diodeAnnotationFormat
        self.tracksCheckbox = tracksCheckbox
        self.templateFilePicker = templateFilePicker

    def GetLayoutPath(self):
        return self.layoutFilePicker.GetPath()

    def GetKeyAnnotationFormat(self):
        return self.keyAnnotationFormat.GetValue()

    def GetStabilizerAnnotationFormat(self):
        return self.stabilizerAnnotationFormat.GetValue()

    def GetDiodeAnnotationFormat(self):
        return self.diodeAnnotationFormat.GetValue()

    def IsTracks(self):
        return self.tracksCheckbox.GetValue()

    def GetTemplatePath(self):
        return self.templateFilePicker.GetPath()


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
            templatePath = dlg.GetTemplatePath()
            if templatePath:
                templateCopier = TemplateCopier(self.logger, self.board, templatePath, dlg.IsTracks())
                templateCopier.Run()

            layoutPath = dlg.GetLayoutPath()
            if layoutPath:
                with open(layoutPath, "r") as f:
                    textInput = f.read()
                layout = json.loads(textInput)
                self.logger.info("User layout: {}".format(layout))
                placer = KeyPlacer(self.logger, self.board, layout)
                placer.Run(dlg.GetKeyAnnotationFormat(), dlg.GetStabilizerAnnotationFormat(), dlg.GetDiodeAnnotationFormat(), dlg.IsTracks())

        dlg.Destroy()
        logging.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Keyboard's key autoplacer")
    parser.add_argument('-l', '--layout', required=True, help="json layout definition file")
    parser.add_argument('-b', '--board', required=True, help=".kicad_pcb file to be processed")
    parser.add_argument('-r', '--route', action="store_true", help="Enable experimental routing")
    parser.add_argument('-t', '--template', help="controler circuit template")

    args = parser.parse_args()
    layoutPath = args.layout
    boardPath = args.board
    routeTracks = args.route
    templatePath = args.template

    # set up logger
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s: %(message)s',
                        datefmt='%H:%M:%S')
    logger = logging.getLogger(__name__)

    board = LoadBoard(boardPath)

    if templatePath:
        copier = TemplateCopier(logger, board, templatePath, routeTracks)
        copier.Run()

    if layoutPath:
        with open(layoutPath, "r") as f:
            textInput = f.read()
            layout = json.loads(textInput)

        logger.info("User layout: {}".format(layout))

        placer = KeyPlacer(logger, board, layout)
        placer.Run("SW{}", "ST{}", "D{}", routeTracks)

    Refresh()
    SaveBoard(boardPath, board)

    logging.shutdown()

else:
    KeyAutoPlace().register()
