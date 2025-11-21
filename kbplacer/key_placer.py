# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import copy
import itertools
import logging
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import (
    Any,
    Dict,
    FrozenSet,
    Iterable,
    Iterator,
    List,
    Optional,
    Set,
    Tuple,
    Union,
    cast,
)

import pcbnew

from .board_modifier import (
    KICAD_VERSION,
    BoardModifier,
    calculate_distance_matrix,
    get_closest_pads_on_same_net,
    get_common_nets,
    get_distance,
    get_footprint,
    get_optional_footprint,
    get_orientation,
    get_pads_by_net,
    get_position,
    get_side,
    position_in_rotated_coordinates,
    prim_mst,
    reset_rotation,
    rotate,
    set_position,
    set_rotation,
    set_side,
)
from .element_position import ElementInfo, ElementPosition, PositionOption
from .kle_serial import (
    Key,
    Keyboard,
    KeyboardTag,
    MatrixAnnotatedKeyboard,
    get_keyboard_from_file,
    layout_classification,
)
from .plugin_error import PluginError

logger = logging.getLogger(__name__)
ANNOTATION_GUIDE_URL = (
    "https://github.com/adamws/kicad-kbplacer/blob/master/docs/annotation_guide.md"
)


class KeyMatrix:
    SUPPORTED_ROW_NAMES = ["ROW{}", "R{}"]
    SUPPORTED_COLUMN_NAMES = ["COLUMN{}", "COL{}", "C{}"]

    def __init__(self, board: pcbnew.BOARD, key_format: str, diode_format: str) -> None:
        self.key_format = key_format
        self.diode_format = diode_format

        self._row_format = ""
        self._column_format = ""

        self._switches: Dict[str, pcbnew.FOOTPRINT] = {}
        self._switches_references_by_net: Dict[FrozenSet[str], List[str]] = defaultdict(
            list
        )
        self._diodes_by_switch: Dict[str, List[pcbnew.FOOTPRINT]] = defaultdict(list)

        diodes: List[pcbnew.FOOTPRINT] = []

        switches_nets: Dict[str, Set[str]] = defaultdict(set)
        all_switches_nets: Set[str] = set()
        diodes_nets_by_reference: Dict[str, Set[str]] = defaultdict(set)
        diodes_unique_nets: Dict[str, Set[str]] = {}

        self.key_pattern = re.compile(key_format.format("(.*)"))
        self.diode_pattern = re.compile(diode_format.format("(.*)"))

        def _get_nets(f: pcbnew.FOOTPRINT) -> List[str]:
            return [p.GetNetname() for p in f.Pads() if p.GetNetname() != ""]

        for f in board.GetFootprints():
            reference = f.GetReference()
            if re.match(self.key_pattern, reference):
                self._switches[reference] = f
                nets = _get_nets(f)
                switches_nets[reference].update(nets)
                all_switches_nets.update(nets)
            elif re.match(self.diode_pattern, reference):
                diodes.append(f)
                diodes_nets_by_reference[reference].update(_get_nets(f))

        # reduce diode_nets to contain only diode-unique nets
        # (i.e. not common with any switch)
        for k, v in diodes_nets_by_reference.items():
            diodes_unique_nets[k] = v.difference(all_switches_nets)

        # each switch can have 0 or more diodes
        for f in diodes:
            reference = f.GetReference()
            for switch_reference, key in self._switches.items():
                diodes_nets = diodes_nets_by_reference[reference]
                switch_nets = [p.GetNetname() for p in key.Pads()]
                if common_nets := list(diodes_nets.intersection(switch_nets)):
                    self._diodes_by_switch[switch_reference].append(f)
                    # remove common switch-diode net and add diode-unique net instead,
                    # this way we should get key-matrix nets:
                    for net in common_nets:
                        switches_nets[switch_reference].discard(net)
                    switches_nets[switch_reference].update(
                        diodes_unique_nets[reference]
                    )

        for k, v in switches_nets.items():
            if len(list(v)) == 2:
                self._switches_references_by_net[frozenset(v)].append(k)
            else:
                logger.warning(
                    "Unexpected switch net position detected, "
                    "each switch should have two unique nets unambiguously defining "
                    "position in key matrix, switch-by-matrix association can't be used"
                )
                self._switches_references_by_net = {}
                break
        logger.debug(f"Switches by nets: {self._switches_references_by_net}")
        self._diodes_references_by_switch = {
            k: [f.GetReference() for f in v] for k, v in self._diodes_by_switch.items()
        }
        logger.debug(f"Diodes by switch: {self._diodes_references_by_switch}")

    def first_switch_reference(self) -> str:
        return min(self._switches)

    def number_of_switches(self) -> int:
        return len(self._switches)

    def switch_by_reference(self, reference: str) -> pcbnew.FOOTPRINT:
        return self._switches[reference]

    def switch_by_format_value(self, value: Any) -> pcbnew.FOOTPRINT:
        return self._switches[self.key_format.format(value)]

    def switches_by_reference(self) -> Iterable[Tuple[str, pcbnew.FOOTPRINT]]:
        return self._switches.items()

    def switches_by_reference_ordered(self) -> Iterable[Tuple[str, pcbnew.FOOTPRINT]]:
        def _tryint(s: str) -> Union[str, int]:
            try:
                return int(s)
            except ValueError:
                return s

        def _alphanum_keys(item: Tuple[str, pcbnew.FOOTPRINT]) -> List[Union[str, int]]:
            return [_tryint(c) for c in re.split("([0-9]+)", item[0])]

        return sorted(self._switches.items(), key=_alphanum_keys)

    def is_matrix_ok(self) -> bool:
        return len(self._switches_references_by_net) != 0

    def is_likely_direct_pin(self) -> bool:
        # assume that matrix netlist is direct-pin if:
        # 1) none of the switch has diode connected to it
        # 2) all of the switches are connected to GND on the one side
        no_diodes = all(
            len(lst) == 0 for lst in self._diodes_references_by_switch.values()
        )
        all_use_gnd = all(
            any(net in key for net in ["GND", "Gnd", "gnd"])
            for key in self._switches_references_by_net.keys()
        )
        return no_diodes and all_use_gnd

    def __guess_format(self, guesses: List[str]) -> str:
        for guess in guesses:
            pattern = re.compile(guess.format("(\\d)+"))
            for net in list(self.matrix_nets()):
                if re.match(pattern, net):
                    return guess
        # out of luck, getting switches by row,column annotation won't work
        return ""

    @property
    def row_format(self) -> str:
        if not self._row_format:
            self._row_format = self.__guess_format(KeyMatrix.SUPPORTED_ROW_NAMES)
        return self._row_format

    @property
    def column_format(self) -> str:
        if not self._column_format:
            self._column_format = self.__guess_format(KeyMatrix.SUPPORTED_COLUMN_NAMES)
        return self._column_format

    def switches_references_by_coordinates(self, row: int, column: int) -> List[str]:
        return self.switches_references_by_netnames(
            self.row_format.format(row), self.column_format.format(column)
        )

    def switches_references_by_netnames(
        self, row_net: str, column_net: str
    ) -> List[str]:
        nets = (row_net, column_net)
        return self._switches_references_by_net[frozenset(nets)]

    def switches_references_by_netname(self, netname: str) -> List[str]:
        result = []
        for nets, switches in self._switches_references_by_net.items():
            if netname in nets:
                result.extend(switches)
        return result

    def diodes_by_switch_reference(self, reference: str) -> List[pcbnew.FOOTPRINT]:
        return self._diodes_by_switch[reference]

    def any_switch_with_multiple_diodes(self) -> bool:
        return any(len(d) > 1 for d in self._diodes_by_switch.values())

    def matrix_nets(self) -> Set[str]:
        return set().union(*self._switches_references_by_net)

    def matrix_rows(self) -> Set[str]:
        pattern = re.compile(self.row_format.format("(\\d)+"))
        return set(filter(lambda net: re.match(pattern, net), self.matrix_nets()))

    def matrix_columns(self) -> Set[str]:
        pattern = re.compile(self.column_format.format("(\\d)+"))
        return set(filter(lambda net: re.match(pattern, net), self.matrix_nets()))


class KeyboardSwitchIterator:
    EXPLICIT_ANNOTATION_LABEL = 10

    def __init__(
        self,
        keyboard: Keyboard,
        key_matrix: KeyMatrix,
        start_index: int = 1,
    ) -> None:
        self._keyboard = keyboard
        self._key_matrix = key_matrix
        self.explicit_annotations = self.__check_explicit_annotations(keyboard)
        self._keys = iter(self._keyboard.keys)
        self._current_key = start_index

    def __check_explicit_annotations(self, keyboard: Keyboard) -> bool:
        number_of_explicit_annotations = sum(
            str(k.get_label(self.EXPLICIT_ANNOTATION_LABEL)).isdigit()
            for k in keyboard.keys
        )
        return number_of_explicit_annotations == len(keyboard.keys)

    def __iter__(self):
        return self

    def __get_footprint(self, key: Key) -> pcbnew.FOOTPRINT:
        if self.explicit_annotations:
            label = key.labels[self.EXPLICIT_ANNOTATION_LABEL]
            try:
                sw = self._key_matrix.switch_by_format_value(label)
            except KeyError as e:
                msg = (
                    "Provided keyboard layout uses explicit annotations "
                    f"but could not find switch {e}, aborting."
                )
                raise PluginError(msg)
        else:
            try:
                sw = self._key_matrix.switch_by_format_value(self._current_key)
            except KeyError as e:
                msg = (
                    f"Could not find switch {e}, aborting.\n"
                    f"Provided keyboard layout requires {len(self._keyboard.keys)} "
                    f"keys, found {self._key_matrix.number_of_switches()} "
                    f"footprints with '{self._key_matrix.key_format}' annotation."
                )
                raise PluginError(msg)
            self._current_key += 1
        return sw

    def __next__(self):
        key = next(self._keys)
        if key:
            if key.decal:
                return self.__next__()
            return key, self.__get_footprint(key)
        else:
            raise StopIteration


class MatrixAnnotatedKeyboardSwitchIterator:
    def __init__(
        self,
        keyboard: MatrixAnnotatedKeyboard,
        key_matrix: KeyMatrix,
    ) -> None:
        self._keyboard = keyboard
        self._key_matrix = key_matrix
        self._keys = self._keyboard.key_iterator(ignore_alternative=False)
        self._seen: List[Tuple[str, str]] = []

    def __iter__(self):
        return self

    def __get_footprint(self, key: Key) -> Optional[pcbnew.FOOTPRINT]:
        matrix_coordinates = MatrixAnnotatedKeyboard.get_matrix_position(key)
        layout_option = self._seen.count(matrix_coordinates)

        if all(c.isdigit() for c in matrix_coordinates):
            switches = self._key_matrix.switches_references_by_coordinates(
                *map(int, matrix_coordinates)
            )
            net_names_inferred = True
        else:
            # supporting via-like annotation where net names are explicitly
            # stated in layout file
            switches = self._key_matrix.switches_references_by_netnames(
                *matrix_coordinates
            )
            net_names_inferred = False
        switches = sorted(switches)
        logger.debug(f"Got {switches} for {matrix_coordinates} position")
        if len(switches) == 0:
            msg = (
                f"Could not find switches connected to {matrix_coordinates} matrix position "
                "which is used in provided layout.\n"
                "Either required footprint is missing or it can't be found due to unexpected "
                "net names.\n"
            )
            if net_names_inferred:
                names = KeyMatrix.SUPPORTED_ROW_NAMES + KeyMatrix.SUPPORTED_COLUMN_NAMES
                msg += (
                    "When using via-annotated layouts it must be possible to associate "
                    "footprints with following net names:\n" + ", ".join(names)
                )
            raise PluginError(msg)

        # assume that alternative keys have same annotation with
        # some sort of suffix so after sorting
        # the option index would get us correct footprint
        try:
            # due to layout collapsing the choices might be missing,
            # instead of using choice value use number of already seen switches
            switch = switches[layout_option]
            fp = self._key_matrix.switch_by_reference(switch)
            self._seen.append(matrix_coordinates)
            return fp
        except Exception:
            logger.warning(
                "Could not find {} layout footprint".format(
                    "default" if layout_option == 0 else "alternative"
                )
            )
            return None

    def __next__(self):
        key = next(self._keys)
        if key:
            if key.decal:
                return self.__next__()
            if not (footprint := self.__get_footprint(key)):
                return self.__next__()
            return key, footprint
        else:
            raise StopIteration


def get_key_iterator(
    keyboard: Keyboard,
    key_matrix: KeyMatrix,
    start_index: int = 1,
) -> Iterator:
    if isinstance(keyboard, MatrixAnnotatedKeyboard):
        if not key_matrix.is_matrix_ok():
            msg = (
                "Detected layout file with via-annotated matrix positions "
                "while not all footprints on PCB can be unambiguously associated "
                "with row/column position.\n"
                "Either net names are unrecognized or netlist is invalid.\n"
                "Fix netlist problems or use layout file which uses 'explicit annotation'.\n"
                f"For details see {ANNOTATION_GUIDE_URL}"
            )
            raise PluginError(msg)
        if key_matrix.is_likely_direct_pin():
            msg = (
                "Detected layout file with via-annotated matrix positions "
                "while key connections appear to be direct-pin (no matrix with diodes found).\n"
                "This means that footprints on PCB can't be reliably matched to layout.\n"
                "Please use layout file which uses 'explicit annotation'.\n"
                f"For details see {ANNOTATION_GUIDE_URL}"
            )
            raise PluginError(msg)
        _iter = MatrixAnnotatedKeyboardSwitchIterator(keyboard, key_matrix)
    else:
        _iter = KeyboardSwitchIterator(keyboard, key_matrix, start_index)
    return iter(_iter)


class KeyPlacer(BoardModifier):
    def __init__(
        self,
        board: pcbnew.BOARD,
        key_distance: Tuple[float, float] = (19.05, 19.05),
        start_index: int = 1,
    ) -> None:
        super().__init__(board)

        self.__key_distance_x = cast(int, pcbnew.FromMM(key_distance[0]))
        self.__key_distance_y = cast(int, pcbnew.FromMM(key_distance[1]))

        logger.debug(
            f"Set key 1U distance: {self.__key_distance_x}/{self.__key_distance_y}"
        )
        # starting index for footprint numbering (allows using offsets other than 1)
        self._start_index = start_index

    def apply_switch_connection_template(
        self,
        switch: pcbnew.FOOTPRINT,
        angle: float,
        template_connection: List[pcbnew.PCB_TRACK],
    ) -> None:
        """
        :param switch: Switch footprint to be routed.
        :param angle: Rotation angle (in degrees) of switch footprint
                      (diode rotation is assumed to be the same)
        :param template_connection: List of template elements (tracks and vias) for
                                    routing switch and diode pads. Normalised to
                                    switch position coordinate. Templates
                                    items must not have netcodes assigned.
        """
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
            if KICAD_VERSION < (7, 0, 0):
                new_track.Move(pcbnew.wxPoint(switch_position.x, switch_position.y))
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

    def route_switch_with_diode(
        self,
        switch: pcbnew.FOOTPRINT,
        diodes: List[pcbnew.FOOTPRINT],
    ) -> None:
        """Performs routing between switch and diode elements.
        It uses two closest (to each other) pads of the same net.

        :param switch: Switch footprint to be routed.
        :param diodes: Diodes footprints to be routed.
        """
        for diode in diodes:
            logger.info(f"Routing {switch.GetReference()} with {diode.GetReference()}")
            if result := get_closest_pads_on_same_net(switch, diode):
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
            x,
            y,
            rot2 - rot1,
            get_side(element2),
        )

    def remove_dangling_tracks(self) -> None:
        logger.info("Removing dangling tracks")
        connectivity = self.get_connectivity()

        any_removed = False

        def _is_dangling(track: pcbnew.PCB_TRACK) -> bool:
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
        set_position(switch_copy, pcbnew.VECTOR2I(0, 0))

        origin = get_position(switch)
        diode_copies = []
        for d in diodes:
            diode_copy = pcbnew.Cast_to_FOOTPRINT(d.Duplicate())
            if angle := get_orientation(switch):
                rotate(diode_copy, origin, angle)
            set_position(
                diode_copy,
                get_position(diode_copy) - origin,
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
        self, key_format: str, diode_format: str, destination_path: str, route: bool
    ) -> List[pcbnew.PCB_TRACK]:
        """Returns list of tracks (including vias) connecting first element
        with reference `key_format` to itself or any other element
        and optionally save it to new `pcbnew` template file.
        The coordinates of returned elements are normalized to center of `key_format`
        element. If `key_format` element is rotated, resulting coordinates are rotated
        back so the template is always in natural (0) orientation.
        """
        switch = get_footprint(self.board, key_format.format(self._start_index))

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
            if KICAD_VERSION < (7, 0, 0):
                item_copy.Move(pcbnew.wxPoint(-origin.x, -origin.y))
            else:
                item_copy.Move(pcbnew.VECTOR2I(-origin.x, -origin.y))

            if route:
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

    def _calculate_reference_coordinate(
        self,
        keyboard: Keyboard,
        key_matrix: KeyMatrix,
    ) -> pcbnew.VECTOR2I:
        """Calculates value of offset vector to be applied to key coordinates
        in order to align first key center with defined x/y grid
        """

        def _offset(
            grid: Union[int, float],
            coordinate: Union[int, float],
            size: Union[int, float],
        ) -> int:
            if not grid:
                return 0
            pos = (grid * coordinate) + (grid * size // 2)
            quotient = pos // grid
            # add to avoid placing next to drawing sheet borders (it just looks better):
            margin = 2
            return int(grid * (quotient + margin) - pos)

        offset_x = 0
        offset_y = 0
        key_iterator: Iterator = get_key_iterator(keyboard, key_matrix, self._start_index)
        first_key, _ = next(key_iterator)
        if first_key:
            offset_x = _offset(self.__key_distance_x, first_key.x, first_key.width)
            offset_y = _offset(self.__key_distance_y, first_key.y, first_key.height)
        return pcbnew.VECTOR2I(offset_x, offset_y)

    def place_switches(
        self,
        keyboard: Keyboard,
        key_matrix: KeyMatrix,
        key_position: Optional[ElementPosition],
    ) -> None:
        offset = self._calculate_reference_coordinate(keyboard, key_matrix)
        logger.debug(f"Layout offset: {offset}")
        key_iterator: Iterator = get_key_iterator(keyboard, key_matrix, self._start_index)

        if (
            isinstance(key_iterator, KeyboardSwitchIterator)
            and not key_iterator.explicit_annotations
        ):
            layout_tags = layout_classification(keyboard)
            if (
                KeyboardTag.COLUMN_STAGGERED in layout_tags
                or KeyboardTag.OTHER in layout_tags
            ):
                msg = (
                    "Layout of this kind with missing key matrix annotations may "
                    "produce unexpected footprint order. "
                    f"For details see: {ANNOTATION_GUIDE_URL}"
                )
                logger.warning(msg)

        for key, switch_footprint in key_iterator:
            reset_rotation(switch_footprint)
            if key_position:
                set_side(switch_footprint, key_position.side)
                set_rotation(switch_footprint, key_position.orientation)

            position = (
                pcbnew.VECTOR2I(
                    int(self.__key_distance_x * (key.x + key.width / 2)),
                    int(self.__key_distance_y * (key.y + key.height / 2)),
                )
                + offset
            )
            set_position(switch_footprint, position)

            angle = key.rotation_angle
            if angle != 0:
                rotation_reference = (
                    pcbnew.VECTOR2I(
                        int(self.__key_distance_x * key.rotation_x),
                        int(self.__key_distance_y * key.rotation_y),
                    )
                    + offset
                )
                rotate(switch_footprint, rotation_reference, angle)

    def place_element(
        self,
        footprint: pcbnew.FOOTPRINT,
        element_position: ElementPosition,
        reference_position: pcbnew.VECTOR2I,
        reference_orientation: float,
    ) -> None:
        reset_rotation(footprint)
        set_side(footprint, element_position.side)
        set_rotation(footprint, element_position.orientation)

        offset = pcbnew.VECTOR2I_MM(element_position.x, element_position.y)
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
            # one diode can be associated with more than one switch,
            # for example for via-annotated alternative keys or when using
            # SOT-23 package or similar, keep track of placed diodes to avoid
            # placing one diode twice.
            placed_diodes: List[pcbnew.FOOTPRINT] = []
            for (
                reference,
                switch_footprint,
            ) in key_matrix.switches_by_reference_ordered():
                diodes = key_matrix.diodes_by_switch_reference(reference)
                switch_position = get_position(switch_footprint)
                switch_orientation = get_orientation(switch_footprint)
                for diode, info in zip(diodes, diode_infos):
                    if info.position and diode not in placed_diodes:
                        self.place_element(
                            diode,
                            info.position,
                            switch_position,
                            switch_orientation,
                        )
                        placed_diodes.append(diode)

    def optimize_diodes_orientation(
        self,
        key_matrix: KeyMatrix,
    ) -> None:
        for (
            reference,
            switch,
        ) in key_matrix.switches_by_reference_ordered():
            diodes = key_matrix.diodes_by_switch_reference(reference)
            logger.debug(f"Optimizing orientation of {switch.GetReference()} diodes")
            for diode in diodes:
                if pads := get_closest_pads_on_same_net(diode, switch):
                    distance1 = get_distance(*pads)
                    position = get_position(diode)
                    rotate(diode, position, 180)
                    distance2 = get_distance(*pads)
                    diff = abs(distance1 - distance2)
                    # if first was shorter or approximately the same (less than 0.01mm)
                    # then go back to initial orientation
                    if distance1 < distance2 or diff < 10000:
                        rotate(diode, position, 180)
                    else:
                        logger.debug(
                            f"Rotated {diode.GetReference()} to minimize distance"
                        )
                else:
                    logger.error(
                        "Could not find pads with the same net, "
                        "diode optimization skipped"
                    )

    def place_switch_elements(
        self,
        elements: List[ElementInfo],
        key_matrix: KeyMatrix,
    ) -> None:
        for reference, switch_footprint in key_matrix.switches_by_reference():
            logger.debug(f"Placing additional elements for {reference}")
            switch_position = get_position(switch_footprint)
            switch_orientation = get_orientation(switch_footprint)
            match = re.match(key_matrix.key_pattern, reference)
            # ommit reference prefix in order to properly match additional element
            # i.e SW1 -> LED1, SW20_1 -> ST20_1
            reference_value = match.group(1) if match else ""
            for element_info in elements:
                footprint = get_optional_footprint(
                    self.board,
                    element_info.annotation_format.format(reference_value),
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
        if template_connection:
            for _, switch_footprint in key_matrix.switches_by_reference():
                angle = -1 * switch_footprint.GetOrientationDegrees()
                self.apply_switch_connection_template(
                    switch_footprint, angle, template_connection
                )
            # when done, delete all template items
            for item in template_connection:
                self.board.RemoveNative(item)
        else:
            for reference, switch_footprint in key_matrix.switches_by_reference():
                diodes = key_matrix.diodes_by_switch_reference(reference)
                self.route_switch_with_diode(switch_footprint, diodes)

    def route_rows_and_columns(self, key_matrix: KeyMatrix) -> None:
        pads = get_pads_by_net(self.board)

        matrix_net_names = key_matrix.matrix_nets()
        matrix_pads = {net: pads[net] for net in matrix_net_names}
        for net, pads in matrix_pads.items():
            logger.debug(f"Routing {net} pads")
            distances = calculate_distance_matrix(cast(List[pcbnew.BOARD_ITEM], pads))
            result = prim_mst(distances)
            for i, j in result:
                p1 = pads[i]
                p2 = pads[j]
                if p1.GetParentAsString() != p2.GetParentAsString():
                    self.route(p1, p2)

    def load_template(self, template_path: str) -> pcbnew.BOARD:
        if KICAD_VERSION >= (8, 0, 0):
            return pcbnew.PCB_IO_MGR.Load(pcbnew.PCB_IO_MGR.KICAD_SEXP, template_path)  # type: ignore
        return pcbnew.IO_MGR.Load(pcbnew.IO_MGR.KICAD_SEXP, template_path)  # type: ignore

    def _normalize_template_path(self, template_path: str) -> str:
        if not template_path:
            msg = "Template path can't be empty"
            raise PluginError(msg)
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
            element1 = get_footprint(source, key_info.annotation_format.format(self._start_index))
            element2 = get_footprint(source, element.annotation_format.format(self._start_index))
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
            number_of_template_switches = template_matrix.number_of_switches()
            if (
                diode_info.position_option == PositionOption.PRESET
                and number_of_template_switches != 1
            ):
                msg = (
                    f"Template file '{diode_info.template_path}' "
                    "must have exactly one switch. "
                    f"Found {number_of_template_switches} switches using "
                    f"'{key_matrix.key_format}' annotation format."
                )
                raise PluginError(msg)
            first_switch = template_matrix.first_switch_reference()
            switch = template_matrix.switch_by_reference(first_switch)
            diodes = template_matrix.diodes_by_switch_reference(switch.GetReference())
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
        self, key_format: str, diode_info: ElementInfo, route: bool
    ) -> List[pcbnew.PCB_TRACK]:
        if diode_info.position_option in [
            PositionOption.RELATIVE,
            PositionOption.UNCHANGED,
        ]:
            return self.get_connection_template(
                key_format,
                diode_info.annotation_format,
                diode_info.template_path,
                route,
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
        optimize_diodes_orientation: bool = False,
    ) -> None:
        # stage 1 - prepare
        key_matrix = KeyMatrix(
            self.board, key_info.annotation_format, diode_info.annotation_format
        )
        if (
            key_matrix.any_switch_with_multiple_diodes()
            and diode_info.position_option
            in [
                PositionOption.DEFAULT,
                PositionOption.CUSTOM,
            ]
        ):
            msg = (
                f"The '{diode_info.position_option}' position not supported for "
                f"multiple diodes per switch layouts, use '{PositionOption.RELATIVE}' "
                f"or '{PositionOption.PRESET}' position option.\n"
                f"When using '{diode_info.position_option}' ensure that each switch "
                "has exactly one diode connected to it."
            )
            raise PluginError(msg)

        number_of_switches = key_matrix.number_of_switches()
        if number_of_switches == 0:
            msg = (
                f"No switch footprints found using '{key_info.annotation_format}' "
                "annotation format. Make sure that switches are added to opened "
                "PCB file and theirs annotations match configured value."
            )
            raise PluginError(msg)

        # it is important to get template connection
        # and relative positions before moving any elements
        template_connection = self._get_template_connection(
            key_info.annotation_format, diode_info, route_switches_with_diodes
        )

        diode_infos = self._prepare_diode_infos(key_matrix, diode_info)
        for element_info in additional_elements:
            self._update_element_position(key_info, element_info)

        # stage 2 - place elements
        if layout_path:
            keyboard = get_keyboard_from_file(layout_path)
            if not isinstance(keyboard, MatrixAnnotatedKeyboard):
                # if not MatrixAnnotatedKeyboard already,
                # check if it is possible to convert
                try:
                    keyboard = MatrixAnnotatedKeyboard(keyboard.meta, keyboard.keys)
                    logger.info(
                        "Detected layout convertible to matrix annotated keyboard"
                    )
                except Exception:
                    pass
            if isinstance(keyboard, MatrixAnnotatedKeyboard):
                # can be called only once:
                keyboard.collapse()
            self.place_switches(keyboard, key_matrix, key_info.position)

        logger.info(f"Diode info: {diode_infos}")
        if diode_info.position_option != PositionOption.UNCHANGED:
            self.place_diodes(diode_infos, key_matrix)
            if optimize_diodes_orientation:
                self.optimize_diodes_orientation(key_matrix)

        if additional_elements:
            self.place_switch_elements(additional_elements, key_matrix)

        # stage 3 - route elements
        if route_switches_with_diodes:
            self.route_switches_with_diodes(key_matrix, template_connection)

        if route_rows_and_columns:
            self.route_rows_and_columns(key_matrix)

        if route_switches_with_diodes or route_rows_and_columns:
            self.remove_dangling_tracks()
