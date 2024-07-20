from __future__ import annotations

import builtins
import itertools
import logging
import math
import re
from typing import Optional, Tuple, Union

import pcbnew

from .element_position import Side

logger = logging.getLogger(__name__)
version_match = re.search(r"(\d+)\.(\d+)\.(\d+)", pcbnew.Version())
KICAD_VERSION = tuple(map(int, version_match.groups())) if version_match else ()
if KICAD_VERSION == ():
    logger.warning("Could not determine KiCad version")


def position_in_rotated_coordinates(
    point: pcbnew.VECTOR2I, angle: float
) -> pcbnew.VECTOR2I:
    """
    Map position in xy-Cartesian coordinate system to x'y'-Cartesian which
    has same origin but axes are rotated by angle

    :param point: A point to be mapped
    :param angle: Rotation angle (in degrees) of x'y'-Cartesian coordinates
    :type point: pcbnew.VECTOR2I
    :type angle: float
    :return: Result position in x'y'-Cartesian coordinates
    :rtype: pcbnew.VECTOR2I
    """
    x, y = point.x, point.y
    angle = math.radians(angle)
    xr = (x * math.cos(angle)) + (y * math.sin(angle))
    yr = (-x * math.sin(angle)) + (y * math.cos(angle))
    return pcbnew.VECTOR2I(int(xr), int(yr))


def position_in_cartesian_coordinates(
    point: pcbnew.VECTOR2I, angle: float
) -> pcbnew.VECTOR2I:
    """Performs inverse operation to position_in_rotated_coordinates i.e.
    map position in rotated (by angle) x'y'-Cartesian to xy-Cartesian

    :param point: A point to be mapped
    :param angle: Rotation angle (in degrees) of x'y'-Cartesian coordinates
    :type point: pcbnew.VECTOR2I
    :type angle: float
    :return: Result position in xy-Cartesian coordinates
    :rtype: pcbnew.VECTOR2I
    """
    xr, yr = point.x, point.y
    angle = math.radians(angle)
    x = (xr * math.cos(angle)) - (yr * math.sin(angle))
    y = (xr * math.sin(angle)) + (yr * math.cos(angle))
    return pcbnew.VECTOR2I(int(x), int(y))


def get_footprint(board: pcbnew.BOARD, reference: str) -> pcbnew.FOOTPRINT:
    logger.debug(f"Searching for {reference} footprint in {board.GetFileName()}")
    footprint = board.FindFootprintByReference(reference)
    if footprint is None:
        msg = f"Cannot find footprint {reference}"
        raise RuntimeError(msg)
    return footprint


def get_optional_footprint(
    board: pcbnew.BOARD, reference: str
) -> pcbnew.FOOTPRINT | None:
    logger.debug(
        f"Searching for optional {reference} footprint in {board.GetFileName()}"
    )
    footprint = board.FindFootprintByReference(reference)
    if footprint is None:
        logger.debug("Footprint not found")
    return footprint


def set_position(footprint: pcbnew.FOOTPRINT, position: pcbnew.VECTOR2I) -> None:
    logger.debug(f"Setting {footprint.GetReference()} footprint position: {position}")
    if KICAD_VERSION < (7, 0, 0):
        footprint.SetPosition(pcbnew.wxPoint(position.x, position.y))
    else:
        footprint.SetPosition(position)


def set_position_by_points(footprint: pcbnew.FOOTPRINT, x: int, y: int) -> None:
    set_position(footprint, pcbnew.VECTOR2I(x, y))


def get_position(footprint: pcbnew.FOOTPRINT) -> pcbnew.VECTOR2I:
    position = footprint.GetPosition()
    logger.debug(f"Getting {footprint.GetReference()} footprint position: {position}")
    if KICAD_VERSION < (7, 0, 0):
        return pcbnew.VECTOR2I(position)
    return position


def set_side(footprint: pcbnew.FOOTPRINT, side: Side) -> None:
    if side != get_side(footprint):
        footprint.Flip(footprint.GetPosition(), False)


def get_side(footprint: pcbnew.FOOTPRINT) -> Side:
    if footprint.IsFlipped():
        return Side.BACK
    else:
        return Side.FRONT


def set_rotation(footprint: pcbnew.FOOTPRINT, angle: float) -> None:
    footprint.SetOrientationDegrees(angle)


def reset_rotation(footprint: pcbnew.FOOTPRINT) -> None:
    set_rotation(footprint, 0)


def get_orientation(footprint: pcbnew.FOOTPRINT) -> float:
    return footprint.GetOrientationDegrees()


def rotate(
    item: pcbnew.BOARD_ITEM,
    rotation_reference: pcbnew.VECTOR2I,
    angle: float,
) -> None:
    if KICAD_VERSION < (7, 0, 0):
        item.Rotate(
            pcbnew.wxPoint(rotation_reference.x, rotation_reference.y), angle * -10
        )
    else:
        item.Rotate(
            rotation_reference,
            pcbnew.EDA_ANGLE(angle * -1, pcbnew.DEGREES_T),
        )


def get_distance(i1: pcbnew.BOARD_ITEM, i2: pcbnew.BOARD_ITEM) -> int:
    """Calculate distance between two board items"""
    center1 = i1.GetPosition()
    center2 = i2.GetPosition()
    return int(((center1.x - center2.x) ** 2 + (center1.y - center2.y) ** 2) ** 0.5)


def get_common_layers(p1: pcbnew.PAD, p2: pcbnew.PAD) -> list[int]:
    """Returns list of common layer ids for both of the given pads,
    may be empty if no common layers found
    """
    set1 = [layer for layer in p1.GetLayerSet().CuStack()]
    set2 = [layer for layer in p2.GetLayerSet().CuStack()]
    return list(set(set1).intersection(set2))


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

    # We iterated with pads2 so we need to swap result to keep original
    # order in tuple, first pad should be from f1, second from f2
    # Some caller might require proper order
    if result:
        return result[1], result[0]
    return result


def get_clearance(
    i1: pcbnew.BOARD_CONNECTED_ITEM, i2: pcbnew.BOARD_CONNECTED_ITEM
) -> int:
    if KICAD_VERSION < (7, 0, 0):
        # workaround for bug in KiCad 6.x python wrapper:
        import _pcbnew

        def _own_clearance(item: pcbnew.BOARD_CONNECTED_ITEM) -> int:
            if item.Type() == pcbnew.PCB_PAD_T:
                return _pcbnew.PAD_GetOwnClearance(item, item.GetLayer())
            else:
                return _pcbnew.BOARD_CONNECTED_ITEM_GetOwnClearance(
                    item, item.GetLayer()
                )

        return max(_own_clearance(i1), _own_clearance(i2))
    else:
        return max(i1.GetOwnClearance(i1.GetLayer()), i2.GetOwnClearance(i2.GetLayer()))


class BoardModifier:
    def __init__(self, board: pcbnew.BOARD) -> None:
        self.board = board

    def get_connectivity(self) -> pcbnew.CONNECTIVITY_DATA:
        self.board.BuildConnectivity()
        return self.board.GetConnectivity()

    def _test_collision_track_without_net(self, track: pcbnew.PCB_TRACK) -> bool:
        collide_list = []
        track_shape = track.GetEffectiveShape()
        track_start = track.GetStart()
        track_end = track.GetEnd()
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

                    # if track starts or ends in pad then assume that
                    # this collision is expected, with the exception of case
                    # where track already has netlist set and it is different
                    # than pad's netlist or pad has `NPTH` attribute
                    if p.HitTest(track_start) or p.HitTest(track_end):
                        logger.debug(
                            "Track collision ignored, track starts or ends "
                            f"in pad {reference}:{pad_name}"
                        )
                    else:
                        hit_test_result = pad_shape.Collide(
                            track_shape, get_clearance(p, track)
                        )
                        on_same_layer = p.IsOnLayer(track.GetLayer())
                        if hit_test_result and on_same_layer:
                            logger.debug(
                                f"Track collide with pad {reference}:{pad_name}"
                            )
                            collide_list.append(p)
        # track ids to clear at the end:
        tracks_to_clear = []
        for t in self.board.GetTracks():
            # check collision if not itself and on same layer
            if t.m_Uuid != track.m_Uuid and t.IsOnLayer(track.GetLayer()):
                track_uuid = t.m_Uuid.AsString()
                if (
                    track_start == t.GetStart()
                    or track_start == t.GetEnd()
                    or track_end == t.GetStart()
                    or track_end == t.GetEnd()
                ):
                    logger.debug(
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
                            logger.debug(
                                "Pad collision removed due to connection with track "
                                "which leads to that pad"
                            )
                            collide_list.remove(collision)
                elif hit_test_result := t.GetEffectiveShape().Collide(
                    track_shape, get_clearance(t, track)
                ):
                    logger.debug(f"Track collide with another track: {track_uuid}")
                    collide_list.append(t)
        for collision in list(collide_list):
            if collision.m_Uuid in tracks_to_clear:
                collision_uuid = collision.m_Uuid.AsString()
                logger.debug(
                    f"Track collision with {collision_uuid} removed due to "
                    "connection with track which leads to it"
                )
                collide_list.remove(collision)
        return len(collide_list) != 0

    def _test_collision_track_with_net(self, track: pcbnew.PCB_TRACK) -> bool:
        track_netcode = track.GetNetCode()
        track_shape = track.GetEffectiveShape()
        track_layer = track.GetLayer()
        for item in self.board.AllConnectedItems():
            if track_netcode == item.GetNetCode():
                continue

            item_shape = item.GetEffectiveShape()
            if item_shape.Collide(track_shape, get_clearance(item, track)):
                if isinstance(item.Cast(), pcbnew.PCB_TRACK):
                    if item.GetLayer() == track_layer:
                        return True
                elif isinstance(item.Cast(), pcbnew.PAD):
                    pad = pcbnew.Cast_to_PAD(item)
                    if (
                        pad.IsOnLayer(track_layer)
                        or pad.GetAttribute == pcbnew.PAD_ATTRIB_NPTH
                    ):
                        return True
                # pcbnew.ZONE is remaining possibility but we do not handle it
        return False

    def test_track_collision(self, track: pcbnew.PCB_TRACK) -> bool:
        if track.GetNetCode() == 0:
            return self._test_collision_track_without_net(track)
        return self._test_collision_track_with_net(track)

    def add_track_to_board(
        self, track: pcbnew.PCB_TRACK
    ) -> Optional[Union[pcbnew.VECTOR2I, pcbnew.wxPoint]]:
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
        layer_name = self.board.GetLayerName(track.GetLayer())
        start = track.GetStart()
        stop = track.GetEnd()
        logger.info(
            f"Adding track segment ({layer_name}): [{start}, {stop}]",
        )
        if not self.test_track_collision(track):
            self.board.Add(track)
            logger.info("Track added")
            return stop
        else:
            logger.debug("Could not add track segment due to detected collision")
            return None

    def add_track_segment_by_points(
        self,
        start: pcbnew.VECTOR2I,
        end: pcbnew.VECTOR2I,
        layer: int = pcbnew.B_Cu,
        netcode: int = 0,
    ) -> Optional[Union[pcbnew.VECTOR2I, pcbnew.wxPoint]]:
        track = pcbnew.PCB_TRACK(self.board)
        track.SetWidth(pcbnew.FromMM(0.25))
        track.SetLayer(layer)
        if netcode:
            track.SetNetCode(netcode)
        if KICAD_VERSION < (7, 0, 0):
            track.SetStart(pcbnew.wxPoint(start.x, start.y))
            track.SetEnd(pcbnew.wxPoint(end.x, end.y))
        else:
            track.SetStart(start)
            track.SetEnd(end)
        return self.add_track_to_board(track)

    def route(self, pad1: pcbnew.PAD, pad2: pcbnew.PAD) -> None:
        r"""Simple track router
        If pads are collinear, it will use single track segment.
        If pads are not collinear it will try use two segments track,
        in first try, it will fanout straight segment from `pad1` to
        `pad2` direction and then it will end it with second segment
        at 45degree angle:

        |pad| ____
        | 1 |     \
                   \
                  |pad|
                  | 2 |

        If this does not succeed (it is not possible using 45degree angles
        and two segments only or there is collision detected),
        then it will try to switch track posture:

        |pad|
        | 1 |
          \
           \______|pad|
                  | 2 |

        If this is not possible as well, it will leave pads unconnected
        and will not try another route.

        If both parent footprint are rotated the same, it might
        route track at that angle.
        Footprint is considered rotated, if its orientation is different than
        0, 90, 180 and 270. When comparing rotations use angle to closest
        quarter, i.e. footprints with orientation 10 and 190 (190-180=10) are
        considered to be rotated the same.
        """
        layers = get_common_layers(pad1, pad2)
        if not layers:
            logger.warning("Could not route pads, no common layers found")
            return

        layer = layers[0]
        logger.debug(f"Routing at {self.board.GetLayerName(layer)} layer")

        if pad1.GetNetCode() != pad2.GetNetCode():
            logger.warning("Could not route pads of different nets")
            return

        netcode = pad1.GetNetCode()

        def _calculate_corners(
            pos1: pcbnew.VECTOR2I, pos2: pcbnew.VECTOR2I
        ) -> Tuple[pcbnew.VECTOR2I, pcbnew.VECTOR2I]:
            x_diff = pos2.x - pos1.x
            y_diff = pos2.y - pos1.y
            x_diff_abs = builtins.abs(x_diff)
            y_diff_abs = builtins.abs(y_diff)
            if x_diff_abs < y_diff_abs:
                up_or_down = -1 if y_diff > 0 else 1
                return (
                    pcbnew.VECTOR2I(pos1.x, pos2.y + (up_or_down * x_diff_abs)),
                    pcbnew.VECTOR2I(pos2.x, pos1.y - (up_or_down * x_diff_abs)),
                )
            else:
                left_or_right = -1 if x_diff > 0 else 1
                return (
                    pcbnew.VECTOR2I(pos2.x + (left_or_right * y_diff_abs), pos1.y),
                    pcbnew.VECTOR2I(pos1.x - (left_or_right * y_diff_abs), pos2.y),
                )

        def _route(
            pos1: pcbnew.VECTOR2I, pos2: pcbnew.VECTOR2I, corner: pcbnew.VECTOR2I
        ) -> bool:
            if end := self.add_track_segment_by_points(pos1, corner, layer, netcode):
                end = self.add_track_segment_by_points(end, pos2, layer, netcode)
                return end is not None
            return False

        def _angles_equal(angle1: float, angle2: float) -> bool:
            return abs(angle1 - angle2) <= 0.1

        pos1 = pad1.GetPosition()
        pos2 = pad2.GetPosition()

        parent1 = pad1.GetParent()
        parent2 = pad2.GetParent()

        if KICAD_VERSION >= (8, 0, 0):
            parent1 = pcbnew.Cast_to_FOOTPRINT(parent1)
            parent2 = pcbnew.Cast_to_FOOTPRINT(parent2)

        orientation1 = get_orientation(parent1)
        orientation2 = get_orientation(parent2)

        if _angles_equal(orientation1 % 90, 0) and _angles_equal(orientation2 % 90, 0):
            # this could be merged with next elif but being close to zero is special
            # i.e. we clamp to 0 when near:
            angle = 0
        elif _angles_equal(orientation1 % 90, orientation2 % 90):
            # if rotations are considered the same use the angle
            angle = (-1 * orientation1 + 360) % 360
        else:
            logger.warning(
                "Could not route pads when parent footprints not rotated the same, "
                f"orientations: {orientation1} and {orientation2}"
            )
            return

        logger.debug(
            f"Routing pad '{pad1.GetParentAsString()}:{pad1.GetPadName()}' at {pos1} "
            f"with pad '{pad2.GetParentAsString()}:{pad2.GetPadName()}' at {pos2} "
            f"using coordinate system rotated by {angle} degree(s)"
        )

        # if in line, use one track segment
        if pos1.x == pos2.x or pos1.y == pos2.y:
            self.add_track_segment_by_points(pos1, pos2, layer, netcode)
        else:
            # pads are not in single line, attempt routing with two segment track
            if angle != 0:
                pos1_r = position_in_rotated_coordinates(pos1, angle)
                pos2_r = position_in_rotated_coordinates(pos2, angle)
                corners = _calculate_corners(pos1_r, pos2_r)
                corners = (
                    position_in_cartesian_coordinates(corners[0], angle),
                    position_in_cartesian_coordinates(corners[1], angle),
                )
            else:
                corners = _calculate_corners(pos1, pos2)

            if not _route(pos1, pos2, corners[0]):
                _route(pos1, pos2, corners[1])
