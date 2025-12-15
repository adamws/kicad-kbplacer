# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import json
import logging
import os
import re
from collections import defaultdict
from string import ascii_lowercase
from typing import Dict, List, Optional, Tuple, Union

import pcbnew

from .board_modifier import KICAD_VERSION
from .footprint_loader import FootprintIdentifier, SwitchFootprintLoader
from .kle_serial import Key, Keyboard, MatrixAnnotatedKeyboard, get_keyboard

logger = logging.getLogger(__name__)


class BoardBuilder:
    def __init__(
        self,
        pcb_file_path: Union[str, os.PathLike],
        *,
        switch_footprint: str,
        diode_footprint: str,
    ) -> None:
        # Switches support variable width with template footprints
        self.switch_footprint = SwitchFootprintLoader(switch_footprint)
        # Diodes are simple - just parse the identifier
        self.diode_footprint = FootprintIdentifier.from_str(diode_footprint)

        # use `NewBoard` over `CreateNewBoard` because it respects netclass
        # settings from .kicad_pro file if it already exist
        self.board = pcbnew.NewBoard(pcb_file_path)
        self.nets: dict[str, pcbnew.NETINFO_ITEM] = {}
        self.net_info = self.board.GetNetInfo()

    def _add_footprint(self, footprint: pcbnew.FOOTPRINT) -> pcbnew.FOOTPRINT:
        logger.info(f"Add {footprint.GetReference()} footprint")
        self.board.Add(footprint)
        return footprint

    def _add_switch_footprint(
        self, ref: str, key: Optional[Key] = None
    ) -> pcbnew.FOOTPRINT:
        f = self.switch_footprint.load(key=key)
        f.SetReference(ref)
        return self._add_footprint(f)

    def _add_diode_footprint(self, ref: str) -> pcbnew.FOOTPRINT:
        # Diodes don't need variable width - load directly
        fp = pcbnew.FootprintLoad(
            self.diode_footprint.library_path,
            self.diode_footprint.footprint_name,
        )
        if fp is None:
            msg = (
                f"Unable to load footprint: "
                f"{self.diode_footprint.library_path}:"
                f"{self.diode_footprint.footprint_name}"
            )
            raise RuntimeError(msg)
        fp.SetReference(ref)
        return self._add_footprint(fp)

    def _add_or_get_net(self, netname: str) -> pcbnew.NETINFO_ITEM:
        """Add new net with netname if it does not exist already
        or return if it does exist

        Note: Net codes are auto-assigned by KiCad when adding nets to the board.
        To control net code ordering, nets must be added in the desired order.
        """
        if netname in self.nets:
            net = self.nets[netname]
        else:
            # Use -1 for netcode - it will be auto-assigned when added to board
            net = pcbnew.NETINFO_ITEM(self.board, netname, -1)
            if KICAD_VERSION < (8, 0, 0):
                self.net_info.AppendNet(net)
            logger.info(f"Add {netname} net")
            self.board.Add(net)
            self.nets[netname] = net
        return net

    def create_board(
        self,
        keyboard: Union[str, os.PathLike, MatrixAnnotatedKeyboard],
    ) -> pcbnew.BOARD:
        if isinstance(keyboard, str) or isinstance(keyboard, os.PathLike):
            with open(keyboard, "r", encoding="utf-8") as f:
                layout = json.load(f)
                tmp: Keyboard = get_keyboard(layout)
                if not isinstance(tmp, MatrixAnnotatedKeyboard):
                    try:
                        _keyboard = MatrixAnnotatedKeyboard(tmp.meta, tmp.keys)
                    except Exception as e:
                        msg = (
                            f"Layout from {keyboard} is not convertible to "
                            "matrix annotated keyboard which is required "
                            "for board create"
                        )
                        raise RuntimeError(msg) from e
                else:
                    _keyboard = tmp
        else:
            _keyboard: MatrixAnnotatedKeyboard = keyboard

        _keyboard.collapse()

        items: List[Tuple[str, str]] = []
        key_map: Dict[Tuple[str, str], List[Key]] = defaultdict(list)
        key_iterator = _keyboard.key_iterator(ignore_alternative=False)

        for key in key_iterator:
            if key.decal:
                continue
            matrix_pos = MatrixAnnotatedKeyboard.get_matrix_position(key)
            items.append(matrix_pos)
            # Store key for later use (for width extraction)
            key_map[matrix_pos].append(key)

        def _sort_matrix(item: Tuple[str, str]) -> Tuple[int, int]:
            row_match = re.search(r"\d+", item[0])
            column_match = re.search(r"\d+", item[1])

            if row_match is None or column_match is None:
                msg = f"No numeric part for row or column found in '{item}'"
                raise ValueError(msg)

            return int(row_match.group()), int(column_match.group())

        # First pass: collect all unique net names
        net_names = set()
        current_ref = 1
        position_tracker: Dict[Tuple[str, str], bool] = {}
        for row, column in sorted(items, key=_sort_matrix):
            position = (row, column)
            if position not in position_tracker:
                column_name = f"COL{column}" if column.isdigit() else column
                row_name = f"ROW{row}" if row.isdigit() else row
                net_names.add(column_name)
                net_names.add(row_name)
                net_names.add(f"Net-(D{current_ref}-A)")
                current_ref += 1
                position_tracker[position] = True

        # Create all nets in alphabetical order
        # This ensures they get auto-assigned netcodes in alphabetical order
        # which would match behaviour of netlist generated from schematic
        for net_name in sorted(net_names):
            self._add_or_get_net(net_name)

        # Second pass: create footprints and assign nets
        current_ref = 1
        progress: Dict[Tuple[str, str], List[pcbnew.FOOTPRINT]] = defaultdict(list)
        for row, column in sorted(items, key=_sort_matrix):
            position = (row, column)
            if position not in progress:
                # Get first key at this position (for width and ISO Enter detection)
                keys_at_position = key_map[position]
                first_key = keys_at_position[0] if keys_at_position else None

                switch = self._add_switch_footprint(f"SW{current_ref}", key=first_key)
                diode = self._add_diode_footprint(f"D{current_ref}")

                switch_pad1 = switch.FindPadByNumber("1")
                switch_pad2 = switch.FindPadByNumber("2")
                switch_pad1.SetPinFunction("1")
                switch_pad2.SetPinFunction("2")
                diode_pad1 = diode.FindPadByNumber("1")
                diode_pad2 = diode.FindPadByNumber("2")
                diode_pad1.SetPinFunction("K")
                diode_pad2.SetPinFunction("A")

                column_name = f"COL{column}" if column.isdigit() else column
                net = self._add_or_get_net(column_name)
                switch_pad1.SetNet(net)

                row_name = f"ROW{row}" if row.isdigit() else row
                net = self._add_or_get_net(row_name)
                diode_pad1.SetNet(net)

                net = self._add_or_get_net(f"Net-(D{current_ref}-A)")
                switch_pad2.SetNet(net)
                diode_pad2.SetNet(net)

                current_ref += 1
                progress[position].append(switch)
            else:
                # this must be alternative layout key, do not need to create nets
                # or add diode for it. Just add duplicate and add suffix to reference
                switches = progress[position]
                default_switch = switches[0]

                suffix = ascii_lowercase[len(switches) - 1]
                switch = pcbnew.Cast_to_FOOTPRINT(default_switch.Duplicate())
                switch.SetReference(default_switch.GetReference() + suffix)
                self._add_footprint(switch)

                progress[position].append(switch)

        return self.board
