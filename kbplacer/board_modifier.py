from dataclasses import dataclass
from enum import Flag
from pcbnew import *


DEFAULT_CLEARANCE_MM = 0.25


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

    def SetPosition(self, footprint, position: wxPoint):
        self.logger.info("Setting {} footprint position: {}".format(footprint.GetReference(), position))
        footprint.SetPosition(position)

    def SetPositionByPoints(self, footprint, x: int, y: int):
        self.SetPosition(footprint, wxPoint(x, y))

    def GetPosition(self, footprint):
        position = footprint.GetPosition()
        self.logger.info("Getting {} footprint position: {}".format(footprint.GetReference(), position))
        return position

    def SetRelativePositionMM(self, footprint, referencePoint, direction):
        position = wxPoint(referencePoint.x + FromMM(direction[0]), referencePoint.y + FromMM(direction[1]))
        self.SetPosition(footprint, position)

    def TestTrackCollision(self, track):
        collide = False
        trackShape = track.GetEffectiveShape()
        trackStart = track.GetStart()
        trackEnd = track.GetEnd()
        for f in self.board.GetFootprints():
            reference = f.GetReference()
            hull = f.GetBoundingHull()
            hitTestResult = hull.Collide(trackShape)
            if hitTestResult:
                for p in f.Pads():
                    padName = p.GetName()
                    padShape = p.GetEffectiveShape()
                    # if track starts or ends in pad than assume this collision is expected
                    if p.HitTest(trackStart) or p.HitTest(trackEnd):
                        self.logger.info("Pad {}:{} - collision ignored, track starts or ends in pad".format(reference, padName))
                    else:
                        hitTestResult = padShape.Collide(trackShape, FromMM(DEFAULT_CLEARANCE_MM))
                        onSameLayer = p.IsOnLayer(track.GetLayer())
                        if hitTestResult and onSameLayer:
                            self.logger.info("Track collide pad {}:{}".format(reference, padName))
                            collide = True
                            break
        for t in self.board.GetTracks():
            # do not check collision with itself:
            if t.m_Uuid.__ne__(track.m_Uuid) and t.IsOnLayer(track.GetLayer()):
                if trackStart == t.GetStart() or trackStart == t.GetEnd() or trackEnd == t.GetStart() or trackEnd == t.GetEnd():
                    self.logger.info("Collision ignored, track starts or ends at the end of another track")
                else:
                    hitTestResult = t.GetEffectiveShape().Collide(trackShape, FromMM(DEFAULT_CLEARANCE_MM))
                    if hitTestResult:
                        self.logger.info("Track collide with another track")
                        collide = True
                        break
        return collide

    def AddTrackToBoard(self, track):
        if not self.TestTrackCollision(track):
            layerName = self.board.GetLayerName(track.GetLayer())
            start = track.GetStart()
            stop = track.GetEnd()
            self.logger.info("Adding track segment ({}): [{}, {}]".format(layerName, start, stop))
            self.board.Add(track)
            return stop
        else:
            self.logger.warning("Could not add track segment due to detected collision")
            return None

    def AddTrackSegmentByPoints(self, start, stop, layer=B_Cu):
        track = PCB_TRACK(self.board)
        track.SetWidth(FromMM(0.25))
        track.SetLayer(layer)
        track.SetStart(start)
        track.SetEnd(stop)
        return self.AddTrackToBoard(track)

    def AddTrackSegment(self, start, vector, layer=B_Cu):
        stop = wxPoint(start.x + vector[0], start.y + vector[1])
        return self.AddTrackSegmentByPoints(start, stop, layer)

    def Rotate(self, footprint, rotationReference, angle):
        self.logger.info("Rotating {} footprint: rotationReference: {}, rotationAngle: {}".format(footprint.GetReference(), rotationReference, angle))
        footprint.Rotate(rotationReference, angle * -10)

    def SetSide(self, footprint, side: Side):
        if side ^ self.GetSide(footprint):
            footprint.Flip(footprint.GetPosition(), False)

    def GetSide(self, footprint):
        return Side(footprint.IsFlipped())

