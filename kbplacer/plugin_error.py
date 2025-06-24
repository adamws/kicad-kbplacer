# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later
import logging

logger = logging.getLogger(__name__)


class PluginError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        logger.error(self.message.replace("\n", " "))
        super().__init__(self.message)
