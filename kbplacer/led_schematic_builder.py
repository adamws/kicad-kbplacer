# SPDX-FileCopyrightText: 2026 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import logging
import os
from typing import List, Tuple, Union

from .board_modifier import KICAD_VERSION
from .kle_serial import MatrixAnnotatedKeyboard, get_annotated_keyboard_from_file
from .schematic_builder import can_create_schematic

try:
    from skip import Schematic
except ImportError:
    pass
else:
    # kicad-skip logs a warning every time it builds a named-element lookup
    # for a symbol whose pins have no name (Device:C and power:GND/VCC both
    # use blank pin names) - harmless, but noisy enough to flood stderr
    # across dozens of LEDs/capacitors.
    logging.getLogger("skip").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)

# ISO 216 landscape page sizes in mm: (name, width, height).
PAPER_SIZES = [
    ("A4", 297.0, 210.0),
    ("A3", 420.0, 297.0),
    ("A2", 594.0, 420.0),
    ("A1", 841.0, 594.0),
    ("A0", 1189.0, 841.0),
]

LED_PITCH_X = 24.13
ROW_PITCH_Y = 29.845
FIRST_LED_X = 46.355
FIRST_LED_Y = 60.325

# Pin connection length (2.54) + a short stub (1.27) out to each LED's own
# power symbol; symmetric for VDD (top) and VSS (bottom).
LED_POWER_OFFSET = 7.62 + 1.27

# DOUT pin -> rightward waypoint used both for the inter-row return wire and
# for the final chain-output global label.
CHAIN_LABEL_STUB_X = 8.255
# Global input label -> first LED's DIN pin.
INPUT_LABEL_STUB_X = 4.445
# Extra clearance the inter-row return wire keeps to the left of a row's
# first DIN pin, so it does not cut through the LED symbol body.
RETURN_MARGIN_X = 6.985

CAP_PITCH_X = 9.525
CAP_FIRST_X = FIRST_LED_X
# Clearance between the last LED row and the capacitor bank.
CAP_ROW_MARGIN_Y = 24.13
# Vertical spacing between wrapped capacitor-bank rows.
CAP_ROW_PITCH_Y = 15.24
# Capacitor pin connection length (3.81) + bus stub (1.27) + symbol stub
# (1.27), symmetric top/bottom.
CAP_POWER_OFFSET = 3.81 + 1.27 + 1.27
CAP_BUS_OFFSET = 3.81 + 1.27
# Two dedicated columns, left of the capacitor bank, carrying the single
# shared VCC/GND net across wrapped capacitor rows.
CAP_VCC_SPINE_X = CAP_FIRST_X - 6.35
CAP_GND_SPINE_X = CAP_FIRST_X - 12.7

BOTTOM_MARGIN_Y = 20.0


TEMPLATE = """\
(kicad_sch
    (version 20260306)
    (generator "eeschema")
    (generator_version "10.0")
    (uuid "{own_uuid}")
    (paper "{page_size}")
    (lib_symbols
        (symbol "Device:C"
            (pin_numbers
                (hide yes)
            )
            (pin_names
                (offset 0.254)
            )
            (exclude_from_sim no)
            (in_bom yes)
            (on_board yes)
            (in_pos_files yes)
            (duplicate_pin_numbers_are_jumpers no)
            (property "Reference" "C"
                (at 0.635 2.54 0)
                (show_name no)
                (do_not_autoplace no)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                    (justify left)
                )
            )
            (property "Value" "C"
                (at 0.635 -2.54 0)
                (show_name no)
                (do_not_autoplace no)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                    (justify left)
                )
            )
            (property "Footprint" ""
                (at 0.9652 -3.81 0)
                (show_name no)
                (do_not_autoplace no)
                (hide yes)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                )
            )
            (property "Datasheet" ""
                (at 0 0 0)
                (show_name no)
                (do_not_autoplace no)
                (hide yes)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                )
            )
            (property "Description" "Unpolarized capacitor"
                (at 0 0 0)
                (show_name no)
                (do_not_autoplace no)
                (hide yes)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                )
            )
            (property "ki_keywords" "cap capacitor"
                (at 0 0 0)
                (show_name no)
                (do_not_autoplace no)
                (hide yes)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                )
            )
            (property "ki_fp_filters" "C_*"
                (at 0 0 0)
                (show_name no)
                (do_not_autoplace no)
                (hide yes)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                )
            )
            (symbol "C_0_1"
                (polyline
                    (pts
                        (xy -2.032 0.762) (xy 2.032 0.762)
                    )
                    (stroke
                        (width 0.508)
                        (type default)
                    )
                    (fill
                        (type none)
                    )
                )
                (polyline
                    (pts
                        (xy -2.032 -0.762) (xy 2.032 -0.762)
                    )
                    (stroke
                        (width 0.508)
                        (type default)
                    )
                    (fill
                        (type none)
                    )
                )
            )
            (symbol "C_1_1"
                (pin passive line
                    (at 0 3.81 270)
                    (length 2.794)
                    (name ""
                        (effects
                            (font
                                (size 1.27 1.27)
                            )
                        )
                    )
                    (number "1"
                        (effects
                            (font
                                (size 1.27 1.27)
                            )
                        )
                    )
                )
                (pin passive line
                    (at 0 -3.81 90)
                    (length 2.794)
                    (name ""
                        (effects
                            (font
                                (size 1.27 1.27)
                            )
                        )
                    )
                    (number "2"
                        (effects
                            (font
                                (size 1.27 1.27)
                            )
                        )
                    )
                )
            )
            (embedded_fonts no)
        )
        (symbol "LED:SK6812MINI-E"
            (pin_names
                (offset 0.254)
            )
            (exclude_from_sim no)
            (in_bom yes)
            (on_board yes)
            (in_pos_files yes)
            (duplicate_pin_numbers_are_jumpers no)
            (property "Reference" "D"
                (at 5.08 5.715 0)
                (show_name no)
                (do_not_autoplace no)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                    (justify right bottom)
                )
            )
            (property "Value" "SK6812MINI-E"
                (at 1.27 -5.715 0)
                (show_name no)
                (do_not_autoplace no)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                    (justify left top)
                )
            )
            (property "Footprint" "LED_SMD:LED_SK6812MINI-E_3.2x2.8mm_P1.5mm_ReverseMount"
                (at 1.27 -7.62 0)
                (show_name no)
                (do_not_autoplace no)
                (hide yes)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                    (justify left top)
                )
            )
            (property "Datasheet" "https://www.lcsc.com/datasheet/C5149201.pdf"
                (at 2.54 -9.525 0)
                (show_name no)
                (do_not_autoplace no)
                (hide yes)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                    (justify left top)
                )
            )
            (property "Description" "RGB LED with integrated controller"
                (at 0 0 0)
                (show_name no)
                (do_not_autoplace no)
                (hide yes)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                )
            )
            (property "ki_keywords" "RGB LED NeoPixel addressable"
                (at 0 0 0)
                (show_name no)
                (do_not_autoplace no)
                (hide yes)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                )
            )
            (property "ki_fp_filters" "LED?SK6812MINI?E?3.2x2.8mm?P1.5mm*"
                (at 0 0 0)
                (show_name no)
                (do_not_autoplace no)
                (hide yes)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                )
            )
            (symbol "SK6812MINI-E_0_0"
                (text "RGB"
                    (at 2.286 -4.191 0)
                    (effects
                        (font
                            (size 0.762 0.762)
                        )
                    )
                )
            )
            (symbol "SK6812MINI-E_0_1"
                (polyline
                    (pts
                        (xy 1.27 -2.54) (xy 1.778 -2.54)
                    )
                    (stroke
                        (width 0)
                        (type default)
                    )
                    (fill
                        (type none)
                    )
                )
                (polyline
                    (pts
                        (xy 1.27 -3.556) (xy 1.778 -3.556)
                    )
                    (stroke
                        (width 0)
                        (type default)
                    )
                    (fill
                        (type none)
                    )
                )
                (polyline
                    (pts
                        (xy 2.286 -1.524) (xy 1.27 -2.54) (xy 1.27 -2.032)
                    )
                    (stroke
                        (width 0)
                        (type default)
                    )
                    (fill
                        (type none)
                    )
                )
                (polyline
                    (pts
                        (xy 2.286 -2.54) (xy 1.27 -3.556) (xy 1.27 -3.048)
                    )
                    (stroke
                        (width 0)
                        (type default)
                    )
                    (fill
                        (type none)
                    )
                )
                (polyline
                    (pts
                        (xy 3.683 -1.016) (xy 3.683 -3.556) (xy 3.683 -4.064)
                    )
                    (stroke
                        (width 0)
                        (type default)
                    )
                    (fill
                        (type none)
                    )
                )
                (polyline
                    (pts
                        (xy 4.699 -1.524) (xy 2.667 -1.524) (xy 3.683 -3.556) (xy 4.699 -1.524)
                    )
                    (stroke
                        (width 0)
                        (type default)
                    )
                    (fill
                        (type none)
                    )
                )
                (polyline
                    (pts
                        (xy 4.699 -3.556) (xy 2.667 -3.556)
                    )
                    (stroke
                        (width 0)
                        (type default)
                    )
                    (fill
                        (type none)
                    )
                )
                (rectangle
                    (start 5.08 5.08)
                    (end -5.08 -5.08)
                    (stroke
                        (width 0.254)
                        (type default)
                    )
                    (fill
                        (type background)
                    )
                )
            )
            (symbol "SK6812MINI-E_1_1"
                (pin power_in line
                    (at 0 -7.62 90)
                    (length 2.54)
                    (name "VSS"
                        (effects
                            (font
                                (size 1.27 1.27)
                            )
                        )
                    )
                    (number "1"
                        (effects
                            (font
                                (size 1.27 1.27)
                            )
                        )
                    )
                )
                (pin input line
                    (at -7.62 0 0)
                    (length 2.54)
                    (name "DIN"
                        (effects
                            (font
                                (size 1.27 1.27)
                            )
                        )
                    )
                    (number "2"
                        (effects
                            (font
                                (size 1.27 1.27)
                            )
                        )
                    )
                )
                (pin power_in line
                    (at 0 7.62 270)
                    (length 2.54)
                    (name "VDD"
                        (effects
                            (font
                                (size 1.27 1.27)
                            )
                        )
                    )
                    (number "3"
                        (effects
                            (font
                                (size 1.27 1.27)
                            )
                        )
                    )
                )
                (pin output line
                    (at 7.62 0 180)
                    (length 2.54)
                    (name "DOUT"
                        (effects
                            (font
                                (size 1.27 1.27)
                            )
                        )
                    )
                    (number "4"
                        (effects
                            (font
                                (size 1.27 1.27)
                            )
                        )
                    )
                )
            )
            (embedded_fonts no)
        )
        (symbol "power:GND"
            (power global)
            (pin_numbers
                (hide yes)
            )
            (pin_names
                (offset 0)
                (hide yes)
            )
            (exclude_from_sim no)
            (in_bom yes)
            (on_board yes)
            (in_pos_files yes)
            (duplicate_pin_numbers_are_jumpers no)
            (property "Reference" "#PWR"
                (at 0 -6.35 0)
                (show_name no)
                (do_not_autoplace no)
                (hide yes)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                )
            )
            (property "Value" "GND"
                (at 0 -3.81 0)
                (show_name no)
                (do_not_autoplace no)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                )
            )
            (property "Footprint" ""
                (at 0 0 0)
                (show_name no)
                (do_not_autoplace no)
                (hide yes)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                )
            )
            (property "Datasheet" ""
                (at 0 0 0)
                (show_name no)
                (do_not_autoplace no)
                (hide yes)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                )
            )
            (property "Description" "Power symbol creates a global label with name \\"GND\\" , ground"
                (at 0 0 0)
                (show_name no)
                (do_not_autoplace no)
                (hide yes)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                )
            )
            (property "ki_keywords" "global power"
                (at 0 0 0)
                (show_name no)
                (do_not_autoplace no)
                (hide yes)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                )
            )
            (symbol "GND_0_1"
                (polyline
                    (pts
                        (xy 0 0) (xy 0 -1.27) (xy 1.27 -1.27) (xy 0 -2.54) (xy -1.27 -1.27) (xy 0 -1.27)
                    )
                    (stroke
                        (width 0)
                        (type default)
                    )
                    (fill
                        (type none)
                    )
                )
            )
            (symbol "GND_1_1"
                (pin power_in line
                    (at 0 0 270)
                    (length 0)
                    (name ""
                        (effects
                            (font
                                (size 1.27 1.27)
                            )
                        )
                    )
                    (number "1"
                        (effects
                            (font
                                (size 1.27 1.27)
                            )
                        )
                    )
                )
            )
            (embedded_fonts no)
        )
        (symbol "power:VCC"
            (power global)
            (pin_numbers
                (hide yes)
            )
            (pin_names
                (offset 0)
                (hide yes)
            )
            (exclude_from_sim no)
            (in_bom yes)
            (on_board yes)
            (in_pos_files yes)
            (duplicate_pin_numbers_are_jumpers no)
            (property "Reference" "#PWR"
                (at 0 -3.81 0)
                (show_name no)
                (do_not_autoplace no)
                (hide yes)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                )
            )
            (property "Value" "VCC"
                (at 0 3.556 0)
                (show_name no)
                (do_not_autoplace no)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                )
            )
            (property "Footprint" ""
                (at 0 0 0)
                (show_name no)
                (do_not_autoplace no)
                (hide yes)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                )
            )
            (property "Datasheet" ""
                (at 0 0 0)
                (show_name no)
                (do_not_autoplace no)
                (hide yes)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                )
            )
            (property "Description" "Power symbol creates a global label with name \\"VCC\\""
                (at 0 0 0)
                (show_name no)
                (do_not_autoplace no)
                (hide yes)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                )
            )
            (property "ki_keywords" "global power"
                (at 0 0 0)
                (show_name no)
                (do_not_autoplace no)
                (hide yes)
                (effects
                    (font
                        (size 1.27 1.27)
                    )
                )
            )
            (symbol "VCC_0_1"
                (polyline
                    (pts
                        (xy -0.762 1.27) (xy 0 2.54)
                    )
                    (stroke
                        (width 0)
                        (type default)
                    )
                    (fill
                        (type none)
                    )
                )
                (polyline
                    (pts
                        (xy 0 2.54) (xy 0.762 1.27)
                    )
                    (stroke
                        (width 0)
                        (type default)
                    )
                    (fill
                        (type none)
                    )
                )
                (polyline
                    (pts
                        (xy 0 0) (xy 0 2.54)
                    )
                    (stroke
                        (width 0)
                        (type default)
                    )
                    (fill
                        (type none)
                    )
                )
            )
            (symbol "VCC_1_1"
                (pin power_in line
                    (at 0 0 90)
                    (length 0)
                    (name ""
                        (effects
                            (font
                                (size 1.27 1.27)
                            )
                        )
                    )
                    (number "1"
                        (effects
                            (font
                                (size 1.27 1.27)
                            )
                        )
                    )
                )
            )
            (embedded_fonts no)
        )
    )
    (symbol
        (lib_id "LED:SK6812MINI-E")
        (at 0 0 0)
        (unit 1)
        (body_style 1)
        (exclude_from_sim no)
        (in_bom yes)
        (on_board yes)
        (in_pos_files yes)
        (dnp no)
        (uuid "5e5f1cf7-5172-4f72-b83c-5dbd3da3dcd1")
        (property "Reference" "LED0"
            (at 5.588 -2.54 0)
            (show_name no)
            (do_not_autoplace no)
            (effects
                (font
                    (size 1.27 1.27)
                )
                (justify left)
            )
        )
        (property "Value" "SK6812MINI-E"
            (at 8.89 3.175 0)
            (show_name no)
            (do_not_autoplace no)
            (hide yes)
            (effects
                (font
                    (size 1.27 1.27)
                )
                (justify left)
            )
        )
        (property "Footprint" "LED_SMD:LED_SK6812MINI-E_3.2x2.8mm_P1.5mm_ReverseMount"
            (at 0 0 0)
            (show_name no)
            (do_not_autoplace no)
            (hide yes)
            (effects
                (font
                    (size 1.27 1.27)
                )
            )
        )
        (property "Datasheet" "https://www.lcsc.com/datasheet/C5149201.pdf"
            (at 0 0 0)
            (show_name no)
            (do_not_autoplace no)
            (hide yes)
            (effects
                (font
                    (size 1.27 1.27)
                )
            )
        )
        (property "Description" "RGB LED with integrated controller"
            (at 0 0 0)
            (show_name no)
            (do_not_autoplace no)
            (hide yes)
            (effects
                (font
                    (size 1.27 1.27)
                )
            )
        )
        (pin "1"
            (uuid "8ca07ba2-fb03-4ab6-a2c0-9b247abf569d")
        )
        (pin "2"
            (uuid "74eb21b7-9565-414d-ac8a-65c999628418")
        )
        (pin "3"
            (uuid "bc25eb53-33e4-4310-83fd-a452cce2fd25")
        )
        (pin "4"
            (uuid "d15401d6-2b74-4f3c-aef6-27c09edcdaa8")
        )
        (instances
            (project "{project_name}"
                (path "/{own_uuid}"
                    (reference "LED0")
                    (unit 1)
                )
            )
        )
    )
    (symbol
        (lib_id "Device:C")
        (at 0 20 0)
        (unit 1)
        (body_style 1)
        (exclude_from_sim no)
        (in_bom yes)
        (on_board yes)
        (in_pos_files yes)
        (dnp no)
        (uuid "21ac7c7a-0244-422b-90ac-e14ae0b8f9f8")
        (property "Reference" "C0"
            (at 3.175 18.8 0)
            (show_name no)
            (do_not_autoplace no)
            (effects
                (font
                    (size 1.27 1.27)
                )
                (justify left)
            )
        )
        (property "Value" "C"
            (at 3.175 21.34 0)
            (show_name no)
            (do_not_autoplace no)
            (effects
                (font
                    (size 1.27 1.27)
                )
                (justify left)
            )
        )
        (property "Footprint" ""
            (at 0 25 0)
            (show_name no)
            (do_not_autoplace no)
            (hide yes)
            (effects
                (font
                    (size 1.27 1.27)
                )
            )
        )
        (property "Datasheet" ""
            (at 0 20 0)
            (show_name no)
            (do_not_autoplace no)
            (hide yes)
            (effects
                (font
                    (size 1.27 1.27)
                )
            )
        )
        (property "Description" "Unpolarized capacitor"
            (at 0 20 0)
            (show_name no)
            (do_not_autoplace no)
            (hide yes)
            (effects
                (font
                    (size 1.27 1.27)
                )
            )
        )
        (pin "1"
            (uuid "1d46334a-9a14-4aeb-9439-23760e6b9ffc")
        )
        (pin "2"
            (uuid "c86b85e5-27de-4bfd-a7d4-7376936c8058")
        )
        (instances
            (project "{project_name}"
                (path "/{own_uuid}"
                    (reference "C0")
                    (unit 1)
                )
            )
        )
    )
    (symbol
        (lib_id "power:GND")
        (at 20 20 0)
        (unit 1)
        (body_style 1)
        (exclude_from_sim no)
        (in_bom yes)
        (on_board yes)
        (in_pos_files yes)
        (dnp no)
        (uuid "5b3b82c0-ecf1-447c-af2d-b0fde89153ef")
        (property "Reference" "#PWRG0"
            (at 20 26.35 0)
            (show_name no)
            (do_not_autoplace no)
            (hide yes)
            (effects
                (font
                    (size 1.27 1.27)
                )
            )
        )
        (property "Value" "GND"
            (at 20 24.445 0)
            (show_name no)
            (do_not_autoplace no)
            (effects
                (font
                    (size 1.27 1.27)
                )
            )
        )
        (property "Footprint" ""
            (at 20 20 0)
            (show_name no)
            (do_not_autoplace no)
            (hide yes)
            (effects
                (font
                    (size 1.27 1.27)
                )
            )
        )
        (property "Datasheet" ""
            (at 20 20 0)
            (show_name no)
            (do_not_autoplace no)
            (hide yes)
            (effects
                (font
                    (size 1.27 1.27)
                )
            )
        )
        (property "Description" "Power symbol creates a global label with name \\"GND\\" , ground"
            (at 20 20 0)
            (show_name no)
            (do_not_autoplace no)
            (hide yes)
            (effects
                (font
                    (size 1.27 1.27)
                )
            )
        )
        (pin "1"
            (uuid "682d709c-a34b-4c75-9976-6cb70ef3f4a8")
        )
        (instances
            (project "{project_name}"
                (path "/{own_uuid}"
                    (reference "#PWRG0")
                    (unit 1)
                )
            )
        )
    )
    (symbol
        (lib_id "power:VCC")
        (at 20 40 0)
        (unit 1)
        (body_style 1)
        (exclude_from_sim no)
        (in_bom yes)
        (on_board yes)
        (in_pos_files yes)
        (dnp no)
        (uuid "74da7e5f-09c7-48f3-9dc0-66210a80fb94")
        (property "Reference" "#PWRV0"
            (at 20 44.19 0)
            (show_name no)
            (do_not_autoplace no)
            (hide yes)
            (effects
                (font
                    (size 1.27 1.27)
                )
            )
        )
        (property "Value" "VCC"
            (at 20 35.44 0)
            (show_name no)
            (do_not_autoplace no)
            (effects
                (font
                    (size 1.27 1.27)
                )
            )
        )
        (property "Footprint" ""
            (at 20 40 0)
            (show_name no)
            (do_not_autoplace no)
            (hide yes)
            (effects
                (font
                    (size 1.27 1.27)
                )
            )
        )
        (property "Datasheet" ""
            (at 20 40 0)
            (show_name no)
            (do_not_autoplace no)
            (hide yes)
            (effects
                (font
                    (size 1.27 1.27)
                )
            )
        )
        (property "Description" "Power symbol creates a global label with name \\"VCC\\""
            (at 20 40 0)
            (show_name no)
            (do_not_autoplace no)
            (hide yes)
            (effects
                (font
                    (size 1.27 1.27)
                )
            )
        )
        (pin "1"
            (uuid "9f686ca6-1a35-4d5b-8c53-03c633e63d6e")
        )
        (instances
            (project "{project_name}"
                (path "/{own_uuid}"
                    (reference "#PWRV0")
                    (unit 1)
                )
            )
        )
    )
    (sheet_instances
        (path "/"
            (page "{sheet_page}")
        )
    )
    (embedded_fonts no)
)
"""


def can_create_led_chain_schematic() -> bool:
    return can_create_schematic()


def _per_row(width: float, first_x: float, pitch_x: float) -> int:
    usable_span = width - 2 * first_x
    return max(int(usable_span // pitch_x) + 1, 1)


def _plan_layout(led_count: int) -> Tuple[str, int, int, int, int]:
    """Pick the smallest paper size that fits `led_count` LEDs plus the
    capacitor bank, and how many LEDs/capacitors go in each row before
    wrapping.

    Both the LED chain and the capacitor bank are laid out left to right,
    each wrapping to a new row only once *that* row runs out of horizontal
    space on the page (not based on total count) - matching the placement
    density seen in `example_led_chain.kicad_sch`. Capacitors are pitched
    much tighter than LEDs, so the capacitor bank typically wraps into fewer
    rows than the LED chain, but for large layouts it still needs to wrap.
    """
    last_name, last_width, last_height = PAPER_SIZES[-1]
    for name, width, height in PAPER_SIZES:
        led_per_row = _per_row(width, FIRST_LED_X, LED_PITCH_X)
        led_rows = -(-led_count // led_per_row)  # ceil division
        cap_per_row = _per_row(width, CAP_FIRST_X, CAP_PITCH_X)
        cap_rows = -(-led_count // cap_per_row)
        total_height = (
            FIRST_LED_Y
            + (led_rows - 1) * ROW_PITCH_Y
            + LED_POWER_OFFSET
            + CAP_ROW_MARGIN_Y
            + (cap_rows - 1) * CAP_ROW_PITCH_Y
            + 2 * CAP_POWER_OFFSET
            + BOTTOM_MARGIN_Y
        )
        if total_height <= height or name == last_name:
            return name, led_per_row, led_rows, cap_per_row, cap_rows

    # unreachable, `last_name` is always visited by the loop above
    return last_name, 1, led_count, 1, led_count


def _unique_matrix_positions(
    keyboard: MatrixAnnotatedKeyboard,
) -> List[Tuple[str, str]]:
    """One entry per physical key position, in matrix (chain) order.

    Alternative keys (e.g. an encoder sharing a position with a regular key)
    occupy the same physical spot and therefore the same LED, so only the
    first key seen per position is kept.
    """
    seen = set()
    positions = []
    for key in keyboard.keys_in_matrix_order():
        position = MatrixAnnotatedKeyboard.get_matrix_position(key)
        if position not in seen:
            seen.add(position)
            positions.append(position)
    return positions


def create_led_chain_schematic(
    keyboard: Union[str, os.PathLike, MatrixAnnotatedKeyboard],
    output_path,
    *,
    project_name: str,
    own_uuid: str,
    sheet_page: int = 1,
) -> None:
    """Write an LED-chain `.kicad_sch`: one `LED:SK6812MINI-E` per physical
    key (matrix order = chain order, matching the key matrix builder's use of
    `keys_in_matrix_order`), daisy-chained DOUT -> DIN with global labels at
    both ends, individual per-LED VCC/GND, and a decoupling capacitor per LED
    placed in its own row/bank below with a single shared VCC/GND symbol
    pair.
    """
    if not can_create_led_chain_schematic():
        msg = "Requires optional schematic dependencies"
        raise ImportError(msg)
    if KICAD_VERSION < (9, 0, 0):
        msg = "Requires KiCad 9.0 or higher"
        raise RuntimeError(msg)

    if isinstance(keyboard, (str, os.PathLike)):
        _keyboard = get_annotated_keyboard_from_file(keyboard)
    else:
        _keyboard = keyboard

    _keyboard.collapse()
    positions = _unique_matrix_positions(_keyboard)
    led_count = len(positions)
    if led_count == 0:
        msg = "Layout has no keys to generate an LED chain for"
        raise ValueError(msg)

    page_size, led_per_row, led_rows, cap_per_row, cap_rows = _plan_layout(led_count)
    logger.debug(
        f"LED chain: {led_count} LEDs, {led_per_row} per row, {led_rows} rows; "
        f"{led_count} capacitors, {cap_per_row} per row, {cap_rows} rows; "
        f"page {page_size}"
    )

    with open(output_path, "w") as f:
        f.write(
            TEMPLATE.format(
                page_size=page_size,
                own_uuid=own_uuid,
                project_name=project_name,
                sheet_page=sheet_page,
            )
        )

    sch = Schematic(output_path)
    base_led = sch.symbol.reference_startswith("LED0")[0]
    base_cap = sch.symbol.reference_startswith("C0")[0]
    base_gnd = sch.symbol.reference_startswith("#PWRG0")[0]
    base_vcc = sch.symbol.reference_startswith("#PWRV0")[0]

    pwr_index = 0

    def _new_power(base, x: float, y: float, rotation: int = 0):
        nonlocal pwr_index
        pwr_index += 1
        symbol = base.clone()
        symbol.setAllReferences(f"#PWR{pwr_index}")
        symbol.move(x, y, rotation)
        return symbol

    prev_dout_loc = None

    for index in range(led_count):
        row, col = divmod(index, led_per_row)
        led_x = FIRST_LED_X + col * LED_PITCH_X
        led_y = FIRST_LED_Y + row * ROW_PITCH_Y

        led = base_led.clone()
        led.setAllReferences(f"LED{index + 1}")
        led.move(led_x, led_y)

        vdd_loc = led.pin.VDD.location
        vss_loc = led.pin.VSS.location
        vdd_is_top = vdd_loc.value[1] < vss_loc.value[1]
        top_loc, bottom_loc = (vdd_loc, vss_loc) if vdd_is_top else (vss_loc, vdd_loc)
        din_loc = led.pin.DIN.location
        dout_loc = led.pin.DOUT.location

        own_vcc = _new_power(base_vcc, top_loc.value[0], top_loc.value[1] - 1.27)
        wire = sch.wire.new()
        wire.start_at(top_loc)
        wire.end_at(own_vcc.at)

        own_gnd = _new_power(base_gnd, bottom_loc.value[0], bottom_loc.value[1] + 1.27)
        wire = sch.wire.new()
        wire.start_at(bottom_loc)
        wire.end_at(own_gnd.at)

        if index == 0:
            label_x = din_loc.value[0] - INPUT_LABEL_STUB_X
            input_label = sch.global_label.new()
            input_label.move(label_x, din_loc.value[1], 180)
            input_label.effects.justify.value = "right"
            input_label.value = "LEDIN"
            wire = sch.wire.new()
            wire.start_at(input_label.at)
            wire.end_at(din_loc)
        elif prev_dout_loc is not None and col != 0:
            # same row: straight wire from the previous LED's DOUT
            wire = sch.wire.new()
            wire.start_at(prev_dout_loc)
            wire.end_at(din_loc)
        elif prev_dout_loc is not None:
            # new row: route the return wire from the previous row's last
            # DOUT down/around into this row's first DIN, staying clear of
            # both rows' LED bodies and power symbols.
            right_x = prev_dout_loc.value[0] + CHAIN_LABEL_STUB_X
            mid_y = (prev_dout_loc.value[1] + led_y) / 2
            left_x = din_loc.value[0] - RETURN_MARGIN_X

            waypoints = [
                [right_x, prev_dout_loc.value[1]],
                [right_x, mid_y],
                [left_x, mid_y],
                [left_x, led_y],
            ]
            segment_start = prev_dout_loc
            for waypoint in waypoints:
                wire = sch.wire.new()
                wire.start_at(segment_start)
                wire.end_at(waypoint)
                segment_start = waypoint

            wire = sch.wire.new()
            wire.start_at(segment_start)
            wire.end_at(din_loc)

        if index == led_count - 1:
            label_x = dout_loc.value[0] + CHAIN_LABEL_STUB_X
            output_label = sch.global_label.new()
            output_label.move(label_x, dout_loc.value[1], 0)
            output_label.effects.justify.value = "left"
            output_label.value = "LEDOUT"
            wire = sch.wire.new()
            wire.start_at(dout_loc)
            wire.end_at(output_label.at)

        prev_dout_loc = dout_loc

    # Capacitor bank: one per LED, placed below the chain, wrapping to a new
    # row once a row runs out of horizontal space (same rule as the LED
    # chain above, just with a much tighter pitch). All rows share a single
    # VCC/GND symbol pair, carried across rows by two dedicated "spine"
    # columns to the left of the bank.
    last_led_row_y = FIRST_LED_Y + (led_rows - 1) * ROW_PITCH_Y
    first_cap_row_y = last_led_row_y + LED_POWER_OFFSET + CAP_ROW_MARGIN_Y

    top_bus_ys = []
    bottom_bus_ys = []
    for cap_row in range(cap_rows):
        cap_y = first_cap_row_y + cap_row * CAP_ROW_PITCH_Y
        top_bus_y = cap_y - CAP_BUS_OFFSET
        bottom_bus_y = cap_y + CAP_BUS_OFFSET
        top_bus_ys.append(top_bus_y)
        bottom_bus_ys.append(bottom_bus_y)

        row_start = cap_row * cap_per_row
        row_end = min(row_start + cap_per_row, led_count)
        row_size = row_end - row_start

        for col in range(row_size):
            index = row_start + col
            cap_x = CAP_FIRST_X + col * CAP_PITCH_X
            cap = base_cap.clone()
            cap.setAllReferences(f"C{index + 1}")
            cap.move(cap_x, cap_y)

            pin_a, pin_b = cap.pin[0].location, cap.pin[1].location
            top_loc, bottom_loc = (
                (pin_a, pin_b) if pin_a.value[1] < pin_b.value[1] else (pin_b, pin_a)
            )

            wire = sch.wire.new()
            wire.start_at(top_loc)
            wire.end_at([cap_x, top_bus_y])

            wire = sch.wire.new()
            wire.start_at(bottom_loc)
            wire.end_at([cap_x, bottom_bus_y])

            # A plain corner (this cap's stub meeting the bus turning
            # towards the next one) needs no junction; a T-connection (bus
            # continuing past this point, or - for column 0 - the spine tap
            # branching off) does. The last capacitor in a row is always a
            # plain corner; when a row has a single capacitor, column 0 is
            # also the last one, so it correctly gets no junction either.
            if col != row_size - 1:
                junc = sch.junction.new()
                junc.move(cap_x, top_bus_y)
                junc = sch.junction.new()
                junc.move(cap_x, bottom_bus_y)

        for col in range(row_size - 1):
            cap_x = CAP_FIRST_X + col * CAP_PITCH_X
            next_cap_x = CAP_FIRST_X + (col + 1) * CAP_PITCH_X

            wire = sch.wire.new()
            wire.start_at([cap_x, top_bus_y])
            wire.end_at([next_cap_x, top_bus_y])

            wire = sch.wire.new()
            wire.start_at([cap_x, bottom_bus_y])
            wire.end_at([next_cap_x, bottom_bus_y])

        # Tap this row's bus into the shared VCC/GND spine columns.
        wire = sch.wire.new()
        wire.start_at([CAP_VCC_SPINE_X, top_bus_y])
        wire.end_at([CAP_FIRST_X, top_bus_y])

        wire = sch.wire.new()
        wire.start_at([CAP_GND_SPINE_X, bottom_bus_y])
        wire.end_at([CAP_FIRST_X, bottom_bus_y])

    # Vertical spine wires connecting every row's tap together, plus
    # junctions at interior rows (top and bottom of the spine are plain
    # corners/attachment points, not T-connections).
    for cap_row in range(cap_rows - 1):
        wire = sch.wire.new()
        wire.start_at([CAP_VCC_SPINE_X, top_bus_ys[cap_row]])
        wire.end_at([CAP_VCC_SPINE_X, top_bus_ys[cap_row + 1]])

        wire = sch.wire.new()
        wire.start_at([CAP_GND_SPINE_X, bottom_bus_ys[cap_row]])
        wire.end_at([CAP_GND_SPINE_X, bottom_bus_ys[cap_row + 1]])

        if cap_row != 0:
            junc = sch.junction.new()
            junc.move(CAP_VCC_SPINE_X, top_bus_ys[cap_row])
            junc = sch.junction.new()
            junc.move(CAP_GND_SPINE_X, bottom_bus_ys[cap_row])

    bank_vcc = _new_power(base_vcc, CAP_VCC_SPINE_X, top_bus_ys[0] - 1.27)
    wire = sch.wire.new()
    wire.start_at([CAP_VCC_SPINE_X, top_bus_ys[0]])
    wire.end_at(bank_vcc.at)

    # GND is placed next to VCC (same row, same "pointing away from the
    # bank" rotation) instead of hanging below row 0's bus: that position
    # sits directly on the spine wire's path down to the next wrapped
    # capacitor row, which would overlap the symbol whenever the bank wraps.
    bank_gnd = _new_power(base_gnd, CAP_GND_SPINE_X, top_bus_ys[0] - 1.27, rotation=180)
    # The 180 rotation flips the symbol's own body/pin drawing (so the flag
    # points up, matching VCC), but kicad-skip only translates property text
    # along with the symbol - it doesn't mirror it for the new rotation. Flip
    # the "GND" label to the opposite side so it doesn't land below the
    # symbol as if the flag still pointed down.
    value_offset_y = bank_gnd.property.Value.at.value[1] - bank_gnd.at.value[1]
    bank_gnd.property.Value.move(
        bank_gnd.at.value[0], bank_gnd.at.value[1] - value_offset_y, 0
    )
    wire = sch.wire.new()
    wire.start_at([CAP_GND_SPINE_X, bottom_bus_ys[0]])
    wire.end_at(bank_gnd.at)

    if cap_rows > 1:
        junc = sch.junction.new()
        junc.move(CAP_VCC_SPINE_X, top_bus_ys[0])
        junc = sch.junction.new()
        junc.move(CAP_GND_SPINE_X, bottom_bus_ys[0])

    base_led.delete()
    base_cap.delete()
    base_gnd.delete()
    base_vcc.delete()

    sch.write(output_path)
