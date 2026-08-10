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
from .builders_commons import matrix_net_name, uses_stabilizer
from .footprint_loader import (
    FootprintIdentifier,
    StabilizerFootprintLoader,
    SwitchFootprintLoader,
    load_footprint,
)
from .kle_serial import (
    Key,
    MatrixAnnotatedKeyboard,
    get_annotated_keyboard_from_path_or_url,
)

logger = logging.getLogger(__name__)

# SK6812MINI-E-compatible pad numbering (fixed by the part's pinout, not
# probed - unlike switch/encoder, which must support two different pad-naming
# conventions). Matches the schematic symbol's pin numbers (see
# `led_schematic_builder.py`'s `SK6812MINI-E_1_1`: pin "1"=VSS, "2"=DIN,
# "3"=VDD, "4"=DOUT).
LED_GND_PAD, LED_DIN_PAD, LED_VCC_PAD, LED_DOUT_PAD = "1", "2", "3", "4"
# Capacitor is unpolarized; pad-to-net convention is arbitrary but fixed.
CAP_VCC_PAD, CAP_GND_PAD = "1", "2"


def _led_chain_link_net_name(prev_ref: int, next_ref: int) -> str:
    """Net name KiCad's netlist/DRC would auto-assign to the anonymous
    (unlabeled) wire between one LED's DOUT and the next LED's DIN.

    KiCad names an anonymous net after the lexicographically (string, not
    numeric) smallest "{ref}-{pin}" among the connected pins - e.g. comparing
    "LED10-DIN" vs "LED9-DOUT" as strings, "LED10..." sorts first because
    '1' < '9' at the first differing character, regardless of which LED is
    numerically earlier in the chain. This is also why the pre-existing
    switch-diode net is always named "Net-(D{n}-A)" (`"D" < "SW"`
    alphabetically for every `n`) - same rule, not a diode-specific one.
    """
    candidates = (f"LED{prev_ref}-DOUT", f"LED{next_ref}-DIN")
    return f"Net-({min(candidates)})"


class BoardBuilder:
    def __init__(
        self,
        pcb_file_path: Union[str, os.PathLike],
        *,
        switch_footprint: str,
        diode_footprint: str,
        stabilizer_footprint: Optional[str] = None,
        encoder_footprint: Optional[str] = None,
        led_footprint: Optional[str] = None,
        cap_footprint: Optional[str] = None,
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
        self.encoder_footprint = (
            FootprintIdentifier.from_str(encoder_footprint)
            if encoder_footprint
            else None
        )
        self.led_footprint = (
            FootprintIdentifier.from_str(led_footprint) if led_footprint else None
        )
        self.cap_footprint = (
            FootprintIdentifier.from_str(cap_footprint) if cap_footprint else None
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
            if fp is None:
                # No suitable stabilizer footprint for this key size; skip it.
                return None
            fp.SetReference(ref)
            fp.SetValue("SW_stab")
            return self._add_footprint(fp)
        return None

    def _add_encoder_footprint(self, ref: str) -> pcbnew.FOOTPRINT:
        fp = load_footprint(
            self.encoder_footprint.library_path,
            self.encoder_footprint.footprint_name,
        )
        fp.SetReference(ref)
        fp.SetValue("RotaryEncoder_Switch")
        return self._add_footprint(fp)

    def _add_led_footprint(self, ref: str) -> pcbnew.FOOTPRINT:
        fp = load_footprint(
            self.led_footprint.library_path,
            self.led_footprint.footprint_name,
        )
        for pad in (LED_GND_PAD, LED_DIN_PAD, LED_VCC_PAD, LED_DOUT_PAD):
            if not fp.FindPadByNumber(pad):
                msg = (
                    f"LED footprint {self.led_footprint.footprint_name} is missing "
                    f"pad '{pad}'; only SK6812MINI-E-pinout-compatible footprints "
                    "(pads 1=GND, 2=DIN, 3=VCC, 4=DOUT) are supported"
                )
                raise RuntimeError(msg)
        fp.SetReference(ref)
        fp.SetValue("SK6812MINI-E")
        return self._add_footprint(fp)

    def _add_capacitor_footprint(self, ref: str) -> pcbnew.FOOTPRINT:
        fp = load_footprint(
            self.cap_footprint.library_path,
            self.cap_footprint.footprint_name,
        )
        for pad in (CAP_VCC_PAD, CAP_GND_PAD):
            if not fp.FindPadByNumber(pad):
                msg = (
                    f"Capacitor footprint {self.cap_footprint.footprint_name} is "
                    f"missing pad '{pad}'; a generic 2-pad passive footprint "
                    "is required"
                )
                raise RuntimeError(msg)
        fp.SetReference(ref)
        fp.SetValue("C")
        return self._add_footprint(fp)

    @staticmethod
    def _matrix_pad_numbers(fp: pcbnew.FOOTPRINT) -> Tuple[str, str]:
        """Return the ordered (column-side, diode-side) matrix pad numbers
        of a switch or encoder footprint.

        Plain switches use pads "1"/"2", encoders use "S1"/"S2". The two roles
        (default vs alternative) can be either type, so pad names must be probed
        instead of assumed. Encoder naming is checked first because an encoder
        may also expose numerically named rotary pads.
        """
        if fp.FindPadByNumber("S1") and fp.FindPadByNumber("S2"):
            return ("S1", "S2")
        if fp.FindPadByNumber("1") and fp.FindPadByNumber("2"):
            return ("1", "2")
        msg = (
            f"Cannot determine matrix pads of footprint {fp.GetReference()}; "
            "expected pads '1'/'2' (switch) or 'S1'/'S2' (encoder)"
        )
        raise RuntimeError(msg)

    def _add_led_chain_elements(
        self,
        current_ref: int,
        start_index: int,
        total_led_positions: int,
        *,
        skip_led_decoupling: bool = False,
    ) -> None:
        """Create the LED (+ decoupling capacitor, unless `skip_led_decoupling`
        is set) for one physical key position and wire them into the shared
        power rails and DIN/DOUT daisy chain.

        Called once per unique physical position (never for alternate-layout
        keys sharing that position - one LED/cap per physical slot, matching
        the schematic's `_unique_matrix_positions` dedup, which is a stricter
        rule than stabilizers currently follow).
        """
        led = self._add_led_footprint(f"LED{current_ref}")

        is_first = current_ref == start_index
        is_last = current_ref == start_index + total_led_positions - 1
        din_net_name = (
            "LEDIN"
            if is_first
            else _led_chain_link_net_name(current_ref - 1, current_ref)
        )
        dout_net_name = (
            "LEDOUT"
            if is_last
            else _led_chain_link_net_name(current_ref, current_ref + 1)
        )

        vcc_net = self._add_or_get_net("VCC")
        gnd_net = self._add_or_get_net("GND")
        din_net = self._add_or_get_net(din_net_name)
        dout_net = self._add_or_get_net(dout_net_name)

        led.FindPadByNumber(LED_GND_PAD).SetNet(gnd_net)
        led.FindPadByNumber(LED_DIN_PAD).SetNet(din_net)
        led.FindPadByNumber(LED_VCC_PAD).SetNet(vcc_net)
        led.FindPadByNumber(LED_DOUT_PAD).SetNet(dout_net)

        if not skip_led_decoupling:
            cap = self._add_capacitor_footprint(f"C{current_ref}")
            cap.FindPadByNumber(CAP_VCC_PAD).SetNet(vcc_net)
            cap.FindPadByNumber(CAP_GND_PAD).SetNet(gnd_net)

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
        start_index: int = 1,
        create_leds: bool = False,
        skip_led_decoupling: bool = False,
    ) -> pcbnew.BOARD:
        # A negative start index is the "unset" sentinel used by `ElementInfo`
        # (see element_position.py); mirror the key placer and fall back to 1.
        if start_index < 0:
            logger.warning(f"Invalid switch start index: {start_index}, defaults to 1")
            start_index = 1

        if create_leds and not self.led_footprint:
            msg = "LED footprint must be configured when create_leds is requested"
            raise RuntimeError(msg)

        if create_leds and not skip_led_decoupling and not self.cap_footprint:
            msg = (
                "Capacitor footprint must be configured when create_leds is "
                "requested, unless skip_led_decoupling is set"
            )
            raise RuntimeError(msg)

        if isinstance(keyboard, str) or isinstance(keyboard, os.PathLike):
            _keyboard = get_annotated_keyboard_from_path_or_url(keyboard)
        else:
            _keyboard: MatrixAnnotatedKeyboard = keyboard

        _keyboard.collapse()

        keys = _keyboard.keys_in_matrix_order()
        positions = [MatrixAnnotatedKeyboard.get_matrix_position(k) for k in keys]

        # First pass: collect all unique net names
        net_names = set()
        current_ref = start_index
        position_tracker: Dict[Tuple[str, str], bool] = {}
        for k, position in zip(keys, positions):
            row, column = position
            if position not in position_tracker:
                column_name = matrix_net_name("COL", column)
                row_name = matrix_net_name("ROW", row)
                net_names.add(column_name)
                net_names.add(row_name)
                net_names.add(f"Net-(D{current_ref}-A)")
                current_ref += 1
                position_tracker[position] = True

        total_led_positions = current_ref - start_index

        if create_leds and total_led_positions > 0:
            net_names.add("VCC")
            net_names.add("GND")
            net_names.add("LEDIN")
            net_names.add("LEDOUT")
            for ref in range(start_index, start_index + total_led_positions - 1):
                net_names.add(_led_chain_link_net_name(ref, ref + 1))

        # Create all nets in alphabetical order
        # This ensures they get auto-assigned netcodes in alphabetical order
        # which would match behaviour of netlist generated from schematic
        for net_name in sorted(net_names):
            self._add_or_get_net(net_name)

        # Second pass: create footprints and assign nets
        current_ref = start_index
        progress: Dict[Tuple[str, str], List[pcbnew.FOOTPRINT]] = defaultdict(list)
        for k, position in zip(keys, positions):
            row, column = position
            if position not in progress:
                if k.sm == "rot_ec11":
                    if not self.encoder_footprint:
                        msg = "Encoder footprint not configured but layout contains encoder keys"
                        raise RuntimeError(msg)
                    encoder = self._add_encoder_footprint(f"SW{current_ref}")
                    diode = self._add_diode_footprint(f"D{current_ref}")

                    encoder_s1 = encoder.FindPadByNumber("S1")
                    encoder_s2 = encoder.FindPadByNumber("S2")
                    encoder_s1.SetPinFunction("S1")
                    encoder_s2.SetPinFunction("S2")
                    diode_pad1 = diode.FindPadByNumber("1")
                    diode_pad2 = diode.FindPadByNumber("2")
                    diode_pad1.SetPinFunction("K")
                    diode_pad2.SetPinFunction("A")

                    column_name = matrix_net_name("COL", column)
                    net = self._add_or_get_net(column_name)
                    encoder_s1.SetNet(net)

                    row_name = matrix_net_name("ROW", row)
                    net = self._add_or_get_net(row_name)
                    diode_pad1.SetNet(net)

                    net = self._add_or_get_net(f"Net-(D{current_ref}-A)")
                    encoder_s2.SetNet(net)
                    diode_pad2.SetNet(net)

                    if create_leds:
                        self._add_led_chain_elements(
                            current_ref,
                            start_index,
                            total_led_positions,
                            skip_led_decoupling=skip_led_decoupling,
                        )

                    current_ref += 1
                    progress[position].append(encoder)
                else:
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

                    column_name = matrix_net_name("COL", column)
                    net = self._add_or_get_net(column_name)
                    switch_pad1.SetNet(net)

                    row_name = matrix_net_name("ROW", row)
                    net = self._add_or_get_net(row_name)
                    diode_pad1.SetNet(net)

                    net = self._add_or_get_net(f"Net-(D{current_ref}-A)")
                    switch_pad2.SetNet(net)
                    diode_pad2.SetNet(net)

                    if create_leds:
                        self._add_led_chain_elements(
                            current_ref,
                            start_index,
                            total_led_positions,
                            skip_led_decoupling=skip_led_decoupling,
                        )

                    current_ref += 1
                    progress[position].append(switch)
            else:
                # alternative layout key, do not need to create nets
                # or add diode for it. Load the appropriate footprint for this key
                # and copy net assignments from the default footprint at this position.
                footprints = progress[position]
                default_fp = footprints[0]

                suffix = ascii_lowercase[len(footprints) - 1]
                reference = default_fp.GetReference() + suffix
                if k.sm == "rot_ec11":
                    if not self.encoder_footprint:
                        msg = "Encoder footprint not configured but layout contains encoder keys"
                        raise RuntimeError(msg)
                    fp = self._add_encoder_footprint(reference)
                else:
                    fp = self._add_switch_footprint(reference, key=k)
                    if add_stabilizers and uses_stabilizer(k):
                        stabilizer_reference = reference.replace("SW", "ST")
                        self._add_stabilizer_footprint(stabilizer_reference, key=k)

                # Copy matrix nets from the default footprint at this position.
                # Either footprint may be a switch ("1"/"2") or an encoder
                # ("S1"/"S2"), so probe the pad names on both sides instead of
                # assuming the default is a plain switch.
                default_pads = self._matrix_pad_numbers(default_fp)
                new_pads = self._matrix_pad_numbers(fp)
                for default_number, new_number in zip(default_pads, new_pads):
                    default_pad = default_fp.FindPadByNumber(default_number)
                    new_pad = fp.FindPadByNumber(new_number)
                    if default_pad and new_pad:
                        new_pad.SetNet(default_pad.GetNet())
                        new_pad.SetPinFunction(new_number)

                progress[position].append(fp)

        return self.board
