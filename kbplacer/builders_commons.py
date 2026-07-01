# SPDX-FileCopyrightText: 2026 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from .kle_serial import Key


def uses_stabilizer(key: Key) -> bool:
    # Assume that each key wider/taller or equal than 2U uses stabilizer
    if key.width >= 2 or key.height >= 2:
        return True
    return False


def matrix_net_name(prefix: str, coordinate: str) -> str:
    # Digit-only coordinates are normalized through int() so that leading-zero
    # variants (e.g. "00") collapse onto their canonical net ("0" -> "COL0").
    # This matches the int-based lookup in MatrixAnnotatedKeyboardSwitchIterator
    # and avoids creating phantom nets like COL00 which placement can never
    # resolve. Non-digit coordinates (explicit via-style net names) are kept
    # as-is.
    return f"{prefix}{int(coordinate)}" if coordinate.isdigit() else coordinate
