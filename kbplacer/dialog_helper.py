# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import os
from typing import Optional

import wx


class MessageDialog(wx.Dialog):
    def __init__(self, parent: Optional[wx.Window], title: str = "") -> None:
        super(MessageDialog, self).__init__(
            parent, -1, title, style=wx.DEFAULT_DIALOG_STYLE | wx.STAY_ON_TOP
        )
        self.parent = parent

    def adjust_size_to_text(self, text_ctrl: wx.TextCtrl, text: str) -> None:
        dc = wx.ClientDC(self)
        max_line_width = 0

        for line in text.split("\n"):
            width, _ = dc.GetTextExtent(line)
            max_line_width = max(max_line_width, width)

        width_for_text = max_line_width + 50

        if self.parent is None:
            max_width = wx.GetDisplaySize().GetWidth() - 100
        else:
            max_width = self.parent.GetSize().GetWidth() - 100

        final_width = min(width_for_text, max_width)

        text_ctrl.SetMinSize(wx.Size(final_width, -1))
        self.SetMinSize(wx.Size(final_width + 20, -1))


def show_with_test_support(class_or_func, *args, **kwargs) -> wx.Dialog:
    """This exist only for testing purposes"""
    import threading

    app = wx.App()
    dlg = class_or_func(*args, **kwargs)

    if "PYTEST_CURRENT_TEST" in os.environ:
        # use stdin for gracefully closing GUI when running
        # from pytest. This is required when measuring
        # coverage and process kill would cause measurement to be lost
        def listen_for_exit():
            input("Press any key to exit: ")
            dlg.Close()
            wx.Exit()

        input_thread = threading.Thread(target=listen_for_exit)
        input_thread.start()

        dlg.Show()
        app.MainLoop()
    else:
        dlg.ShowModal()

    return dlg
