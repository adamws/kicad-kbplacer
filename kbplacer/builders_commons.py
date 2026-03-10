# SPDX-FileCopyrightText: 2026 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from .kle_serial import Key


def uses_stabilizer(key: Key) -> bool:
    # Assume that each key wider/taller or equal than 2U uses stabilizer
    if key.width >= 2 or key.height >= 2:
        return True
    return False
