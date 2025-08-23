# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import traceback

import wx

from .dialog_helper import MessageDialog
from .plugin_error import PluginError


class ErrorDialog(MessageDialog):
    def __init__(self, parent, e: Exception) -> None:
        super(ErrorDialog, self).__init__(parent, "kbplacer error")
        box = wx.BoxSizer(wx.VERTICAL)

        if type(e) == PluginError:
            message = e.message
            add_traceback = False
        else:
            message = getattr(e, "message", f"{e.__class__.__name__}: {e}")
            add_traceback = True

        error_header = wx.TextCtrl(
            self, value=message, style=wx.TE_READONLY | wx.NO_BORDER | wx.TE_MULTILINE
        )
        self.adjust_size_to_text(error_header, message)

        error_icon = wx.ArtProvider.GetBitmap(
            wx.ART_ERROR, wx.ART_MESSAGE_BOX, wx.Size(32, 32)
        )
        icon = wx.StaticBitmap(self, bitmap=error_icon)

        icon_and_message_sizer = wx.BoxSizer(wx.HORIZONTAL)
        icon_and_message_sizer.Add(icon, 0, wx.ALL, 10)
        icon_and_message_sizer.Add(
            error_header, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 10
        )
        box.Add(icon_and_message_sizer, 0, wx.EXPAND | wx.ALL, 5)

        if add_traceback:
            traceback_str = traceback.format_exc()
            details_text = wx.TextCtrl(
                self,
                value=traceback_str,
                style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL,
            )
            self.adjust_size_to_text(details_text, traceback_str)
            box.Add(details_text, 0, wx.EXPAND | wx.ALL, 5)

        buttons = self.CreateButtonSizer(wx.OK)
        box.Add(buttons, 0, wx.EXPAND | wx.ALL, 5)

        self.SetSizerAndFit(box)


if __name__ == "__main__":
    from .dialog_helper import show_with_test_support

    try:
        _ = 1 / 0
    except Exception as e:
        show_with_test_support(ErrorDialog, None, e)
    print("exit ok")
