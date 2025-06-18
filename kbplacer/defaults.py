# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from .element_position import ElementPosition, Side

DEFAULT_DIODE_POSITION = ElementPosition(5.08, 3.03, 90.0, Side.BACK)
ZERO_POSITION = ElementPosition(0, 0, 0, Side.FRONT)
