import builtins
import math
import re
from dataclasses import dataclass

from pcbnew import *
from .board_modifier import BoardModifier, Point, Side, KICAD_VERSION


@dataclass
class DiodePosition:
    relativePosition: Point
    orientation: float
    side: Side


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

    def CalculateCornerPositionOfSwitchDiodeRoute(self, diodePadPosition, switchPadPosition):
        x_diff = diodePadPosition.x - switchPadPosition.x
        y_diff = diodePadPosition.y - switchPadPosition.y
        if builtins.abs(x_diff) < builtins.abs(y_diff):
            upOrDown = -1 if y_diff > 0 else 1
            return wxPoint(diodePadPosition.x - x_diff, diodePadPosition.y + (upOrDown * builtins.abs(x_diff)))
        else:
            leftOrRight = -1 if x_diff > 0 else 1
            return wxPoint(diodePadPosition.x + (leftOrRight * builtins.abs(y_diff)), diodePadPosition.y - y_diff)

    def RouteSwitchWithDiode(self, switch, diode, angle, templateTrackPoints=None):
        """Performs routing between switch and diode elements.
        Assumes col-to-row configuration where diode anode is pad number '2'.

        :param switch: Switch footprint to be routed.
        :param diode: Diode footprint to be routed.
        :param angle: Rotation angle (in degrees) of switch footprint (diode rotation is assumed to be the same)
        :param templateTrackPoints: List of positions (relative to diode pad position) of track corners connecting switch and diode.
                                    Does not support vias, will be routed on the layer of the diode.
                                    If None, use automatic routing algorithm.
        :type switch: FOOTPRINT
        :type diode: FOOTPRINT
        :type angle: float
        :type templateTrackPoints: List[wxPoint]
        """
        self.logger.info("Routing {} with {}".format(switch.GetReference(), diode.GetReference()))

        layer = B_Cu if self.GetSide(diode) == Side.BACK else F_Cu
        switchPadPosition = switch.FindPadByNumber("2").GetPosition()
        diodePadPosition = diode.FindPadByNumber("2").GetPosition()
        if KICAD_VERSION == 7:
            switchPadPosition = wxPoint(switchPadPosition.x, switchPadPosition.y)
            diodePadPosition = wxPoint(diodePadPosition.x, diodePadPosition.y)

        self.logger.debug("switchPadPosition: {}, diodePadPosition: {}".format(switchPadPosition, diodePadPosition))

        if templateTrackPoints:
            if angle != 0:
                self.logger.info("Routing at {} degree angle".format(angle))
            start = diodePadPosition
            for t in templateTrackPoints:
                if angle != 0:
                    diodePadPositionR = PositionInRotatedCoordinates(diodePadPosition, angle)
                    end = t.__add__(diodePadPositionR)
                    end = PositionInCartesianCoordinates(end, angle)
                else:
                    end = t.__add__(diodePadPosition)
                end = self.AddTrackSegmentByPoints(start, end, layer)
                if end:
                    start = end
        else:
            if switchPadPosition.x == diodePadPosition.x or switchPadPosition.y == diodePadPosition.y:
                self.AddTrackSegmentByPoints(diodePadPosition, switchPadPosition, layer)
            else:
                # pads are not in single line, attempt routing with two segment track
                if angle != 0:
                    self.logger.info("Routing at {} degree angle".format(angle))
                    switchPadPositionR = PositionInRotatedCoordinates(switchPadPosition, angle)
                    diodePadPositionR = PositionInRotatedCoordinates(diodePadPosition, angle)

                    self.logger.debug("In rotated coordinates: switchPadPosition: {}, diodePadPosition: {}".format(
                        switchPadPositionR, diodePadPositionR))

                    corner = self.CalculateCornerPositionOfSwitchDiodeRoute(diodePadPositionR, switchPadPositionR)
                    corner = PositionInCartesianCoordinates(corner, angle)
                else:
                    corner = self.CalculateCornerPositionOfSwitchDiodeRoute(diodePadPosition, switchPadPosition)

                # first segment: at 45 degree angle (might be in rotated coordinate system) towards switch pad
                self.AddTrackSegmentByPoints(diodePadPosition, corner, layer)
                # second segment: up to switch pad
                self.AddTrackSegmentByPoints(corner, switchPadPosition, layer)

    def GetDefaultDiodePosition(self):
        return DiodePosition(Point(5.08, 3.03), 90.0, Side.BACK)

    def GetDiodePosition(self, keyFormat, diodeFormat, isFirstPairUsedAsTemplate):
        if isFirstPairUsedAsTemplate:
            key1 = self.GetFootprint(keyFormat.format(1))
            diode1 = self.GetFootprint(diodeFormat.format(1))
            pos1 = self.GetPosition(key1)
            pos2 = self.GetPosition(diode1)
            return DiodePosition(Point(ToMM(pos2.x - pos1.x), ToMM(pos2.y - pos1.y)), diode1.GetOrientationDegrees(), self.GetSide(diode1))
        else:
            return self.GetDefaultDiodePosition()

    def RemoveDanglingTracks(self):
        connectivity = self.GetConnectivity()
        for track in self.board.GetTracks():
            if connectivity.TestTrackEndpointDangling(track):
                self.board.RemoveNative(track)

    def CheckIfDiodeRouted(self, keyFormat, diodeFormat):
        switch = self.GetFootprint(keyFormat.format(1))
        diode = self.GetFootprint(diodeFormat.format(1))
        net1 = switch.FindPadByNumber("2").GetNetname()
        net2 = diode.FindPadByNumber("2").GetNetname()
        tracks = [t for t in self.board.GetTracks() if t.GetNetname() == net1 == net2]

        # convert tracks to list of vectors which will be used by `AddTrackSegmentByPoints`
        switchPadPosition = switch.FindPadByNumber("2").GetPosition()
        diodePadPosition = diode.FindPadByNumber("2").GetPosition()
        if KICAD_VERSION == 7:
            switchPadPosition = wxPoint(switchPadPosition.x, switchPadPosition.y)
            diodePadPosition = wxPoint(diodePadPosition.x, diodePadPosition.y)

        pointsSorted = []
        searchPoint = diodePadPosition
        for i in range(0, len(tracks) + 1):
            for t in list(tracks):
                start = t.GetStart()
                end = t.GetEnd()
                if KICAD_VERSION == 7:
                    start = wxPoint(start.x, start.y)
                    end = wxPoint(end.x, end.y)
                foundStart = start.__eq__(searchPoint)
                foundEnd = end.__eq__(searchPoint)
                if foundStart or foundEnd:
                    pointsSorted.append(searchPoint)
                    searchPoint = end if foundStart else start
                    tracks.remove(t)
                    self.board.RemoveNative(t)
                    break
        if len(pointsSorted) != 0:
            pointsSorted.pop(0)
            pointsSorted.append(switchPadPosition)

        reducedPoints = [p.__sub__(diodePadPosition) for p in pointsSorted]
        self.logger.info("Detected template switch-to-diode path: {}".format(reducedPoints))
        return reducedPoints

    def Run(self, keyFormat, stabilizerFormat, diodeFormat, diodePosition, routeTracks=False):
        self.logger.info("Diode position: {}".format(diodePosition))

        templateTracks = []
        if routeTracks:
            # check if first switch-diode pair is already routed, if yes,
            # then reuse its track shape for remaining pairs, otherwise try to use automatic 'router'
            templateTracks = self.CheckIfDiodeRouted(keyFormat, diodeFormat)

        column_switch_pads = {}
        row_diode_pads = {}
        for key in self.layout["keys"]:
            switchFootprint, stabilizer = self.GetCurrentKey(keyFormat, stabilizerFormat)

            width = key["width"]
            height = key["height"]
            position = wxPoint((self.keyDistance * key["x"]) + (self.keyDistance * width // 2),
                (self.keyDistance * key["y"]) + (self.keyDistance * height // 2)) + self.referenceCoordinate
            self.SetPosition(switchFootprint, position)
            self.ResetRotation(switchFootprint)

            if stabilizer:
                self.SetPosition(stabilizer, position)
                self.ResetRotation(stabilizer)
                # recognize special case of ISO enter:
                width2 = key["width2"]
                height2 = key["height2"]
                if width == 1.25 and height == 2 and width2 == 1.5 and height2 == 1:
                    stabilizer.SetOrientationDegrees(90)

            diodeFootprint = self.GetCurrentDiode(diodeFormat)
            self.ResetRotation(diodeFootprint)
            self.SetSide(diodeFootprint, diodePosition.side)
            diodeFootprint.SetOrientationDegrees(diodePosition.orientation)
            self.SetRelativePositionMM(diodeFootprint, position, diodePosition.relativePosition.toList())

            angle = key["rotation_angle"]
            if angle != 0:
                rotationReference = wxPoint((self.keyDistance * key["rotation_x"]), (self.keyDistance * key["rotation_y"])) + self.referenceCoordinate
                self.Rotate(switchFootprint, rotationReference, angle)
                if stabilizer:
                    self.Rotate(stabilizer, rotationReference, angle)
                self.Rotate(diodeFootprint, rotationReference, angle)

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
                self.RouteSwitchWithDiode(switchFootprint, diodeFootprint, angle, templateTracks)

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
                        y_diff = builtins.abs(pos1.y - pos2.y)
                        x_diff = builtins.abs(pos1.x - pos2.x)
                        vector = [0, (y_diff - x_diff)]
                        if vector[1] <= 0:
                            self.logger.warning("Switch pad to far to route 2 segment track with 45 degree angles")
                        else:
                            lastPosition = self.AddTrackSegment(pos1, vector, layer=F_Cu)
                            if lastPosition:
                                self.AddTrackSegmentByPoints(lastPosition, pos2, layer=F_Cu)

            for row in row_diode_pads:
                pads = row_diode_pads[row]
                positions = [pad.GetPosition() for pad in pads]
                # we can assume that all diodes are on the same side:
                layer = B_Cu if self.GetSide(pad.GetParent()) == Side.BACK else F_Cu
                for pos1, pos2 in zip(positions, positions[1:]):
                    if pos1.y == pos2.y:
                        self.AddTrackSegmentByPoints(pos1, pos2, layer)
                    else:
                        self.logger.warning("Automatic diode routing supported only when diodes aligned vertically")

            self.RemoveDanglingTracks()
