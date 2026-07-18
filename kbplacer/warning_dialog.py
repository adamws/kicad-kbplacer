# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from typing import List, Optional

import wx

from .dialog_helper import MessageDialog


class WarningDialog(MessageDialog):
    def __init__(self, parent, warnings: List[str]) -> None:
        super(WarningDialog, self).__init__(parent, "kbplacer warning")
        warnings_count = len(warnings)
        if warnings_count == 0:
            msg = "WarningDialog must have at least one warning defined"
            raise RuntimeError(msg)
        box = wx.BoxSizer(wx.VERTICAL)

        header_text = f"Encountered {warnings_count} warnings"
        warnings_header = wx.TextCtrl(
            self, value=header_text, style=wx.TE_READONLY | wx.NO_BORDER
        )
        warnings_header.SetBackgroundColour(self.GetBackgroundColour())
        self.adjust_size_to_text(warnings_header, header_text)

        warning_icon = wx.ArtProvider.GetBitmap(
            wx.ART_WARNING, wx.ART_MESSAGE_BOX, wx.Size(32, 32)
        )
        icon = wx.StaticBitmap(self, bitmap=warning_icon)

        icon_and_message_sizer = wx.BoxSizer(wx.HORIZONTAL)
        icon_and_message_sizer.Add(icon, 0, wx.ALL, 10)
        icon_and_message_sizer.Add(
            warnings_header, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 10
        )
        box.Add(icon_and_message_sizer, 0, wx.EXPAND | wx.ALL, 5)

        warnings_str = "\n".join(warnings)
        details_text = wx.TextCtrl(
            self,
            value=warnings_str,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL,
        )
        self.adjust_size_to_text(details_text, warnings_str)
        box.Add(details_text, 0, wx.EXPAND | wx.ALL, 5)

        buttons = self.CreateButtonSizer(wx.OK)
        box.Add(buttons, 0, wx.EXPAND | wx.ALL, 5)

        self.SetSizerAndFit(box)


def get_warnings_from_log(
    parent: wx.Window, log_file: str, *, prefix: str = "WARNING:"
) -> Optional[wx.Dialog]:
    # keeping python 3.8 compatibility which had no `removeprefix`:
    def _remove_prefix(text, prefix):
        if text.startswith(prefix):
            return text[len(prefix) :]
        return text

    with open(log_file, "r") as f:
        warnings = [
            _remove_prefix(l, prefix).strip() for l in f if l.startswith(prefix)
        ]
    if warnings:
        return WarningDialog(parent, warnings)
    return None


if __name__ == "__main__":
    import logging
    import os

    from .dialog_helper import show_with_test_support

    tmp_log = "warning_dialog_temp.log"
    logging.basicConfig(
        level=logging.DEBUG,
        filename=tmp_log,
        filemode="w",
        format="%(levelname)s: %(filename)s:%(lineno)d: %(message)s",
    )

    logger = logging.getLogger(__name__)
    logger.warning("This is warning number 1")
    logger.debug("This is debug which should be ignored")
    logger.warning("And this is warning number 2")

    show_with_test_support(get_warnings_from_log, None, tmp_log)
    os.remove(tmp_log)
    print("exit ok")
