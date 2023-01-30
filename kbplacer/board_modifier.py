from dataclasses import dataclass
from enum import Flag
from pcbnew import *


class Side(Flag):
    FRONT = False
    BACK = True


@dataclass
class Point:
    x: float
    y: float

    def toList(self):
        return [self.x, self.y]


class BoardModifier():
    def __init__(self, logger, board):
        self.logger = logger
        self.board = board

    def GetFootprint(self, reference):
        self.logger.info("Searching for {} footprint".format(reference))
        footprint = self.board.FindFootprintByReference(reference)
        if footprint == None:
            self.logger.error("Footprint not found")
            raise Exception("Cannot find footprint {}".format(reference))
        return footprint

    def SetPosition(self, footprint, position):
        self.logger.info("Setting {} footprint position: {}".format(footprint.GetReference(), position))
        footprint.SetPosition(position)

    def GetPosition(self, footprint):
        position = footprint.GetPosition()
        self.logger.info("Getting {} footprint position: {}".format(footprint.GetReference(), position))
        return position

    def SetRelativePositionMM(self, footprint, referencePoint, direction):
        position = wxPoint(referencePoint.x + FromMM(direction[0]), referencePoint.y + FromMM(direction[1]))
        self.SetPosition(footprint, position)

    def AddTrackSegment(self, start, vector, layer=B_Cu):
        track = PCB_TRACK(self.board)
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
        track = PCB_TRACK(self.board)
        track.SetWidth(FromMM(0.25))
        track.SetLayer(layer)
        track.SetStart(start)
        track.SetEnd(stop)

        layerName = self.board.GetLayerName(layer)
        self.logger.info("Adding track segment ({}): [{}, {}]".format(layerName, start, stop))
        self.board.Add(track)

        return stop

    def Rotate(self, footprint, rotationReference, angle):
        self.logger.info("Rotating {} footprint: rotationReference: {}, rotationAngle: {}".format(footprint.GetReference(), rotationReference, angle))
        footprint.Rotate(rotationReference, angle * -10)

    def SetSide(self, footprint, side: Side):
        if side ^ self.GetSide(footprint):
            footprint.Flip(footprint.GetPosition(), False)

    def GetSide(self, footprint):
        return Side(footprint.IsFlipped())

