from __future__ import annotations

import builtins
import math
import re
from logging import Logger
from typing import List, Optional, Tuple, cast

import pcbnew

from .board_modifier import (
    KICAD_VERSION,
    BoardModifier,
    get_closest_pads_on_same_net,
    get_common_nets,
    rotate,
)
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
        self.__reference_coordinate = pcbnew.wxPointMM(25, 25)

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
        template_connection: List[pcbnew.PCB_TRACK] | None = None,
    ) -> None:
        """Performs routing between switch and diode elements.
        It uses two closest (to each other) pads of the same net.

        :param switch: Switch footprint to be routed.
        :param diode: Diode footprint to be routed.
        :param angle: Rotation angle (in degrees) of switch footprint
                      (diode rotation is assumed to be the same)
        :param template_connection: List of template elements (tracks and vias) for
                                    routing switch and diode pads. Normalised to
                                    switch position coordinate. Templates
                                    items must not have netcodes assigned.
                                    If None, use automatic routing algorithm.
        :type switch: FOOTPRINT
        :type diode: FOOTPRINT
        :type angle: float
        :type template_connection: List[pcbnew.PCB_TRACK] | None
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
        if template_connection:
            if angle != 0:
                self.logger.info(f"Routing at {angle} degree angle")
            switch_position = self.get_position(switch)
            for item in template_connection:
                # item is either PCB_TRACK or PCB_VIA, since via extends track
                # we should be safe with `Cast_to_PCB_TRACK` (not doing any via
                # specific operations here)
                track = pcbnew.Cast_to_PCB_TRACK(item)
                new_track = track.Duplicate()
                if KICAD_VERSION >= (7, 0, 0):
                    new_track.Move(pcbnew.VECTOR2I(switch_position.x, switch_position.y))
                else:
                    new_track.Move(switch_position)
                if angle != 0:
                    rotate(new_track, switch_position, angle)
                self.add_track_to_board(new_track)
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
        # TODO: perhaps add support for using diferent pair as reference,
        # we no longer require strict 1-to-1 mapping between switches and diodes
        # so `D1` does not have to exist
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

    def get_connection_template(
        self, key_format: str, diode_format: str
    ) -> List[pcbnew.PCB_TRACK]:
        switch = self.get_footprint(key_format.format(1))
        diode = self.get_optional_footprint(diode_format.format(1))
        if not diode:
            return []

        result = []
        origin = self.get_position(switch)

        connectivity = self.get_connectivity()
        common_nets = get_common_nets(switch, diode)

        def _append_normalized_connection_items(netcode: int) -> None:
            items = connectivity.GetNetItems(
                netcode, [pcbnew.PCB_TRACE_T, pcbnew.PCB_VIA_T]
            )
            for item in items:
                item_copy = item.Duplicate()
                item_copy.SetNetCode(0)
                if KICAD_VERSION >= (7, 0, 0):
                    item_copy.Move(pcbnew.VECTOR2I(-origin.x, -origin.y))
                else:
                    item_copy.Move(pcbnew.wxPoint(-origin.x, -origin.y))

                self.board.RemoveNative(item)
                result.append(item_copy)

        for net in common_nets:
            _append_normalized_connection_items(net)

        # some switch footprints (for example reversible) can have multiple pads
        # with the same netcode which might 'pre-routed' as well.
        # get nets unique to switch (not shared with diode) and collect connection
        # temple from them as well.
        switch_nets = [p.GetNetCode() for p in switch.Pads()]
        switch_unique_nets = list(set(switch_nets) - set(common_nets))
        for net in switch_unique_nets:
            _append_normalized_connection_items(net)

        return result

    def place_switches(
        self,
        keyboard: Keyboard,
        key_format: str,
    ) -> None:
        current_key = 1

        for key in keyboard.keys:
            switch_footprint = self.get_footprint(key_format.format(current_key))

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

            current_key += 1

    def place_switch_elements(
        self,
        key_format: str,
        elements: List[ElementInfo],
    ) -> None:
        for i, switch_footprint in SwitchIterator(self.board, key_format):
            position = self.get_position(switch_footprint)
            orientation = self.get_orientation(switch_footprint)
            for element_info in elements:
                annotation_format = element_info.annotation_format
                element_position = element_info.position
                footprint = self.get_optional_footprint(annotation_format.format(i))
                if footprint and element_position:
                    self.reset_rotation(footprint)
                    self.set_side(footprint, element_position.side)
                    self.set_rotation(footprint, element_position.orientation)

                    offset = pcbnew.wxPointMM(
                        *element_position.relative_position.to_list()
                    )
                    if orientation != 0:
                        offset = position_in_rotated_coordinates(offset, orientation)

                    self.set_position(footprint, position + offset)
                    if orientation != 0:
                        current_position = self.get_position(footprint)
                        self.rotate(footprint, current_position, -1 * orientation)

    def run(
        self,
        layout: dict,
        key_format: str,
        diode_info: Optional[ElementInfo],
        route_tracks: bool = False,
        additional_elements: List[ElementInfo] = [],
    ) -> None:
        diode_format = ""
        template_connection = []

        if diode_info:
            self.logger.info(f"Diode info: {diode_info}")
            diode_format = diode_info.annotation_format
            if route_tracks:
                # check if first switch-diode pair is already routed, if yes,
                # then reuse its tracks and vias for remaining pairs,
                # otherwise try to use automatic 'router'
                template_connection = self.get_connection_template(
                    key_format, diode_format
                )
            additional_elements = [diode_info] + additional_elements

        for element_info in additional_elements:
            if element_info.position_option == PositionOption.CURRENT_RELATIVE:
                position = self.get_current_relative_element_position(
                    key_format, element_info.annotation_format
                )
                element_info.position = position

        if layout:
            self.logger.info(f"User layout: {layout}")
            keyboard = get_keyboard(layout)
            self.place_switches(keyboard, key_format)

        if additional_elements:
            self.place_switch_elements(key_format, additional_elements)

        if route_tracks:
            for i, switch_footprint in SwitchIterator(self.board, key_format):
                angle = -1 * switch_footprint.GetOrientationDegrees()

                if diode_footprint := self.get_optional_footprint(
                    diode_format.format(i)
                ):
                    self.route_switch_with_diode(
                        switch_footprint, diode_footprint, angle, template_connection
                    )
            # when done, delete all template items
            for item in template_connection:
                self.board.RemoveNative(item)

            # TODO: extract this to some separate class/method:
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
                for pad1, pad2 in zip(pads, pads[1:]):
                    if pad1.GetParentAsString() == pad2.GetParentAsString():
                        # do not connect pads of the same footprint
                        continue
                    pos1 = pad1.GetPosition()
                    pos2 = pad2.GetPosition()
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
