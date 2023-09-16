from __future__ import annotations

import builtins
import math
import re
from logging import Logger
from typing import List, Optional, Tuple, cast

import pcbnew

from .board_modifier import KICAD_VERSION, BoardModifier, get_closest_pads_on_same_net
from .element_position import ElementInfo, ElementPosition, Point, PositionOption, Side
from .kle_serial import Keyboard, get_keyboard


def position_in_rotated_coordinates(
    point: pcbnew.wxPoint, angle: float
) -> pcbnew.wxPoint:
    """
    Map position in xy-Cartesian coordinate system to x'y'-Cartesian which
    has same origin but axes are rotated by angle

    :param point: A point to be mapped
    :param angle: Rotation angle (in degrees) of x'y'-Cartesian coordinates
    :type point: pcbnew.wxPoint
    :type angle: float
    :return: Result position in x'y'-Cartesian coordinates
    :rtype: pcbnew.wxPoint
    """
    x, y = point.x, point.y
    angle = math.radians(angle)
    xr = (x * math.cos(angle)) + (y * math.sin(angle))
    yr = (-x * math.sin(angle)) + (y * math.cos(angle))
    return pcbnew.wxPoint(xr, yr)


def position_in_cartesian_coordinates(
    point: pcbnew.wxPoint, angle: float
) -> pcbnew.wxPoint:
    """Performs inverse operation to position_in_rotated_coordinates i.e.
    map position in rotated (by angle) x'y'-Cartesian to xy-Cartesian

    :param point: A point to be mapped
    :param angle: Rotation angle (in degrees) of x'y'-Cartesian coordinates
    :type point: pcbnew.wxPoint
    :type angle: float
    :return: Result position in xy-Cartesian coordinates
    :rtype: pcbnew.wxPoint
    """
    xr, yr = point.x, point.y
    angle = math.radians(angle)
    x = (xr * math.cos(angle)) - (yr * math.sin(angle))
    y = (xr * math.sin(angle)) + (yr * math.cos(angle))
    return pcbnew.wxPoint(x, y)


class SwitchIterator:
    def __init__(self, board: pcbnew.BOARD, annotation: str) -> None:
        self.__board = board
        self.__annotation = annotation

    def __iter__(self):
        self.__current_key = 1
        return self

    def __next__(self):
        reference = self.__annotation.format(self.__current_key)
        footprint = self.__board.FindFootprintByReference(reference)
        if footprint:
            result = self.__current_key, footprint
            self.__current_key += 1
            return result
        else:
            raise StopIteration


class KeyPlacer(BoardModifier):
    def __init__(
        self,
        logger: Logger,
        board: pcbnew.BOARD,
        key_distance: Tuple[float, float] = (19.05, 19.05),
    ) -> None:
        super().__init__(logger, board)

        self.__key_distance_x = cast(int, pcbnew.FromMM(key_distance[0]))
        self.__key_distance_y = cast(int, pcbnew.FromMM(key_distance[1]))

        self.logger.debug(
            f"Set key 1U distance: {self.__key_distance_x}/{self.__key_distance_y}"
        )
        self.__current_key = 1
        self.__reference_coordinate = pcbnew.wxPointMM(25, 25)

    def get_current_key(self, key_format: str) -> pcbnew.FOOTPRINT:
        return self.get_footprint(key_format.format(self.__current_key))

    def get_current_footprint(
        self, annotation_format: str
    ) -> Optional[pcbnew.FOOTPRINT]:
        try:
            f = self.get_footprint(annotation_format.format(self.__current_key))
        except:
            f = None
        return f

    def calculate_corner_position_of_switch_diode_route(
        self, diode_pad_position: pcbnew.wxPoint, switch_pad_position: pcbnew.wxPoint
    ) -> pcbnew.wxPoint:
        x_diff = diode_pad_position.x - switch_pad_position.x
        y_diff = diode_pad_position.y - switch_pad_position.y
        if builtins.abs(x_diff) < builtins.abs(y_diff):
            up_or_down = -1 if y_diff > 0 else 1
            return pcbnew.wxPoint(
                diode_pad_position.x - x_diff,
                diode_pad_position.y + (up_or_down * builtins.abs(x_diff)),
            )
        else:
            left_or_right = -1 if x_diff > 0 else 1
            return pcbnew.wxPoint(
                diode_pad_position.x + (left_or_right * builtins.abs(y_diff)),
                diode_pad_position.y - y_diff,
            )

    def route_switch_with_diode(
        self,
        switch: pcbnew.FOOTPRINT,
        diode: pcbnew.FOOTPRINT,
        angle: float,
        template_track_points=None,
    ) -> None:
        """Performs routing between switch and diode elements.
        It uses two closest (to each other) pads of the same net.

        :param switch: Switch footprint to be routed.
        :param diode: Diode footprint to be routed.
        :param angle: Rotation angle (in degrees) of switch footprint
                      (diode rotation is assumed to be the same)
        :param templateTrackPoints: List of positions (relative to diode pad position)
                                    of track corners connecting switch and diode closest
                                    pads of the same net name.
                                    Does not support vias, will be routed on the layer
                                    of the diode.
                                    If None, use automatic routing algorithm.
        :type switch: FOOTPRINT
        :type diode: FOOTPRINT
        :type angle: float
        :type templateTrackPoints: List[pcbnew.wxPoint]
        """
        self.logger.info(f"Routing {switch.GetReference()} with {diode.GetReference()}")

        if result := get_closest_pads_on_same_net(switch, diode):
            switch_pad, diode_pad = result
        else:
            self.logger.error("Could not find pads with the same net, routing skipped")
            return

        switch_pad_position = switch_pad.GetPosition()
        diode_pad_position = diode_pad.GetPosition()
        if KICAD_VERSION >= (7, 0, 0):
            switch_pad_position = pcbnew.wxPoint(
                switch_pad_position.x, switch_pad_position.y
            )
            diode_pad_position = pcbnew.wxPoint(
                diode_pad_position.x, diode_pad_position.y
            )

        self.logger.debug(
            f"switchPadPosition: {switch_pad_position}, "
            f"diodePadPosition: {diode_pad_position}",
        )

        layer = pcbnew.B_Cu if self.get_side(diode) == Side.BACK else pcbnew.F_Cu
        if template_track_points:
            if angle != 0:
                self.logger.info(f"Routing at {angle} degree angle")
            start = diode_pad_position
            for t in template_track_points:
                if angle != 0:
                    diode_pad_position_r = position_in_rotated_coordinates(
                        diode_pad_position, angle
                    )
                    end = t.__add__(diode_pad_position_r)
                    end = position_in_cartesian_coordinates(end, angle)
                else:
                    end = t.__add__(diode_pad_position)
                if end := self.add_track_segment_by_points(start, end, layer):
                    start = end
        elif (
            switch_pad_position.x == diode_pad_position.x
            or switch_pad_position.y == diode_pad_position.y
        ):
            self.add_track_segment_by_points(
                diode_pad_position, switch_pad_position, layer
            )
        else:
            # pads are not in single line, attempt routing with two segment track
            if angle != 0:
                self.logger.info(f"Routing at {angle} degree angle")
                switch_pad_position_r = position_in_rotated_coordinates(
                    switch_pad_position, angle
                )
                diode_pad_position_r = position_in_rotated_coordinates(
                    diode_pad_position, angle
                )

                self.logger.debug(
                    "In rotated coordinates: "
                    f"switchPadPosition: {switch_pad_position_r}, "
                    f"diodePadPosition: {diode_pad_position_r}",
                )

                corner = self.calculate_corner_position_of_switch_diode_route(
                    diode_pad_position_r, switch_pad_position_r
                )
                corner = position_in_cartesian_coordinates(corner, angle)
            else:
                corner = self.calculate_corner_position_of_switch_diode_route(
                    diode_pad_position, switch_pad_position
                )

            # first segment: at 45 degree angle
            # (might be in rotated coordinate system) towards switch pad
            self.add_track_segment_by_points(diode_pad_position, corner, layer)
            # second segment: up to switch pad
            self.add_track_segment_by_points(corner, switch_pad_position, layer)

    def get_current_relative_element_position(
        self, key_format: str, element_format: str
    ) -> ElementPosition:
        key1 = self.get_footprint(key_format.format(1))
        element1 = self.get_footprint(element_format.format(1))
        pos1 = self.get_position(key1)
        pos2 = self.get_position(element1)
        x = cast(float, pcbnew.ToMM(pos2.x - pos1.x))
        y = cast(float, pcbnew.ToMM(pos2.y - pos1.y))
        return ElementPosition(
            Point(x, y),
            element1.GetOrientationDegrees(),
            self.get_side(element1),
        )

    def remove_dangling_tracks(self) -> None:
        connectivity = self.get_connectivity()

        def _is_dangling(track):
            if KICAD_VERSION >= (7, 0, 7):
                return connectivity.TestTrackEndpointDangling(track, False)
            return connectivity.TestTrackEndpointDangling(track)

        for track in self.board.GetTracks():
            if _is_dangling(track):
                self.board.RemoveNative(track)

    def check_if_diode_routed(
        self, key_format: str, diode_format: str
    ) -> list[pcbnew.wxPoint]:
        switch = self.get_footprint(key_format.format(1))
        diode = self.get_footprint(diode_format.format(1))

        if result := get_closest_pads_on_same_net(switch, diode):
            switch_pad, diode_pad = result
        else:
            self.logger.error(
                "Could not find pads with the same net, "
                "routing template not obtained"
            )
            return []

        net1 = switch_pad.GetNetname()
        net2 = diode_pad.GetNetname()
        # TODO: check if there is a better way to get tracks between two elements
        # without itereting over all tracks of the board:
        tracks = [t for t in self.board.GetTracks() if t.GetNetname() == net1 == net2]

        # convert tracks to list of vectors which will be used
        # by `AddTrackSegmentByPoints`
        switch_pad_position = switch_pad.GetPosition()
        diode_pad_position = diode_pad.GetPosition()
        if KICAD_VERSION >= (7, 0, 0):
            switch_pad_position = pcbnew.wxPoint(
                switch_pad_position.x, switch_pad_position.y
            )
            diode_pad_position = pcbnew.wxPoint(
                diode_pad_position.x, diode_pad_position.y
            )

        points_sorted = []
        search_point = diode_pad_position
        for _ in range(0, len(tracks) + 1):
            for t in list(tracks):
                start = t.GetStart()
                end = t.GetEnd()
                if KICAD_VERSION >= (7, 0, 0):
                    start = pcbnew.wxPoint(start.x, start.y)
                    end = pcbnew.wxPoint(end.x, end.y)
                found_start = start.__eq__(search_point)
                found_end = end.__eq__(search_point)
                if found_start or found_end:
                    points_sorted.append(search_point)
                    search_point = end if found_start else start
                    tracks.remove(t)
                    self.board.RemoveNative(t)
                    break
        if points_sorted:
            points_sorted.pop(0)
            points_sorted.append(switch_pad_position)

        reduced_points = [p.__sub__(diode_pad_position) for p in points_sorted]
        self.logger.info(f"Detected template switch-to-diode path: {reduced_points}")
        return reduced_points

    def place_switches(
        self,
        keyboard: Keyboard,
        key_format: str,
        additional_elements: List[ElementInfo] = [],
    ) -> None:
        self.__current_key = 1

        for key in keyboard.keys:
            switch_footprint = self.get_current_key(key_format)

            width = key.width
            height = key.height
            position = (
                pcbnew.wxPoint(
                    (self.__key_distance_x * key.x)
                    + (self.__key_distance_x * width // 2),
                    (self.__key_distance_y * key.y)
                    + (self.__key_distance_y * height // 2),
                )
                + self.__reference_coordinate
            )
            self.set_position(switch_footprint, position)
            self.reset_rotation(switch_footprint)

            for element_info in additional_elements:
                annotation_format = element_info.annotation_format
                element_position = element_info.position
                footprint = self.get_current_footprint(annotation_format)
                if footprint and element_position:
                    self.reset_rotation(footprint)
                    self.set_side(footprint, element_position.side)
                    footprint.SetOrientationDegrees(element_position.orientation)
                    self.set_relative_position_mm(
                        footprint,
                        position,
                        element_position.relative_position.to_list(),
                    )

            angle = key.rotation_angle
            if angle != 0:
                rotation_reference = (
                    pcbnew.wxPoint(
                        (self.__key_distance_x * key.rotation_x),
                        (self.__key_distance_y * key.rotation_y),
                    )
                    + self.__reference_coordinate
                )
                self.rotate(switch_footprint, rotation_reference, angle)
                if additional_elements:
                    for element_info in additional_elements:
                        annotation_format = element_info.annotation_format
                        if footprint := self.get_current_footprint(annotation_format):
                            self.rotate(footprint, rotation_reference, angle)

            self.__current_key += 1

    def run(
        self,
        layout: dict,
        key_format: str,
        diode_info: Optional[ElementInfo],
        route_tracks: bool = False,
        additional_elements: List[ElementInfo] = [],
    ) -> None:
        diode_format = ""
        template_tracks = []

        if diode_info:
            self.logger.info(f"Diode info: {diode_info}")
            diode_format = diode_info.annotation_format
            if route_tracks:
                # check if first switch-diode pair is already routed, if yes,
                # then reuse its track shape for remaining pairs,
                # otherwise try to use automatic 'router'
                template_tracks = self.check_if_diode_routed(key_format, diode_format)
            additional_elements = [diode_info] + additional_elements

        for element_info in additional_elements:
            if element_info.position_option == PositionOption.CURRENT_RELATIVE:
                position = self.get_current_relative_element_position(
                    key_format, element_info.annotation_format
                )
                element_info.position = position

        if layout:
            # TODO: handle additional elements seprately if layout missing, allow
            # to place elements to already placed switches (without layout defined by user)
            self.logger.info(f"User layout: {layout}")
            keyboard = get_keyboard(layout)
            self.place_switches(keyboard, key_format, additional_elements)

        if route_tracks:
            for i, switch_footprint in SwitchIterator(self.board, key_format):
                angle = -1 * switch_footprint.GetOrientationDegrees()

                if diode_footprint := self.board.FindFootprintByReference(
                    diode_format.format(i)
                ):
                    self.route_switch_with_diode(
                        switch_footprint, diode_footprint, angle, template_tracks
                    )

            column_pads = {}
            row_pads = {}

            sorted_pads = pcbnew.PADS_VEC()
            self.board.GetSortedPadListByXthenYCoord(sorted_pads)
            for pad in sorted_pads:
                net_name = pad.GetNetname()
                if match := re.match(r"^COL(\d+)$", net_name, re.IGNORECASE):
                    column_number = match.groups()[0]
                    column_pads.setdefault(column_number, []).append(pad)
                elif match := re.match(r"^ROW(\d+)$", net_name, re.IGNORECASE):
                    row_number = match.groups()[0]
                    row_pads.setdefault(row_number, []).append(pad)

            # very naive routing approach, will fail in some scenarios:
            for pads in column_pads.values():
                positions = [pad.GetPosition() for pad in pads]
                for pos1, pos2 in zip(positions, positions[1:]):
                    # connect two pads together
                    if pos1.x == pos2.x:
                        self.add_track_segment_by_points(pos1, pos2, layer=pcbnew.F_Cu)
                    else:
                        # two segment track
                        y_diff = builtins.abs(pos1.y - pos2.y)
                        x_diff = builtins.abs(pos1.x - pos2.x)
                        vector = [0, (y_diff - x_diff)]
                        if vector[1] <= 0:
                            self.logger.warning(
                                "Switch pad to far to route 2 segment track "
                                "with 45 degree angles"
                            )
                        elif last_position := self.add_track_segment(
                            pos1, vector, layer=pcbnew.F_Cu
                        ):
                            self.add_track_segment_by_points(
                                last_position, pos2, layer=pcbnew.F_Cu
                            )

            for row in row_pads:
                pads = row_pads[row]
                positions = [pad.GetPosition() for pad in pads]
                # we can assume that all diodes are on the same side:
                layer = (
                    pcbnew.B_Cu
                    if self.get_side(pads[0].GetParent()) == Side.BACK
                    else pcbnew.F_Cu
                )
                for pos1, pos2 in zip(positions, positions[1:]):
                    if pos1.y == pos2.y:
                        self.add_track_segment_by_points(pos1, pos2, layer)
                    else:
                        self.logger.warning(
                            "Automatic diode routing supported only when "
                            "diodes aligned vertically"
                        )

            self.remove_dangling_tracks()
