from __future__ import annotations

import pcbnew
from logging import Logger

from .element_position import Side


KICAD_VERSION = int(pcbnew.Version().split(".")[0])
DEFAULT_CLEARANCE_MM = 0.25


def set_position(footprint: pcbnew.FOOTPRINT, position: pcbnew.wxPoint) -> None:
    if KICAD_VERSION == 7:
        footprint.SetPosition(pcbnew.VECTOR2I(position.x, position.y))
    else:
        footprint.SetPosition(position)


def get_position(footprint: pcbnew.FOOTPRINT) -> pcbnew.wxPoint:
    position = footprint.GetPosition()
    if KICAD_VERSION == 7:
        return pcbnew.wxPoint(position.x, position.y)
    return position


class BoardModifier:
    def __init__(self, logger: Logger, board: pcbnew.BOARD) -> None:
        self.logger = logger
        self.board = board

    def get_connectivity(self):
        self.board.BuildConnectivity()
        return self.board.GetConnectivity()

    def get_footprint(self, reference: str) -> pcbnew.FOOTPRINT:
        self.logger.info(f"Searching for {reference} footprint")
        footprint = self.board.FindFootprintByReference(reference)
        if footprint is None:
            self.logger.error("Footprint not found")
            msg = f"Cannot find footprint {reference}"
            raise Exception(msg)
        return footprint

    def set_position(
        self, footprint: pcbnew.FOOTPRINT, position: pcbnew.wxPoint
    ) -> None:
        self.logger.info(
            f"Setting {footprint.GetReference()} footprint position: {position}"
        )
        set_position(footprint, position)

    def set_position_by_points(
        self, footprint: pcbnew.FOOTPRINT, x: int, y: int
    ) -> None:
        self.set_position(footprint, pcbnew.wxPoint(x, y))

    def get_position(self, footprint: pcbnew.FOOTPRINT) -> pcbnew.wxPoint:
        position = get_position(footprint)
        self.logger.info(
            f"Getting {footprint.GetReference()} footprint position: {position}"
        )
        return position

    def set_relative_position_mm(
        self,
        footprint: pcbnew.FOOTPRINT,
        reference_point: pcbnew.wxPoint,
        direction: list[float],
    ) -> None:
        position = pcbnew.wxPoint(
            reference_point.x + pcbnew.FromMM(direction[0]),
            reference_point.y + pcbnew.FromMM(direction[1]),
        )
        self.set_position(footprint, position)

    def test_track_collision(self, track: pcbnew.PCB_TRACK) -> bool:
        collide_list = []
        track_shape = track.GetEffectiveShape()
        track_start = track.GetStart()
        track_end = track.GetEnd()
        track_net_code = track.GetNetCode()
        # connectivity needs to be last,
        # otherwise it will update track net name before we want it to:
        connectivity = self.get_connectivity()
        for f in self.board.GetFootprints():
            reference = f.GetReference()
            hull = f.GetBoundingHull()
            if hit_test_result := hull.Collide(track_shape):
                for p in f.Pads():
                    pad_name = p.GetName()
                    pad_shape = p.GetEffectiveShape()

                    # track has non default netlist set so we can skip collision detection
                    # for pad of same netlist:
                    if track_net_code != 0 and track_net_code == p.GetNetCode():
                        self.logger.debug(
                            f"Track collision ignored, pad {reference}:{pad_name} "
                            f"on same netlist: {track.GetNetname()}/{p.GetNetname()}"
                        )
                        continue

                    # if track starts or ends in pad than assume this collision is expected,
                    # with the execption of case where track already has netlist set
                    # and it is different than pad's netlist
                    if p.HitTest(track_start) or p.HitTest(track_end):
                        if (
                            track_net_code != 0
                            and track_net_code != p.GetNetCode()
                            and p.IsOnLayer(track.GetLayer())
                        ):
                            self.logger.debug(
                                f"Track collide with pad {reference}:{pad_name}"
                            )
                            collide_list.append(p)
                        else:
                            self.logger.debug(
                                f"Track collision ignored, track starts or ends in pad {reference}:{pad_name}"
                            )
                    else:
                        hit_test_result = pad_shape.Collide(
                            track_shape, pcbnew.FromMM(DEFAULT_CLEARANCE_MM)
                        )
                        on_same_layer = p.IsOnLayer(track.GetLayer())
                        if hit_test_result and on_same_layer:
                            self.logger.debug(
                                f"Track collide with pad {reference}:{pad_name}"
                            )
                            collide_list.append(p)
        # track ids to clear at the end:
        tracks_to_clear = []
        for t in self.board.GetTracks():
            # check collision if not itself, on same layer and with different netlist
            # (unless 'trackNetCode' is default '0' netlist):
            if (
                t.m_Uuid.__ne__(track.m_Uuid)
                and t.IsOnLayer(track.GetLayer())
                and (track_net_code != t.GetNetCode() or track_net_code == 0)
            ):
                track_uuid = t.m_Uuid.AsString()
                if (
                    track_start == t.GetStart()
                    or track_start == t.GetEnd()
                    or track_end == t.GetStart()
                    or track_end == t.GetEnd()
                ):
                    self.logger.debug(
                        f"Track collision ignored, track starts or ends at the end of {track_uuid} track"
                    )
                    # ignoring one track means that we can ignore all other connected to it:
                    tracks_to_clear += [
                        x.m_Uuid for x in connectivity.GetConnectedTracks(t)
                    ]
                    # check if connection to this track clears pad collision:
                    connected_pads_ids = [
                        x.m_Uuid for x in connectivity.GetConnectedPads(t)
                    ]
                    for collision in list(collide_list):
                        if collision.m_Uuid in connected_pads_ids:
                            self.logger.debug(
                                "Pad collision removed due to connection with track which leads to that pad"
                            )
                            collide_list.remove(collision)
                elif hit_test_result := t.GetEffectiveShape().Collide(
                    track_shape, pcbnew.FromMM(DEFAULT_CLEARANCE_MM)
                ):
                    self.logger.debug(
                        f"Track collide with another track: {track_uuid}"
                    )
                    collide_list.append(t)
        for collision in list(collide_list):
            if collision.m_Uuid in tracks_to_clear:
                collision_uuid = collision.m_Uuid.AsString()
                self.logger.debug(
                    f"Track collision with {collision_uuid} removed due to connection with track which leads to it"
                )
                collide_list.remove(collision)
        return len(collide_list) != 0

    def add_track_to_board(self, track: pcbnew.PCB_TRACK):
        """Add track to the board if track passes collision check.
        If track has no set netlist, it would get netlist of a pad
        or other track, on which it started or ended.
        Collision with element of the same netlist will be ignored
        unless it is default '0' netlist.
        This exception about '0' netlist is important because it helps
        to detect collisions with holes.

        :param track: A track to be added to board
        :return: End position of added track or None if failed to add.
        """
        if not self.test_track_collision(track):
            layer_name = self.board.GetLayerName(track.GetLayer())
            start = track.GetStart()
            stop = track.GetEnd()
            self.logger.info(
                f"Adding track segment ({layer_name}): [{start}, {stop}]",
            )
            self.board.Add(track)
            return stop
        else:
            self.logger.warning("Could not add track segment due to detected collision")
            return None

    def add_track_segment_by_points(
        self, start: pcbnew.wxPoint, end: pcbnew.wxPoint, layer=pcbnew.B_Cu
    ):
        track = pcbnew.PCB_TRACK(self.board)
        track.SetWidth(pcbnew.FromMM(0.25))
        track.SetLayer(layer)
        if KICAD_VERSION == 7:
            track.SetStart(pcbnew.VECTOR2I(start.x, start.y))
            track.SetEnd(pcbnew.VECTOR2I(end.x, end.y))
        else:
            track.SetStart(start)
            track.SetEnd(end)
        return self.add_track_to_board(track)

    def add_track_segment(
        self, start: pcbnew.wxPoint, vector: list[int], layer=pcbnew.B_Cu
    ):
        end = pcbnew.wxPoint(start.x + vector[0], start.y + vector[1])
        return self.add_track_segment_by_points(start, end, layer)

    def reset_rotation(self, footprint: pcbnew.FOOTPRINT):
        footprint.SetOrientationDegrees(0)

    def rotate(
        self,
        footprint: pcbnew.FOOTPRINT,
        rotation_reference: pcbnew.wxPoint,
        angle: float,
    ) -> None:
        self.logger.info(
            f"Rotating {footprint.GetReference()} footprint: "
            f"rotationReference: {rotation_reference}, rotationAngle: {angle}"
        )
        if KICAD_VERSION == 7:
            footprint.Rotate(
                pcbnew.VECTOR2I(rotation_reference.x, rotation_reference.y),
                pcbnew.EDA_ANGLE(angle * -1, pcbnew.DEGREES_T),
            )
        else:
            footprint.Rotate(rotation_reference, angle * -10)

    def set_side(self, footprint: pcbnew.FOOTPRINT, side: Side) -> None:
        if side ^ self.get_side(footprint):
            footprint.Flip(footprint.GetPosition(), False)

    def get_side(self, footprint: pcbnew.FOOTPRINT) -> Side:
        return Side(footprint.IsFlipped())
