# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later


class PluginError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(self.message)
