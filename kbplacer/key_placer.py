from __future__ import annotations

import re
from logging import Logger
from typing import List, Optional, Tuple, cast

import pcbnew

from .board_modifier import (
    KICAD_VERSION,
    BoardModifier,
    get_closest_pads_on_same_net,
    get_common_nets,
    position_in_rotated_coordinates,
    rotate,
)
from .element_position import ElementInfo, ElementPosition, Point, PositionOption
from .kle_serial import Keyboard, get_keyboard


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

        if template_connection:
            self.logger.info("Using template replication method")
            if angle != 0:
                self.logger.info(f"Routing at {angle} degree angle")
            switch_position = self.get_position(switch)
            rejects = []
            for item in template_connection:
                # item is either PCB_TRACK or PCB_VIA, since via extends track
                # we should be safe with `Cast_to_PCB_TRACK` (not doing any via
                # specific operations here)
                track = pcbnew.Cast_to_PCB_TRACK(item)
                new_track = track.Duplicate()
                if KICAD_VERSION >= (7, 0, 0):
                    new_track.Move(
                        pcbnew.VECTOR2I(switch_position.x, switch_position.y)
                    )
                else:
                    new_track.Move(switch_position)
                if angle != 0:
                    rotate(new_track, switch_position, angle)
                result = self.add_track_to_board(new_track)
                # depending on the order of track elements placement, some may not pass
                # collision check (for example when starting from middle segment,
                # if it ends to close to a pad). To avoid rejecting false positives,
                # collect rejects and give them a second chance. Only the 'middle' segments
                # (i.e. not starting in a pad) should be in this list, others should
                # get placed properly (unless indeed colliding with some footprints,
                # for example optional stabilizer holes), so running placement of rejects
                # a second time should succeed.
                if result is None:
                    rejects.append(new_track)
            for item in rejects:
                self.add_track_to_board(item)
        elif result := get_closest_pads_on_same_net(switch, diode):
            self.logger.info("Using internal autorouter method")
            switch_pad, diode_pad = result
            self.route(switch_pad, diode_pad)
        else:
            self.logger.error("Could not find pads with the same net, routing skipped")

    def get_current_relative_element_position(
        self, key_format: str, element_format: str
    ) -> ElementPosition:
        # TODO: perhaps add support for using different pair as reference,
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

        def _format_item(item: pcbnew.PCB_TRACK) -> str:
            if KICAD_VERSION >= (7, 0, 0):
                name = item.GetFriendlyName()
            else:
                name = "Via" if item.Type() == pcbnew.PCB_VIA_T else "Track"
            start = item.GetStart()
            end = item.GetEnd()
            return f"{name} [{start} {end}]"

        items_str = ", ".join([_format_item(i) for i in result])
        self.logger.info(f"Got connection template: {items_str}")
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
                    self.route(pad1, pad2)

            for pads in row_pads.values():
                for pad1, pad2 in zip(pads, pads[1:]):
                    self.route(pad1, pad2)

            self.remove_dangling_tracks()
