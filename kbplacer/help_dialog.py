import os
import re
import webbrowser

import wx

wx_ = wx.GetTranslation


class HelpDialog(wx.Dialog):
    def __init__(self, parent) -> None:
        super(HelpDialog, self).__init__(parent, -1, "kbplacer help")

        # inherit translations from parent:
        self._ = parent._ if parent else (lambda x: x)
        information_section = self.get_information_section()
        actions_section = self.get_actions_section()
        help_section = self.get_help_section()

        buttons = self.CreateButtonSizer(wx.OK)

        header = wx.BoxSizer(wx.HORIZONTAL)
        header.Add(information_section, 3, wx.ALL, 5)
        header.Add(actions_section, 1, wx.ALIGN_CENTER | wx.ALL, 5)

        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(header, 0, wx.EXPAND | wx.ALL, 5)
        box.Add(help_section, 0, wx.EXPAND | wx.ALL, 5)
        box.Add(buttons, 0, wx.EXPAND | wx.ALL, 5)

        self.SetSizerAndFit(box)

    def get_information_section(self):
        source_dir = os.path.dirname(__file__)
        icon_file_name = os.path.join(source_dir, "icon.png")
        icon = wx.Image(icon_file_name, wx.BITMAP_TYPE_ANY)
        icon_bitmap = wx.Bitmap(icon)
        static_icon_bitmap = wx.StaticBitmap(self, wx.ID_ANY, icon_bitmap)

        font = wx.Font(
            12, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD
        )
        name = wx.StaticText(self, -1, "Keyboard Footprints Placer")
        name.SetFont(font)

        version_file_name = os.path.join(source_dir, "version.txt")
        version_str = self._("<missing>")
        if os.path.isfile(version_file_name):
            with open(version_file_name, "r") as f:
                version_str = f.read()
        if not re.match(r"v\d.\d$", version_str):
            status = ", " + self._("development build")
        else:
            status = ""
        version = wx.StaticText(self, -1, wx_("Version") + f": {version_str}{status}")

        name_box = wx.BoxSizer(wx.HORIZONTAL)
        name_box.Add(static_icon_bitmap, 0, wx.ALL, 5)
        name_box.Add(name, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)

        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(name_box, 0, wx.ALL, 5)
        box.Add(version, 0, wx.ALL, 5)

        return box

    def get_actions_section(self):
        box = wx.BoxSizer(wx.VERTICAL)

        report_bug_button = wx.Button(self, label=wx_("Report Bug"))

        def on_report_bug(_) -> None:
            webbrowser.open(
                "https://github.com/adamws/kicad-kbplacer/issues/new?template=bug_report.md&title="
            )

        report_bug_button.Bind(wx.EVT_BUTTON, on_report_bug)

        donate_button = wx.Button(self, label=wx_("Donate"))

        def on_donate(_) -> None:
            webbrowser.open("https://ko-fi.com/adamws")

        donate_button.Bind(wx.EVT_BUTTON, on_donate)

        box.Add(report_bug_button, 0, wx.EXPAND | wx.ALL, 5)
        box.Add(donate_button, 0, wx.EXPAND | wx.ALL, 5)

        return box

    def get_help_section(self):
        box = wx.BoxSizer(wx.VERTICAL)
        help_message = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_AUTO_URL | wx.HSCROLL
        )

        bold_font = wx.Font(wx.FontInfo().Bold())
        bold_attr = wx.TextAttr(wx.BLACK)
        bold_attr.SetFont(bold_font)

        regular_font = wx.Font(wx.FontInfo())
        normal_attr = wx.TextAttr(wx.BLACK)
        normal_attr.SetFont(wx.Font(wx.FontInfo()))
        normal_attr.SetFont(regular_font)

        help_message.SetDefaultStyle(bold_attr)
        help_message.AppendText(wx_("Description"))
        help_message.AppendText("\n\n")

        help_message.SetDefaultStyle(normal_attr)
        help_message.AppendText(
            self._(
                "Plugin for mechanical keyboard design. "
                "It features automatic key placement \nbased on popular "
                "layout description from "
            )
        )
        help_message.SetDefaultStyle(wx.TextAttr(wx.BLUE))
        help_message.AppendText("www.keyboard-layout-editor.com")

        def on_open_url(event) -> None:
            url = help_message.GetValue()[event.GetURLStart() : event.GetURLEnd()]
            if event.MouseEvent.LeftDown():
                webbrowser.open(url)

        help_message.Bind(wx.EVT_TEXT_URL, on_open_url)

        help_message.SetDefaultStyle(bold_attr)
        help_message.AppendText("\n\n")
        help_message.AppendText(wx_("Help"))
        help_message.AppendText("\n\n")

        help_message.SetDefaultStyle(normal_attr)
        help_message.AppendText(" \u2022 " + self._("Project website - "))

        help_message.SetDefaultStyle(wx.TextAttr(wx.BLUE))
        help_message.AppendText("https://github.com/adamws/kicad-kbplacer")

        help_message.SetDefaultStyle(normal_attr)
        help_message.AppendText("\n \u2022 " + self._("Geekhack forum thread - "))

        help_message.SetDefaultStyle(wx.TextAttr(wx.BLUE))
        help_message.AppendText("https://geekhack.org/index.php?topic=106059.0")

        dc = wx.ScreenDC()
        dc.SetFont(regular_font)

        number_of_lines = help_message.GetNumberOfLines()
        size = (0, 0)
        for i in range(0, number_of_lines):
            line = help_message.GetLineText(i)
            size_new = dc.GetTextExtent(line)
            if size_new[0] > size[0]:
                size = size_new

        margin = 20
        size = (size[0] + margin, size[1] * number_of_lines + margin)
        help_message.SetMinSize(size)

        box.Add(help_message, 0, wx.EXPAND | wx.ALL, 5)
        return box


if __name__ == "__main__":
    import sys
    import threading

    _ = wx.App(False)
    dlg = HelpDialog(None)

    if "PYTEST_CURRENT_TEST" in os.environ:
        # use stdin for gracefully closing GUI when running
        # from pytest. This is required when measuring
        # coverage and process kill would cause measurement to be lost
        def listen_for_exit():
            while True:
                input("Press any key to exit: ")
                dlg.Close(wx.ID_CANCEL)
                sys.exit()

        input_thread = threading.Thread(target=listen_for_exit)
        input_thread.daemon = True
        input_thread.start()

    dlg.ShowModal()
