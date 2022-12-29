import math
import re

from pcbnew import *
from .board_modifier import BoardModifier


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


class KeyPlacer(BoardModifier):
    def __init__(self, logger, board, layout):
        super().__init__(logger, board)
        self.layout = layout
        self.keyDistance = 19050000
        self.currentKey = 1
        self.currentDiode = 1
        self.referenceCoordinate = wxPoint(FromMM(25), FromMM(25))

    def GetCurrentKey(self, keyFormat, stabilizerFormat):
        key = self.GetFootprint(keyFormat.format(self.currentKey))

        # in case of perigoso/keyswitch-kicad-library, stabilizer holes are not part of of switch footprint and needs to be handled
        # separately, check if there is stabilizer with id matching current key and return it
        # stabilizer will be None if not found
        stabilizer = self.board.FindFootprintByReference(stabilizerFormat.format(self.currentKey))
        self.currentKey += 1

        return key, stabilizer

    def GetCurrentDiode(self, diodeFormat):
        diode = self.GetFootprint(diodeFormat.format(self.currentDiode))
        self.currentDiode += 1
        return diode

    def RouteSwitchWithDiode(self, switch, diode, angle):
        self.logger.info("Routing {} with {}".format(switch.GetReference(), diode.GetReference()))

        switchPadPosition = switch.FindPadByNumber("2").GetPosition()
        diodePadPosition = diode.FindPadByNumber("2").GetPosition()

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
            switchFootprint, stabilizer = self.GetCurrentKey(keyFormat, stabilizerFormat)

            width = key["width"]
            height = key["height"]
            position = wxPoint((self.keyDistance * key["x"]) + (self.keyDistance * width // 2),
                (self.keyDistance * key["y"]) + (self.keyDistance * height // 2)) + self.referenceCoordinate
            self.SetPosition(switchFootprint, position)

            if stabilizer:
                self.SetPosition(stabilizer, position)
                # recognize special case of of ISO enter:
                width2 = key["width2"]
                height2 = key["height2"]
                if width == 1.25 and height == 2 and width2 == 1.5 and height2 == 1:
                    stabilizer.SetOrientationDegrees(90)

            diodeFootprint = self.GetCurrentDiode(diodeFormat)
            self.SetRelativePositionMM(diodeFootprint, position, [5.08, 3.03])

            angle = key["rotation_angle"]
            if angle != 0:
                rotationReference = wxPoint((self.keyDistance * key["rotation_x"]), (self.keyDistance * key["rotation_y"])) + self.referenceCoordinate
                self.Rotate(switchFootprint, rotationReference, angle)
                if stabilizer:
                    self.Rotate(stabilizer, rotationReference, angle)
                self.Rotate(diodeFootprint, rotationReference, angle)
                if not diodeFootprint.IsFlipped():
                    diodeFootprint.Flip(diodeFootprint.GetPosition(), False)
                diodeFootprint.SetOrientationDegrees(switchFootprint.GetOrientationDegrees() - 270)
            else:
                if diodeFootprint.GetOrientationDegrees() != 90.0:
                    diodeFootprint.SetOrientationDegrees(270)
                if not diodeFootprint.IsFlipped():
                    diodeFootprint.Flip(diodeFootprint.GetPosition(), False)

            # append pad:
            pad = switchFootprint.FindPadByNumber("1")
            net_name = pad.GetNetname()
            match = re.match(r"^COL(\d+)$", net_name)
            if match:
                column_number = match.groups()[0]
                column_switch_pads.setdefault(column_number, []).append(pad)
            else:
                self.logger.warning("Switch pad without recognized net name found.")
            # append diode:
            pad = diodeFootprint.FindPadByNumber("1")
            net_name = pad.GetNetname()
            match = re.match(r"^ROW(\d+)$", net_name)
            if match:
                row_number = match.groups()[0]
                row_diode_pads.setdefault(row_number, []).append(pad)
            else:
                self.logger.warning("Switch pad without recognized net name found.")

            if routeTracks:
                self.RouteSwitchWithDiode(switchFootprint, diodeFootprint, angle)

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
