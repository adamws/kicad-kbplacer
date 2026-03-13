# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import logging
import os
from collections import defaultdict
from string import ascii_lowercase
from typing import Dict, List, Optional, Tuple, Union

import pcbnew

from .board_modifier import KICAD_VERSION
from .builders_commons import uses_stabilizer
from .footprint_loader import (
    FootprintIdentifier,
    StabilizerFootprintLoader,
    SwitchFootprintLoader,
    load_footprint,
)
from .kle_serial import Key, MatrixAnnotatedKeyboard, get_annotated_keyboard_from_file

logger = logging.getLogger(__name__)


class BoardBuilder:
    def __init__(
        self,
        pcb_file_path: Union[str, os.PathLike],
        *,
        switch_footprint: str,
        diode_footprint: str,
        stabilizer_footprint: Optional[str] = None,
    ) -> None:
        # Switches support variable width with template footprints
        self.switch_footprint = SwitchFootprintLoader(switch_footprint)
        # Diodes are simple - just parse the identifier
        self.diode_footprint = FootprintIdentifier.from_str(diode_footprint)
        self.stabilizer_footprint = (
            StabilizerFootprintLoader(stabilizer_footprint)
            if stabilizer_footprint
            else None
        )

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
        fp = self.switch_footprint.load(key=key)
        fp.SetReference(ref)
        fp.SetValue("SW_Push")
        return self._add_footprint(fp)

    def _add_diode_footprint(self, ref: str) -> pcbnew.FOOTPRINT:
        # Diodes don't need variable width - load directly
        fp = load_footprint(
            self.diode_footprint.library_path,
            self.diode_footprint.footprint_name,
        )
        fp.SetReference(ref)
        fp.SetValue("D")
        return self._add_footprint(fp)

    def _add_stabilizer_footprint(
        self, ref: str, key: Optional[Key] = None
    ) -> Optional[pcbnew.FOOTPRINT]:
        if self.stabilizer_footprint:
            fp = self.stabilizer_footprint.load(key=key)
            fp.SetReference(ref)
            fp.SetValue("SW_stab")
            return self._add_footprint(fp)
        return None

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
        *,
        add_stabilizers: bool = True,
    ) -> pcbnew.BOARD:
        if isinstance(keyboard, str) or isinstance(keyboard, os.PathLike):
            _keyboard = get_annotated_keyboard_from_file(keyboard)
        else:
            _keyboard: MatrixAnnotatedKeyboard = keyboard

        _keyboard.collapse()

        keys = _keyboard.keys_in_matrix_order()
        positions = [MatrixAnnotatedKeyboard.get_matrix_position(k) for k in keys]

        # First pass: collect all unique net names
        net_names = set()
        current_ref = 1
        position_tracker: Dict[Tuple[str, str], bool] = {}
        for k, position in zip(keys, positions):
            row, column = position
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
        for k, position in zip(keys, positions):
            row, column = position
            if position not in progress:
                switch = self._add_switch_footprint(f"SW{current_ref}", key=k)
                diode = self._add_diode_footprint(f"D{current_ref}")

                if add_stabilizers and uses_stabilizer(k):
                    self._add_stabilizer_footprint(f"ST{current_ref}", key=k)

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
                # or add diode for it. Load the appropriate footprint for this key
                # and copy net assignments from the default switch.
                switches = progress[position]
                default_switch = switches[0]

                suffix = ascii_lowercase[len(switches) - 1]
                switch_reference = default_switch.GetReference() + suffix
                switch = self._add_switch_footprint(switch_reference, key=k)
                for pad_number in ("1", "2"):
                    default_pad = default_switch.FindPadByNumber(pad_number)
                    new_pad = switch.FindPadByNumber(pad_number)
                    if default_pad and new_pad:
                        new_pad.SetNet(default_pad.GetNet())
                        new_pad.SetPinFunction(pad_number)

                if add_stabilizers and uses_stabilizer(k):
                    stabilizer_reference = switch_reference.replace("SW", "ST")
                    self._add_stabilizer_footprint(stabilizer_reference, key=k)

                progress[position].append(switch)

        return self.board
