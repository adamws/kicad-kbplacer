from __future__ import annotations

import copy
import itertools
import json
import logging
import os
import re
from collections import defaultdict
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, cast

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
from .kle_serial import Keyboard, ViaKeyboard, get_keyboard

logger = logging.getLogger(__name__)


class KeyMatrix:
    def __init__(self, board: pcbnew.BOARD, key_format: str, diode_format: str) -> None:
        self.key_format = key_format
        self.diode_format = diode_format

        self.switches: Dict[str, pcbnew.FOOTPRINT] = {}
        self.switches_by_number: Dict[int, pcbnew.FOOTPRINT] = {}
        self.diodes: Dict[str, List[pcbnew.FOOTPRINT]] = defaultdict(list)
        if key_format:
            key_pattern = re.compile(key_format.format("((\\d)+)"))
            for f in board.GetFootprints():
                reference = f.GetReference()
                if match := re.match(key_pattern, reference):
                    if reference in self.switches:
                        msg = "Duplicate switch reference, footprint reference must be unique"
                        raise Exception(msg)
                    self.switches[reference] = f
                    self.switches_by_number[int(match.group(1))] = f

        # each switch can have 0 or more diodes
        if diode_format:
            diode_pattern = re.compile(diode_format.format("((\\d)+)"))
            for f in board.GetFootprints():
                if re.match(diode_pattern, f.GetReference()):
                    for switch_reference, key in self.switches.items():
                        if get_common_nets(key, f):
                            self.diodes[switch_reference].append(f)

    def __str__(self) -> str:
        mapping: Dict[str, str] = {}
        for reference, diodes in self.diodes.items():
            mapping[reference] = ", ".join([d.GetReference() for d in diodes])
        return "KeyMatrix: " + "; ".join(f"{k}-{v}" for k, v in mapping.items())

    def switch(self, index: int) -> pcbnew.FOOTPRINT:
        return self.switches[self.key_format.format(index)]


class KeyboardSwitchIterator:
    ANNOTATION_LABEL = 10

    class Type(str, Enum):
        DEFAULT = "Default"
        EXPLICIT_ANNOTATIONS = "Explicit Annotations"
        VIA_ROW_KEY_LABELS = "VIA Labels"  # not supported yet

        def __str__(self) -> str:
            return self.value

    def __init__(
        self,
        keyboard: Keyboard,
        key_matrix: KeyMatrix,
    ) -> None:
        self.__keyboard = keyboard
        self.__key_matrix = key_matrix
        self.__type = self.__get_iteration_type(keyboard)

    def __get_iteration_type(self, keyboard: Keyboard) -> Type:
        if isinstance(keyboard, ViaKeyboard):
            return self.Type.VIA_ROW_KEY_LABELS
        else:
            number_of_explicit_annotations = sum(
                str(k.get_label(self.ANNOTATION_LABEL)).isdigit() for k in keyboard.keys
            )
            if number_of_explicit_annotations == len(keyboard.keys):
                return self.Type.EXPLICIT_ANNOTATIONS
            else:
                return self.Type.DEFAULT

    def get_type(self) -> str:
        return str(self.__type)

    def __iter__(self):
        self.__keys = iter(self.__keyboard.keys)
        self.__current_key = 1
        return self

    def __get_footprint(self, key) -> pcbnew.FOOTPRINT:
        if self.__type == self.Type.EXPLICIT_ANNOTATIONS:
            return self.__key_matrix.switch(int(key.labels[self.ANNOTATION_LABEL]))
        else:
            sw = self.__key_matrix.switch(self.__current_key)
            self.__current_key += 1
            return sw

    def __next__(self):
        key = next(self.__keys)
        if key:
            return key, self.__get_footprint(key)
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
        diodes: List[pcbnew.FOOTPRINT],
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
        # not supporting multiple diodes placement yet
        if not len(diodes):
            return
        diode = diodes[0]
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
        diodes: List[pcbnew.FOOTPRINT],
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
        diode_copies = []
        for d in diodes:
            diode_copy = pcbnew.Cast_to_FOOTPRINT(d.Duplicate())
            if angle := get_orientation(switch):
                rotate(diode_copy, origin, angle)
            set_position(
                diode_copy,
                get_position(diode_copy) - pcbnew.wxPoint(origin.x, origin.y),
            )
            diode_copies.append(diode_copy)

        for p in itertools.chain(
            switch_copy.Pads(),
            itertools.chain.from_iterable((d.Pads() for d in diode_copies)),
        ):
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
        for p in itertools.chain(
            switch_copy.Pads(),
            itertools.chain.from_iterable((d.Pads() for d in diode_copies)),
        ):
            if p.GetNetCode() != 0:
                before = p.GetNetCode()
                p.SetNet(nets[p.GetNetname()])
                logger.info(
                    f"Updating pad '{p.GetParentAsString()}:{p.GetPadName()}' "
                    f"net {p.GetNetname()} netcode: {before} -> {p.GetNetCode()}"
                )

        board.Add(switch_copy)
        for d in diode_copies:
            board.Add(d)

        for item in connections:
            # using `Duplicate` here to not alter net assignments of original tracks
            # (which needs to be empty in order to work as template)
            board.Add(item.Duplicate())
        pcbnew.SaveBoard(destination_path, board, aSkipSettings=True)

    def get_connection_template(
        self, key_format: str, diode_format: str, destination_path: str
    ) -> List[pcbnew.PCB_TRACK]:
        """Returns list of tracks (including vias) connecting first element
        with reference `key_format` to itself or any other element
        and optionally save it to new `pcbnew` template file.
        The coordinates of returned elements are normalized to center of `key_format`
        element. If `key_format` element is rotated, resulting coordinates are rotated
        back so the template is always in natural (0) orientation.
        """
        switch = get_footprint(self.board, key_format.format(1))

        logger.info(
            "Looking for connection template between "
            f"{switch.GetReference()} and other elements"
        )
        result = []
        origin = get_position(switch)

        connectivity = self.get_connectivity()
        _tracks: Dict[str, pcbnew.PCB_TRACE_T] = {}

        def _get_connected_tracks(item: pcbnew.BOARD_CONNECTED_ITEM) -> None:
            for t in connectivity.GetConnectedTracks(item):
                uid = t.m_Uuid.AsString()
                if uid not in _tracks:
                    _tracks[uid] = t
                    _get_connected_tracks(t)

        for p in switch.Pads():
            _get_connected_tracks(p)

        for item in _tracks.values():
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
            pattern = re.compile(diode_format.format("(\\d)+"))
            diodes = [
                f
                for f in self.board.GetFootprints()
                if get_common_nets(f, switch) and re.match(pattern, f.GetReference())
            ]
            self.save_connection_template(switch, diodes, result, destination_path)

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
        key_matrix: KeyMatrix,
        key_position: Optional[ElementPosition],
    ) -> None:
        key_iterator = KeyboardSwitchIterator(keyboard, key_matrix)
        logger.info(f"Placing switches with '{key_iterator.get_type()}' iterator")
        for key, switch_footprint in key_iterator:
            reset_rotation(switch_footprint)
            if key_position:
                set_side(switch_footprint, key_position.side)
                set_rotation(switch_footprint, key_position.orientation)

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

    def place_element(
        self,
        footprint: pcbnew.FOOTPRINT,
        element_position: ElementPosition,
        reference_position: pcbnew.wxPoint,
        reference_orientation: float,
    ) -> None:
        reset_rotation(footprint)
        set_side(footprint, element_position.side)
        set_rotation(footprint, element_position.orientation)

        offset = pcbnew.wxPointMM(*element_position.relative_position.to_list())
        if reference_orientation != 0:
            offset = position_in_rotated_coordinates(offset, reference_orientation)

        set_position(footprint, reference_position + offset)
        if reference_orientation != 0:
            current_position = get_position(footprint)
            rotate(footprint, current_position, -1 * reference_orientation)

    def place_diodes(
        self,
        diode_infos: List[ElementInfo],
        key_matrix: KeyMatrix,
    ) -> None:
        if diode_infos and diode_infos[0].position:
            for reference, footprints in key_matrix.diodes.items():
                switch_footprint = key_matrix.switches[reference]
                switch_position = get_position(switch_footprint)
                switch_orientation = get_orientation(switch_footprint)
                for diode, info in zip(footprints, diode_infos):
                    if info.position:
                        self.place_element(
                            diode,
                            info.position,
                            switch_position,
                            switch_orientation,
                        )

    def place_switch_elements(
        self,
        elements: List[ElementInfo],
        key_matrix: KeyMatrix,
    ) -> None:
        for number, switch_footprint in key_matrix.switches_by_number.items():
            switch_position = get_position(switch_footprint)
            switch_orientation = get_orientation(switch_footprint)
            for element_info in elements:
                footprint = get_optional_footprint(
                    self.board,
                    element_info.annotation_format.format(number),
                )
                if footprint and element_info.position:
                    self.place_element(
                        footprint,
                        element_info.position,
                        switch_position,
                        switch_orientation,
                    )

    def route_switches_with_diodes(
        self,
        key_matrix: KeyMatrix,
        template_connection: List[pcbnew.PCB_TRACK],
    ) -> None:
        for reference, footprints in key_matrix.diodes.items():
            switch_footprint = key_matrix.switches[reference]
            angle = -1 * switch_footprint.GetOrientationDegrees()
            self.route_switch_with_diode(
                switch_footprint, footprints, angle, template_connection
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

    def load_template(self, template_path: str) -> pcbnew.BOARD:
        if KICAD_VERSION >= (8, 0, 0):
            return pcbnew.PCB_IO_MGR.Load(pcbnew.PCB_IO_MGR.KICAD_SEXP, template_path)  # type: ignore
        return pcbnew.IO_MGR.Load(pcbnew.IO_MGR.KICAD_SEXP, template_path)  # type: ignore

    def _normalize_template_path(self, template_path: str) -> str:
        if not template_path:
            msg = "Template path can't be empty"
            raise ValueError(msg)
        if str(Path(template_path).name) == template_path:
            # if passed filename without directory,
            # assume that this refers to file in the directory of
            # current board. This is mostly for CLI convenience
            template_path = str(Path(self.board.GetFileName()).parent / template_path)
        return template_path

    def _get_relative_position_source(self, element: ElementInfo) -> pcbnew.BOARD:
        if element.position_option == PositionOption.PRESET:
            return self.load_template(
                self._normalize_template_path(element.template_path)
            )
        else:
            return self.board

    def _update_element_position(
        self, key_info: ElementInfo, element: ElementInfo
    ) -> None:
        if element.position_option in [
            PositionOption.RELATIVE,
            PositionOption.PRESET,
        ]:
            source = self._get_relative_position_source(element)
            element1 = get_footprint(source, key_info.annotation_format.format(1))
            element2 = get_footprint(source, element.annotation_format.format(1))
            element.position = self.get_current_relative_element_position(
                element1, element2
            )
            logger.info(f"Element info updated: {element}")

    def _prepare_diode_infos(
        self, key_matrix: KeyMatrix, diode_info: ElementInfo
    ) -> List[ElementInfo]:
        infos = []
        if diode_info.position_option in [
            PositionOption.RELATIVE,
            PositionOption.PRESET,
        ]:
            source = self._get_relative_position_source(diode_info)
            template_matrix = KeyMatrix(
                source, key_matrix.key_format, diode_info.annotation_format
            )
            if (
                diode_info.position_option == PositionOption.PRESET
                and len(template_matrix.switches) != 1
            ):
                msg = f"Template file '{diode_info.template_path}' must have exactly one switch"
                raise RuntimeError(msg)
            first_switch = min(template_matrix.switches_by_number.keys())
            switch_reference = template_matrix.key_format.format(first_switch)
            switch = template_matrix.switches[switch_reference]
            diodes = template_matrix.diodes[switch_reference]
            for diode in diodes:
                temp_info = copy.copy(diode_info)
                temp_info.position = self.get_current_relative_element_position(
                    switch, diode
                )
                logger.info(f"Element info updated: {temp_info}")
                infos.append(temp_info)
        else:
            infos.append(diode_info)
        return infos

    def _get_template_connection(
        self, key_format: str, diode_info: ElementInfo
    ) -> List[pcbnew.PCB_TRACK]:
        if diode_info.position_option in [
            PositionOption.RELATIVE,
            PositionOption.UNCHANGED,
        ]:
            return self.get_connection_template(
                key_format, diode_info.annotation_format, diode_info.template_path
            )
        elif diode_info.position_option == PositionOption.PRESET:
            logger.info(
                f"Loading diode connection preset from {diode_info.template_path}"
            )
            return self.load_connection_preset(
                key_format,
                diode_info.annotation_format,
                self._normalize_template_path(diode_info.template_path),
            )
        else:
            return []

    def run(
        self,
        layout_path: str,
        key_info: ElementInfo,
        diode_info: ElementInfo,
        route_switches_with_diodes: bool = False,
        route_rows_and_columns: bool = False,
        additional_elements: List[ElementInfo] = [],
    ) -> None:
        # stage 1 - prepare
        key_matrix = KeyMatrix(
            self.board, key_info.annotation_format, diode_info.annotation_format
        )
        logger.info(f"Keyboard matrix: {key_matrix}")
        if any(
            len(diodes) > 1 for diodes in key_matrix.diodes.values()
        ) and diode_info.position_option in [
            PositionOption.DEFAULT,
            PositionOption.CUSTOM,
        ]:
            msg = (
                f"The '{diode_info.position_option}' position not supported for "
                f"multiple diodes per switch layouts, use '{PositionOption.RELATIVE}' "
                f"or '{PositionOption.PRESET}' position option"
            )
            raise RuntimeError(msg)

        # it is important to get template connection
        # and relative positions before moving any elements
        template_connection = self._get_template_connection(
            key_info.annotation_format, diode_info
        )
        diode_infos = self._prepare_diode_infos(key_matrix, diode_info)
        for element_info in additional_elements:
            self._update_element_position(key_info, element_info)

        # stage 2 - place elements
        if layout_path:
            with open(layout_path, "r") as f:
                layout = json.load(f)
            logger.info(f"User layout: {layout}")
            self.place_switches(get_keyboard(layout), key_matrix, key_info.position)

        logger.info(f"Diode info: {diode_infos}")
        if diode_info.position_option != PositionOption.UNCHANGED:
            self.place_diodes(diode_infos, key_matrix)

        if additional_elements:
            self.place_switch_elements(additional_elements, key_matrix)

        # stage 3 - route elements
        if route_switches_with_diodes:
            self.route_switches_with_diodes(key_matrix, template_connection)

        if route_rows_and_columns:
            self.route_rows_and_columns()

        if route_switches_with_diodes or route_rows_and_columns:
            self.remove_dangling_tracks()
