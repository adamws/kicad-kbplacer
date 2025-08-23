# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import webbrowser

import wx

from . import __version__
from .dialog_helper import MessageDialog

wx_ = wx.GetTranslation


class HelpDialog(MessageDialog):
    def __init__(self, parent) -> None:
        super(HelpDialog, self).__init__(parent, "kbplacer help")

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

    def get_information_section(self) -> wx.BoxSizer:
        source_dir = os.path.dirname(__file__)
        icon_file_name = os.path.join(source_dir, "icon.png")
        icon = wx.Image(icon_file_name, wx.BITMAP_TYPE_ANY)
        icon_bitmap = wx.Bitmap(icon)
        static_icon_bitmap = wx.StaticBitmap(self, wx.ID_ANY, bitmap=icon_bitmap)

        font = wx.Font(
            12, wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD
        )
        name = wx.StaticText(self, -1, "Keyboard Footprints Placer")
        name.SetFont(font)

        version = wx.StaticText(self, -1, wx_("Version") + f": {__version__}")

        name_box = wx.BoxSizer(wx.HORIZONTAL)
        name_box.Add(static_icon_bitmap, 0, wx.ALL, 5)
        name_box.Add(name, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 5)

        box = wx.BoxSizer(wx.VERTICAL)
        box.Add(name_box, 0, wx.ALL, 5)
        box.Add(version, 0, wx.ALL, 5)

        return box

    def get_actions_section(self) -> wx.BoxSizer:
        box = wx.BoxSizer(wx.VERTICAL)

        report_bug_button = wx.Button(self, label=wx_("Report Bug"))

        def on_report_bug(_: wx.Event) -> None:
            webbrowser.open(
                "https://github.com/adamws/kicad-kbplacer/issues/new?template=bug_report.md&title="
            )

        report_bug_button.Bind(wx.EVT_BUTTON, on_report_bug)

        donate_button = wx.Button(self, label=wx_("Donate"))

        def on_donate(_: wx.Event) -> None:
            webbrowser.open("https://ko-fi.com/adamws")

        donate_button.Bind(wx.EVT_BUTTON, on_donate)

        box.Add(report_bug_button, 0, wx.EXPAND | wx.ALL, 5)
        box.Add(donate_button, 0, wx.EXPAND | wx.ALL, 5)

        return box

    def get_help_section(self) -> wx.BoxSizer:
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

        def on_open_url(event: wx.TextUrlEvent) -> None:
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
        longest_line = ""
        for i in range(0, number_of_lines):
            line = help_message.GetLineText(i)
            if len(line) > len(longest_line):
                longest_line = line

        self.adjust_size_to_text(help_message, longest_line)

        box.Add(help_message, 0, wx.EXPAND | wx.ALL, 5)
        return box


if __name__ == "__main__":
    from .dialog_helper import show_with_test_support

    show_with_test_support(HelpDialog, None)
    print("exit ok")
