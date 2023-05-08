import wx


class KbplacerDialog(wx.Dialog):
    def __init__(self, parent, title) -> None:
        style = wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER
        super(KbplacerDialog, self).__init__(parent, -1, title, style=style)
        row1 = wx.BoxSizer(wx.HORIZONTAL)

        text = wx.StaticText(self, -1, "Select kle json file:")
        row1.Add(text, 0, wx.LEFT | wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 5)

        layout_file_picker = wx.FilePickerCtrl(self, -1)
        row1.Add(layout_file_picker, 1, wx.EXPAND | wx.ALL, 5)

        row2 = wx.BoxSizer(wx.HORIZONTAL)

        key_annotation_label = wx.StaticText(self, -1, "Key annotation format string:")
        row2.Add(
            key_annotation_label, 1, wx.LEFT | wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 5
        )

        key_annotation_format = wx.TextCtrl(self, value="SW{}")
        row2.Add(key_annotation_format, 1, wx.EXPAND | wx.ALL, 5)

        row3 = wx.BoxSizer(wx.HORIZONTAL)

        stabilizer_annotation_label = wx.StaticText(
            self, -1, "Stabilizer annotation format string:"
        )
        row3.Add(
            stabilizer_annotation_label,
            1,
            wx.LEFT | wx.RIGHT | wx.ALIGN_CENTER_VERTICAL,
            5,
        )

        stabilizer_annotation_format = wx.TextCtrl(self, value="ST{}")
        row3.Add(stabilizer_annotation_format, 1, wx.EXPAND | wx.ALL, 5)

        row4 = wx.BoxSizer(wx.HORIZONTAL)

        diode_annotation_label = wx.StaticText(
            self, -1, "Diode annotation format string:"
        )
        row4.Add(
            diode_annotation_label, 1, wx.LEFT | wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 5
        )

        diode_annotation_format = wx.TextCtrl(self, value="D{}")
        row4.Add(diode_annotation_format, 1, wx.EXPAND | wx.ALL, 5)

        row5 = wx.BoxSizer(wx.HORIZONTAL)

        tracks_checkbox = wx.CheckBox(self, label="Add tracks")
        tracks_checkbox.SetValue(True)
        row5.Add(tracks_checkbox, 1, wx.EXPAND | wx.ALL, 5)

        row6 = wx.BoxSizer(wx.HORIZONTAL)

        use_first_pair_as_template_checkbox = wx.CheckBox(
            self, label="Use first switch-diode pair as reference for relative position"
        )
        use_first_pair_as_template_checkbox.SetValue(False)
        row6.Add(use_first_pair_as_template_checkbox, 1, wx.EXPAND | wx.ALL, 5)

        row7 = wx.BoxSizer(wx.HORIZONTAL)
        key_distance_label = wx.StaticText(self, -1, "Key 1U distance [mm]:")
        row7.Add(
            key_distance_label, 1, wx.LEFT | wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 5
        )

        key_distance = wx.SpinCtrlDouble(self, initial=19.05, min=0, max=100, inc=0.01)
        row7.Add(key_distance, 1, wx.EXPAND | wx.ALL, 5)

        row8 = wx.BoxSizer(wx.HORIZONTAL)

        text = wx.StaticText(self, -1, "Select controller circuit template:")
        row8.Add(text, 0, wx.LEFT | wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 5)

        template_file_picker = wx.FilePickerCtrl(self, -1)
        row8.Add(template_file_picker, 1, wx.EXPAND | wx.ALL, 5)

        box = wx.BoxSizer(wx.VERTICAL)

        box.Add(row1, 0, wx.EXPAND | wx.ALL, 5)
        box.Add(row2, 0, wx.EXPAND | wx.ALL, 5)
        box.Add(row3, 0, wx.EXPAND | wx.ALL, 5)
        box.Add(row4, 0, wx.EXPAND | wx.ALL, 5)
        box.Add(row5, 0, wx.EXPAND | wx.ALL, 5)
        box.Add(row6, 0, wx.EXPAND | wx.ALL, 5)
        box.Add(row7, 0, wx.EXPAND | wx.ALL, 5)
        box.Add(row8, 0, wx.EXPAND | wx.ALL, 5)

        buttons = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        box.Add(buttons, 0, wx.EXPAND | wx.ALL, 5)

        self.SetSizerAndFit(box)
        self.__layout_file_picker = layout_file_picker
        self.__key_annotation_format = key_annotation_format
        self.__stabilizer_annotation_format = stabilizer_annotation_format
        self.__diode_annotation_format = diode_annotation_format
        self.__use_first_pair_as_template_checkbox = use_first_pair_as_template_checkbox
        self.__tracks_checkbox = tracks_checkbox
        self.__key_distance = key_distance
        self.__template_file_picker = template_file_picker

    def get_layout_path(self) -> str:
        return self.__layout_file_picker.GetPath()

    def get_key_annotation_format(self) -> str:
        return self.__key_annotation_format.GetValue()

    def get_stabilizer_annotation_format(self) -> str:
        return self.__stabilizer_annotation_format.GetValue()

    def get_diode_annotation_format(self) -> str:
        return self.__diode_annotation_format.GetValue()

    def is_tracks(self) -> bool:
        return self.__tracks_checkbox.GetValue()

    def is_first_pair_used_as_template(self) -> bool:
        return self.__use_first_pair_as_template_checkbox.GetValue()

    def get_key_distance(self) -> float:
        return self.__key_distance.GetValue()

    def get_template_path(self) -> str:
        return self.__template_file_picker.GetPath()
