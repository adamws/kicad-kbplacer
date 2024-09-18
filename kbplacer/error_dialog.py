import os
import traceback

import wx


class ErrorDialog(wx.Dialog):
    def __init__(self, parent, e: Exception) -> None:
        super(ErrorDialog, self).__init__(
            parent, -1, "kbplacer error", style=wx.DEFAULT_DIALOG_STYLE | wx.STAY_ON_TOP
        )
        self.parent = parent

        message = getattr(e, "message", f"{e.__class__.__name__}: {e}")
        message_text = wx.StaticText(self, label=message)

        error_icon = wx.ArtProvider.GetBitmap(
            wx.ART_ERROR, wx.ART_MESSAGE_BOX, wx.Size(32, 32)
        )
        icon = wx.StaticBitmap(self, bitmap=error_icon)

        icon_and_message_sizer = wx.BoxSizer(wx.HORIZONTAL)
        icon_and_message_sizer.Add(icon, 0, wx.ALL, 10)
        icon_and_message_sizer.Add(
            message_text, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 10
        )

        traceback_str = traceback.format_exc()
        details_text = wx.TextCtrl(
            self,
            value=traceback_str,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL,
        )
        self.adjust_size_to_text(details_text, traceback_str)

        buttons = self.CreateButtonSizer(wx.OK)

        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(icon_and_message_sizer, 0, wx.EXPAND | wx.ALL, 5)
        box.Add(details_text, 0, wx.EXPAND | wx.ALL, 5)
        box.Add(buttons, 0, wx.EXPAND | wx.ALL, 5)

        self.SetSizerAndFit(box)

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


if __name__ == "__main__":
    import threading

    try:
        _ = 1 / 0
    except Exception as e:
        app = wx.App()
        dlg = ErrorDialog(None, e)

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

        print("exit ok")
