from __future__ import annotations

import itertools
import logging
import os
import re
from pathlib import Path
from typing import List, Tuple, cast

import pcbnew

from .board_modifier import (
    KICAD_VERSION,
    BoardModifier,
    get_closest_pads_on_same_net,
    get_common_nets,
    get_footprint,
    get_optional_footprint,
    get_orientation,
    get_position,
    get_side,
    position_in_rotated_coordinates,
    reset_rotation,
    rotate,
    set_position,
    set_rotation,
    set_side,
)
from .element_position import ElementInfo, ElementPosition, Point, PositionOption
from .kle_serial import Keyboard, get_keyboard

logger = logging.getLogger(__name__)


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
        board: pcbnew.BOARD,
        key_distance: Tuple[float, float] = (19.05, 19.05),
    ) -> None:
        super().__init__(board)

        self.__key_distance_x = cast(int, pcbnew.FromMM(key_distance[0]))
        self.__key_distance_y = cast(int, pcbnew.FromMM(key_distance[1]))

        logger.debug(
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
        logger.info(f"Routing {switch.GetReference()} with {diode.GetReference()}")

        if template_connection:
            logger.info("Using template replication method")
            if angle != 0:
                logger.info(f"Routing at {angle} degree angle")
            switch_position = get_position(switch)
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
            logger.info("Using internal autorouter method")
            switch_pad, diode_pad = result
            self.route(switch_pad, diode_pad)
        else:
            logger.error("Could not find pads with the same net, routing skipped")

    def get_current_relative_element_position(
        self, element1: pcbnew.FOOTPRINT, element2: pcbnew.FOOTPRINT
    ) -> ElementPosition:
        """Returns position of element2 in relation to element1
        in element1 coordinate system (i.e centered in element1 center
        and rotated by its rotation)
        """
        pos1 = get_position(element1)
        pos2 = get_position(element2)
        rot1 = get_orientation(element1)
        rot2 = get_orientation(element2)
        if rot1:
            pos1 = position_in_rotated_coordinates(pos1, -rot1)
            pos2 = position_in_rotated_coordinates(pos2, -rot1)

        x = cast(float, pcbnew.ToMM(pos2.x - pos1.x))
        y = cast(float, pcbnew.ToMM(pos2.y - pos1.y))

        return ElementPosition(
            Point(x, y),
            rot2 - rot1,
            get_side(element2),
        )

    def remove_dangling_tracks(self) -> None:
        logger.info("Removing dangling tracks")
        connectivity = self.get_connectivity()

        any_removed = False

        def _is_dangling(track):
            if KICAD_VERSION >= (7, 0, 7):
                return connectivity.TestTrackEndpointDangling(track, False)
            return connectivity.TestTrackEndpointDangling(track)

        for track in self.board.GetTracks():
            if _is_dangling(track):
                logger.info(f"Removing {track.m_Uuid.AsString()}")
                self.board.RemoveNative(track)
                any_removed = True

        if any_removed:
            self.remove_dangling_tracks()

    def save_connection_template(
        self,
        switch: pcbnew.FOOTPRINT,
        diode: pcbnew.FOOTPRINT,
        connections: List[pcbnew.PCB_TRACK],
        destination_path: str,
    ) -> None:
        logger.info(f"Saving template to {destination_path}")
        # can't use `CreateEmptyBoard` when running inside KiCad.
        # We want new board file but without new project file,
        # looks like this is not possible with pcbnew API.
        # So create board with project
        board = pcbnew.NewBoard(destination_path)
        # and delete project file
        os.remove(Path(destination_path).with_suffix(".kicad_pro"))

        switch_copy = pcbnew.Cast_to_FOOTPRINT(switch.Duplicate())
        reset_rotation(switch_copy)
        set_position(switch_copy, pcbnew.wxPoint(0, 0))

        origin = get_position(switch)
        diode_copy = pcbnew.Cast_to_FOOTPRINT(diode.Duplicate())
        if angle := get_orientation(switch):
            rotate(diode_copy, origin, angle)
        set_position(
            diode_copy,
            get_position(diode_copy) - pcbnew.wxPoint(origin.x, origin.y),
        )

        for p in itertools.chain(switch_copy.Pads(), diode_copy.Pads()):
            if p.GetNetCode() != 0:
                logger.info(
                    f"Adding net {p.GetNetname()} with netcode {p.GetNetCode()}"
                )
                # adding nets to new board will get them new autoassigned netcodes
                # (the one set at `NETINFO_ITEM` constructor will be discarded)
                net = pcbnew.NETINFO_ITEM(board, p.GetNetname(), -1)
                board.Add(net)

        nets = board.GetNetsByName()
        # synchronize net codes
        for p in itertools.chain(switch_copy.Pads(), diode_copy.Pads()):
            if p.GetNetCode() != 0:
                before = p.GetNetCode()
                p.SetNet(nets[p.GetNetname()])
                logger.info(
                    f"Updating pad '{p.GetParentAsString()}:{p.GetPadName()}' "
                    f"net {p.GetNetname()} netcode: {before} -> {p.GetNetCode()}"
                )

        board.Add(switch_copy)
        board.Add(diode_copy)

        for item in connections:
            # using `Duplicate` here to not alter net assignments of original tracks
            # (which needs to be empty in order to work as template)
            board.Add(item.Duplicate())
        pcbnew.SaveBoard(destination_path, board, aSkipSettings=True)

    def get_connection_template(
        self, key_format: str, diode_format: str, destination_path: str
    ) -> List[pcbnew.PCB_TRACK]:
        """Returns list of tracks (including vias) connecting first element
        with reference `key_format` with first element with reference `diode_format`
        and optionally save it to new `pcbnew` template file.
        The coordinates of returned elements are normalized to center of `key_format`
        element. If `key_format` element is rotated, resulting coordinates are rotated
        back so the template is always in natural (0) orientation.
        """
        switch = get_footprint(self.board, key_format.format(1))
        diode = get_optional_footprint(self.board, diode_format.format(1))
        if not diode:
            return []

        result = []
        origin = get_position(switch)

        connectivity = self.get_connectivity()
        common_nets = get_common_nets(switch, diode)

        def _append_normalized_connection_items(netcode: int) -> None:
            items = connectivity.GetNetItems(
                netcode, [pcbnew.PCB_TRACE_T, pcbnew.PCB_VIA_T]
            )
            for item in items:
                item_copy = item.Duplicate()
                item_copy.SetNetCode(0)
                if angle := get_orientation(switch):
                    rotate(item_copy, origin, angle)
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
        logger.info(f"Got connection template: {items_str}")

        if destination_path:
            self.save_connection_template(switch, diode, result, destination_path)

        return result

    def load_connection_preset(
        self, key_format: str, diode_format: str, source_path: str
    ) -> List[pcbnew.PCB_TRACK]:
        board = pcbnew.LoadBoard(source_path)
        tracks = board.GetTracks()
        for t in tracks:
            t.SetNetCode(0)
        return tracks

    def place_switches(
        self,
        keyboard: Keyboard,
        key_format: str,
    ) -> None:
        current_key = 1

        for key in keyboard.keys:
            switch_footprint = get_footprint(self.board, key_format.format(current_key))

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
            set_position(switch_footprint, position)
            reset_rotation(switch_footprint)

            angle = key.rotation_angle
            if angle != 0:
                rotation_reference = (
                    pcbnew.wxPoint(
                        (self.__key_distance_x * key.rotation_x),
                        (self.__key_distance_y * key.rotation_y),
                    )
                    + self.__reference_coordinate
                )
                rotate(switch_footprint, rotation_reference, angle)

            current_key += 1

    def place_switch_elements(
        self,
        key_format: str,
        elements: List[ElementInfo],
    ) -> None:
        for i, switch_footprint in SwitchIterator(self.board, key_format):
            position = get_position(switch_footprint)
            orientation = get_orientation(switch_footprint)
            for element_info in elements:
                annotation_format = element_info.annotation_format
                element_position = element_info.position
                footprint = get_optional_footprint(
                    self.board, annotation_format.format(i)
                )
                if footprint and element_position:
                    reset_rotation(footprint)
                    set_side(footprint, element_position.side)
                    set_rotation(footprint, element_position.orientation)

                    offset = pcbnew.wxPointMM(
                        *element_position.relative_position.to_list()
                    )
                    if orientation != 0:
                        offset = position_in_rotated_coordinates(offset, orientation)

                    set_position(footprint, position + offset)
                    if orientation != 0:
                        current_position = get_position(footprint)
                        rotate(footprint, current_position, -1 * orientation)

    def route_switches_with_diodes(
        self,
        key_format: str,
        diode_format: str,
        template_connection: List[pcbnew.PCB_TRACK],
    ) -> None:
        for i, switch_footprint in SwitchIterator(self.board, key_format):
            angle = -1 * switch_footprint.GetOrientationDegrees()

            if diode_footprint := get_optional_footprint(
                self.board, diode_format.format(i)
            ):
                self.route_switch_with_diode(
                    switch_footprint, diode_footprint, angle, template_connection
                )
        # when done, delete all template items
        for item in template_connection:
            self.board.RemoveNative(item)

    def route_rows_and_columns(self) -> None:
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

    def run(
        self,
        layout: dict,
        key_format: str,
        diode_info: ElementInfo,
        route_switches_with_diodes: bool = False,
        route_rows_and_columns: bool = False,
        additional_elements: List[ElementInfo] = [],
    ) -> None:
        diode_format = ""
        template_connection = []

        def _normalize_template_path(template_path: str) -> str:
            if str(Path(template_path).name) == template_path:
                # if passed filename without directory,
                # assume that this refers to file in the directory of
                # current board. This is mostly for CLI convenience
                template_path = str(
                    Path(self.board.GetFileName()).parent / template_path
                )
            return template_path

        logger.info(f"Diode info: {diode_info}")
        diode_format = diode_info.annotation_format
        if diode_info.position_option != PositionOption.UNCHANGED:
            if diode_info.position_option == PositionOption.RELATIVE:
                template_connection = self.get_connection_template(
                    key_format, diode_format, diode_info.template_path
                )
            elif diode_info.position_option == PositionOption.PRESET:
                logger.info(
                    f"Loading diode connection preset from {diode_info.template_path}"
                )
                template_connection = self.load_connection_preset(
                    key_format,
                    diode_format,
                    _normalize_template_path(diode_info.template_path),
                )
            additional_elements = [diode_info] + additional_elements

        for element_info in additional_elements:
            if element_info.position_option in [
                PositionOption.RELATIVE,
                PositionOption.PRESET,
            ]:
                if element_info.position_option == PositionOption.PRESET:
                    source = pcbnew.IO_MGR.Load(
                        pcbnew.IO_MGR.KICAD_SEXP,
                        _normalize_template_path(element_info.template_path),
                    )
                else:
                    source = self.board

                element1 = get_footprint(source, key_format.format(1))
                element2 = get_footprint(
                    source, element_info.annotation_format.format(1)
                )
                position = self.get_current_relative_element_position(
                    element1, element2
                )
                element_info.position = position
                logger.info(f"Element info updated: {element_info}")

        if layout:
            logger.info(f"User layout: {layout}")
            keyboard = get_keyboard(layout)
            self.place_switches(keyboard, key_format)

        if additional_elements:
            self.place_switch_elements(key_format, additional_elements)

        if route_switches_with_diodes:
            self.route_switches_with_diodes(
                key_format, diode_format, template_connection
            )

        if route_rows_and_columns:
            self.route_rows_and_columns()

        if route_switches_with_diodes or route_rows_and_columns:
            self.remove_dangling_tracks()
