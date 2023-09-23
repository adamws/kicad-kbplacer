from __future__ import annotations

import itertools
from logging import Logger
from typing import Tuple

import pcbnew

from .element_position import Side

# remove pre-release and build numbers (if present) and split to major-minor-patch tuple
KICAD_VERSION = tuple(
    map(int, ((pcbnew.Version().split("+")[0]).split("-")[0]).split("."))
)
DEFAULT_CLEARANCE_MM = 0.25


def set_position(footprint: pcbnew.FOOTPRINT, position: pcbnew.wxPoint) -> None:
    if KICAD_VERSION >= (7, 0, 0):
        footprint.SetPosition(pcbnew.VECTOR2I(position.x, position.y))
    else:
        footprint.SetPosition(position)


def get_position(footprint: pcbnew.FOOTPRINT) -> pcbnew.wxPoint:
    position = footprint.GetPosition()
    if KICAD_VERSION >= (7, 0, 0):
        return pcbnew.wxPoint(position.x, position.y)
    return position


def rotate(
    footprint: pcbnew.BOARD_ITEM,
    rotation_reference: pcbnew.wxPoint,
    angle: float,
) -> None:
    if KICAD_VERSION >= (7, 0, 0):
        footprint.Rotate(
            pcbnew.VECTOR2I(rotation_reference.x, rotation_reference.y),
            pcbnew.EDA_ANGLE(angle * -1, pcbnew.DEGREES_T),
        )
    else:
        footprint.Rotate(rotation_reference, angle * -10)


def get_distance(i1: pcbnew.BOARD_ITEM, i2: pcbnew.BOARD_ITEM) -> int:
    """Calculate distance between two board items"""
    center1 = i1.GetPosition()
    center2 = i2.GetPosition()
    return int(((center1.x - center2.x) ** 2 + (center1.y - center2.y) ** 2) ** 0.5)


def get_common_nets(f1: pcbnew.FOOTPRINT, f2: pcbnew.FOOTPRINT) -> list[int]:
    """Returns list of netcodes which are used by both of the
    given footprints, may be empty if no common nets found
    """
    codes1 = [p.GetNetCode() for p in f1.Pads()]
    codes2 = [p.GetNetCode() for p in f2.Pads()]
    return list(set(codes1).intersection(codes2))


def get_closest(
    pads1: list[pcbnew.PAD], pads2: list[pcbnew.PAD]
) -> Tuple[int, Tuple[pcbnew.PAD, pcbnew.PAD]]:
    all_pairs = itertools.product(pads1, pads2)
    min_distance, closest_pair = min(
        ((get_distance(obj1, obj2), (obj1, obj2)) for obj1, obj2 in all_pairs),
        key=lambda x: x[0],
    )
    return min_distance, closest_pair


def get_closest_pads_on_same_net(
    f1: pcbnew.FOOTPRINT, f2: pcbnew.FOOTPRINT
) -> Tuple[pcbnew.PAD, pcbnew.PAD] | None:
    """Return pair of closest, same net pads of two given footprints
    or None if footprints do not use common net
    """
    pads1 = {}
    for p in f1.Pads():
        if netname := p.GetNetname():
            pads1.setdefault(netname, []).append(p)

    pads2 = {}
    for p in f2.Pads():
        netname = p.GetNetname()
        if netname in pads1:
            pads2.setdefault(netname, []).append(p)

    result = None
    closest = float("inf")
    for key, value in pads2.items():
        distance, result_temp = get_closest(value, pads1[key])
        if distance < closest:
            closest = distance
            result = result_temp

    # We iterated with pads2 so we need to swap reult to keep original
    # order in tuple, first pad should be from f1, second from f2
    # Some caller might require proper order
    if result:
        return result[1], result[0]
    return result


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

    def get_optional_footprint(self, reference: str) -> pcbnew.FOOTPRINT | None:
        try:
            footprint = self.get_footprint(reference)
        except Exception as _:
            footprint = None
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

                    # track has non default netlist set so we can skip
                    # collision detection for pad of same netlist:
                    if track_net_code != 0 and track_net_code == p.GetNetCode():
                        self.logger.debug(
                            f"Track collision ignored, pad {reference}:{pad_name} "
                            f"on same netlist: {track.GetNetname()}/{p.GetNetname()}"
                        )
                        continue

                    # if track starts or ends in pad then assume that
                    # this collision is expected, with the exception of case
                    # where track already has netlist set and it is different
                    # than pad's netlist
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
                                "Track collision ignored, track starts or ends "
                                f"in pad {reference}:{pad_name}"
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
                t.m_Uuid != track.m_Uuid
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
                        "Track collision ignored, track starts or ends "
                        f"at the end of {track_uuid} track"
                    )
                    # ignoring one track means that we can ignore
                    # all other connected to it:
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
                                "Pad collision removed due to connection with track "
                                "which leads to that pad"
                            )
                            collide_list.remove(collision)
                elif hit_test_result := t.GetEffectiveShape().Collide(
                    track_shape, pcbnew.FromMM(DEFAULT_CLEARANCE_MM)
                ):
                    self.logger.debug(f"Track collide with another track: {track_uuid}")
                    collide_list.append(t)
        for collision in list(collide_list):
            if collision.m_Uuid in tracks_to_clear:
                collision_uuid = collision.m_Uuid.AsString()
                self.logger.debug(
                    f"Track collision with {collision_uuid} removed due to "
                    "connection with track which leads to it"
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
        if KICAD_VERSION >= (7, 0, 0):
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
        rotate(footprint, rotation_reference, angle)

    def set_side(self, footprint: pcbnew.FOOTPRINT, side: Side) -> None:
        if side ^ self.get_side(footprint):
            footprint.Flip(footprint.GetPosition(), False)

    def get_side(self, footprint: pcbnew.FOOTPRINT) -> Side:
        return Side(footprint.IsFlipped())

    def set_rotation(self, footprint: pcbnew.FOOTPRINT, angle: float) -> None:
        footprint.SetOrientationDegrees(angle)

    def reset_rotation(self, footprint: pcbnew.FOOTPRINT) -> None:
        self.set_rotation(footprint, 0)

    def get_orientation(self, footprint: pcbnew.FOOTPRINT) -> float:
        return footprint.GetOrientationDegrees()
