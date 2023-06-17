from __future__ import annotations

import wx
from enum import StrEnum
from typing import List, Optional, Tuple

from .defaults import DEFAULT_DIODE_POSITION
from .element_position import ElementPosition, Point, Side


TEXT_CTRL_EXTRA_SPACE = 25


class Position(StrEnum):
    DEFAULT = "Default"
    CURRENT_RELATIVE = "Current relative"
    CUSTOM = "Custom"


class LabeledTextCtrl(wx.Panel):
    def __init__(self, parent, label: str, value: str) -> None:
        super().__init__(parent)

        self.label = wx.StaticText(self, -1, label)
        self.text = wx.TextCtrl(self, value=value)

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(self.label, 0, wx.LEFT | wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 5)
        sizer.Add(self.text, 0, wx.ALL, 5)

        self.SetSizer(sizer)


class CustomRadioBox(wx.Panel):
    def __init__(self, parent, choices: List[str]):
        super().__init__(parent)
        self.radio_buttons: dict[str, wx.RadioButton] = {}

        for choice in choices:
            radio_button = wx.RadioButton(self, label=choice)
            self.radio_buttons[choice] = radio_button

        # this is special hidden option to allow clearing (selecting none)
        self.none_button = wx.RadioButton(self, label="")
        self.none_button.Hide()

        sizer = wx.BoxSizer(wx.VERTICAL)
        for radio_button in self.radio_buttons.values():
            sizer.Add(radio_button, 0, wx.ALL, -2)

        self.SetSizer(sizer)

    def Select(self, choice):
        self.radio_buttons[choice].SetValue(True)

    def Clear(self):
        self.none_button.SetValue(True)

    def GetValue(self) -> Optional[str]:
        if self.none_button.GetValue():
            return None
        else:
            for choice, button in self.radio_buttons.items():
                if button.GetValue():
                    return choice
            return None


class ElementPositionWidget(wx.Panel):
    def __init__(self, parent, default: Optional[ElementPosition] = None) -> None:
        super().__init__(parent)

        self.default = default
        choices = [Position.CURRENT_RELATIVE, Position.CUSTOM]
        if self.default:
            choices.insert(0, Position.DEFAULT)

        self.dropdown = wx.ComboBox(self, choices=choices, style=wx.CB_DROPDOWN)
        self.dropdown.Bind(wx.EVT_COMBOBOX, self.__on_position_choice_change)

        expected_char_width = self.GetTextExtent("x").x
        expected_size = wx.Size(5 * expected_char_width + TEXT_CTRL_EXTRA_SPACE, -1)
        self.x = wx.TextCtrl(self, value="", size=expected_size)
        self.y = wx.TextCtrl(self, value="", size=expected_size)
        self.orientation = wx.TextCtrl(self, value="", size=expected_size)
        self.side = CustomRadioBox(self, choices=["Front", "Back"])

        self.__set_initial_state(choices[0])

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(wx.StaticText(self, -1, "Position:"), 0, wx.ALIGN_CENTER_VERTICAL, 5)
        sizer.Add(self.dropdown, 1, wx.EXPAND | wx.ALL, 5)
        sizer.Add(
            wx.StaticText(self, -1, "X/Y offset:"), 0, wx.ALIGN_CENTER_VERTICAL, 5
        )
        sizer.Add(self.x, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(wx.StaticText(self, -1, "/"), 0, wx.ALIGN_CENTER_VERTICAL, 5)
        sizer.Add(self.y, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(
            wx.StaticText(self, -1, "Orientation:"), 0, wx.ALIGN_CENTER_VERTICAL, 5
        )
        sizer.Add(self.orientation, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(self.side, 0, wx.EXPAND | wx.ALL, 5)

        self.SetSizer(sizer)

    def __set_initial_state(self, choice) -> None:
        self.dropdown.SetValue(choice)
        self.__set_position_by_choice(choice)

    def __on_position_choice_change(self, event) -> None:
        choice = event.GetString()
        self.__set_position_by_choice(choice)

    def __set_position_by_choice(self, choice: str) -> None:
        if choice == Position.DEFAULT:
            self.__set_position_to_default()
        elif choice == Position.CURRENT_RELATIVE:
            self.__set_position_to_empty_non_editable()
        elif choice == Position.CUSTOM:
            self.__set_position_to_zero_editable()
        else:
            raise ValueError
        self.choice = Position(choice)

    def __set_position_to_default(self) -> None:
        if self.default:
            x = str(self.default.relative_position.x)
            y = str(self.default.relative_position.y)
            self.__set_coordinates(x, y)
            self.orientation.SetValue(str(self.default.orientation))
            self.side.Select("Back")
            self.__disable_position_controls()

    def __set_position_to_zero_editable(self) -> None:
        self.__set_coordinates("0", "0")
        self.orientation.SetValue("0")
        self.side.Select("Back")
        self.__enable_position_controls()

    def __set_position_to_empty_non_editable(self):
        self.__set_coordinates("-", "-")
        self.orientation.SetValue("-")
        self.side.Clear()
        self.__disable_position_controls()

    def __set_coordinates(self, x: str, y: str):
        self.x.SetValue(x)
        self.y.SetValue(y)

    def __enable_position_controls(self):
        self.x.Enable()
        self.y.Enable()
        self.orientation.Enable()
        self.side.Enable()

    def __disable_position_controls(self):
        self.x.Disable()
        self.y.Disable()
        self.orientation.Disable()
        self.side.Disable()

    def GetValue(self) -> Tuple[Position, Optional[ElementPosition]]:
        if self.choice == Position.DEFAULT or self.choice == Position.CUSTOM:
            x = float(self.x.GetValue())
            y = float(self.y.GetValue())
            orientation = float(self.orientation.GetValue())
            side_str = self.side.GetValue()
            return self.choice, ElementPosition(
                Point(x, y), orientation, Side(side_str == "Back")
            )
        else:
            return self.choice, None

    def Enable(self):
        self.dropdown.Enable()
        self.__set_position_by_choice(self.dropdown.GetValue())

    def Disable(self):
        self.__disable_position_controls()
        self.dropdown.Disable()


class ElementSettingsWidget(wx.Panel):
    def __init__(
        self,
        parent,
        default_annotation: str,
        default_position: Optional[ElementPosition] = None,
    ) -> None:
        super().__init__(parent)

        self.expected_char_width = self.GetTextExtent("x").x
        annotation_format_size = wx.Size(
            self.expected_char_width * 3 + TEXT_CTRL_EXTRA_SPACE, -1
        )
        self.annotation_format = wx.TextCtrl(
            self, value=default_annotation, size=annotation_format_size
        )
        self.position_widget = ElementPositionWidget(self, default=default_position)

        sizer = wx.BoxSizer(wx.HORIZONTAL)

        sizer.Add(
            wx.StaticText(self, -1, "Annotation format:"),
            0,
            wx.ALIGN_CENTER_VERTICAL,
            5,
        )
        sizer.Add(self.annotation_format, 0, wx.EXPAND | wx.ALL, 10)
        sizer.Add(self.position_widget, 0, wx.EXPAND | wx.ALL, 5)

        self.SetSizer(sizer)

    def Enable(self):
        self.annotation_format.Enable()
        self.position_widget.Enable()

    def Disable(self):
        self.annotation_format.Disable()
        self.position_widget.Disable()


class KbplacerDialog(wx.Dialog):
    def __init__(self, parent, title) -> None:
        style = wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER
        super(KbplacerDialog, self).__init__(parent, -1, title, style=style)

        self.expected_char_width = self.GetTextExtent("x").x

        switch_section = self.get_switch_section()
        switch_diodes_section = self.get_switch_diodes_section()
        # not supported yet:
        # additional_elements_section = self.get_additional_elements_section()
        misc_section = self.get_misc_section()

        box = wx.BoxSizer(wx.VERTICAL)

        box.Add(switch_section, 0, wx.EXPAND | wx.ALL, 5)
        box.Add(switch_diodes_section, 0, wx.EXPAND | wx.ALL, 5)
        # not supported yet:
        # box.Add(additional_elements_section, 0, wx.EXPAND | wx.ALL, 5)
        box.Add(misc_section, 0, wx.EXPAND | wx.ALL, 5)

        buttons = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        box.Add(buttons, 0, wx.EXPAND | wx.ALL, 5)

        self.SetSizerAndFit(box)

    def get_switch_section(self):
        key_annotation = LabeledTextCtrl(self, "Switch annotation format:", "SW{}")
        stabilizer_annotation = LabeledTextCtrl(
            self, "Stabilizer annotation format:", "ST{}"
        )

        layout_label = wx.StaticText(self, -1, "KLE json file:")
        layout_file_picker = wx.FilePickerCtrl(self, -1)

        key_distance_label = wx.StaticText(self, -1, "1U distance [mm]:")
        key_distance = wx.SpinCtrlDouble(self, initial=19.05, min=0, max=100, inc=0.01)

        row1 = wx.BoxSizer(wx.HORIZONTAL)
        row1.Add(layout_label, 0, wx.LEFT | wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 5)
        row1.Add(layout_file_picker, 1, wx.ALL, 5)

        row2 = wx.BoxSizer(wx.HORIZONTAL)
        row2.Add(key_annotation, 0, wx.EXPAND | wx.ALL, 0)
        row2.Add(stabilizer_annotation, 0, wx.EXPAND | wx.ALL, 0)

        row3 = wx.BoxSizer(wx.HORIZONTAL)
        row3.Add(
            key_distance_label, 0, wx.LEFT | wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 5
        )
        row3.Add(key_distance, 0, wx.ALL, 5)

        box = wx.StaticBox(self, label="Switch settings")
        sizer = wx.StaticBoxSizer(box, wx.VERTICAL)

        sizer.Add(row1, 0, wx.EXPAND | wx.ALL, 0)
        sizer.Add(row2, 0, wx.EXPAND | wx.ALL, 0)
        sizer.Add(row3, 0, wx.EXPAND | wx.ALL, 0)

        self.__key_annotation_format = key_annotation.text
        self.__stabilizer_annotation_format = stabilizer_annotation.text
        self.__layout_file_picker = layout_file_picker
        self.__key_distance = key_distance

        return sizer

    def get_switch_diodes_section(self):
        place_diodes_checkbox = wx.CheckBox(self, label="Enable placement")
        place_diodes_checkbox.SetValue(True)
        place_diodes_checkbox.Bind(wx.EVT_CHECKBOX, self.on_diode_place_checkbox)

        diode_settings = ElementSettingsWidget(
            self, "D{}", default_position=DEFAULT_DIODE_POSITION
        )

        box = wx.StaticBox(self, label="Switch diodes settings")
        sizer = wx.StaticBoxSizer(box, wx.VERTICAL)
        sizer.Add(place_diodes_checkbox, 0, wx.EXPAND | wx.ALL, 5)
        # weird border value to make it aligned with 'additional_elements_section':
        sizer.Add(diode_settings, 0, wx.EXPAND | wx.ALL, 9)

        self.__place_diodes_checkbox = place_diodes_checkbox
        self.__diode_settings = diode_settings

        return sizer

    def on_diode_place_checkbox(self, event):
        is_checked = event.GetEventObject().IsChecked()
        if is_checked:
            self.__diode_settings.Enable()
        else:
            self.__diode_settings.Disable()

    def get_additional_elements_section(self):
        additional_elements = []

        scrolled_window = wx.ScrolledWindow(self)
        scrolled_window_sizer = wx.BoxSizer(wx.VERTICAL)

        scrolled_window.SetSizer(scrolled_window_sizer)
        virtual_width, virtual_height = scrolled_window_sizer.GetMinSize()
        scrolled_window.SetVirtualSize((virtual_width, virtual_height))
        scrolled_window.SetScrollRate(0, 10)

        box = wx.StaticBox(self, label="Additional elements settings")
        sizer = wx.StaticBoxSizer(box, wx.VERTICAL)

        sizer.Add(scrolled_window, 1, wx.EXPAND | wx.ALL, 10)

        dialog_width, _ = self.GetSize()
        sizer.SetMinSize((dialog_width, 180))

        buttons_sizer = wx.BoxSizer(wx.HORIZONTAL)

        def add_element(_) -> None:
            element_settings = ElementSettingsWidget(scrolled_window, "")
            additional_elements.append(element_settings)
            scrolled_window_sizer.Add(element_settings, 0, wx.ALIGN_LEFT, 0)
            self.Layout()

        add_element(_)
        add_button = wx.Button(self, label="+")
        add_button.Bind(wx.EVT_BUTTON, add_element)

        def remove_element(_) -> None:
            element_settings = (
                additional_elements.pop() if additional_elements else None
            )
            if element_settings:
                element_settings.Destroy()
                self.Layout()
            pass

        remove_button = wx.Button(self, label="-")
        remove_button.Bind(wx.EVT_BUTTON, remove_element)

        buttons_sizer.Add(add_button, 0, wx.EXPAND | wx.ALL, 0)
        buttons_sizer.Add(remove_button, 0, wx.EXPAND | wx.ALL, 0)

        sizer.Add(buttons_sizer, 0, wx.EXPAND | wx.ALL, 5)

        return sizer

    def get_misc_section(self):
        tracks_checkbox = wx.CheckBox(self, label="Add tracks")
        tracks_checkbox.SetValue(True)

        template_label = wx.StaticText(self, -1, "Controller circuit template:")
        template_file_picker = wx.FilePickerCtrl(self, -1)

        box = wx.StaticBox(self, label="Other settings")
        sizer = wx.StaticBoxSizer(box, wx.HORIZONTAL)

        sizer.Add(tracks_checkbox, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(wx.StaticLine(self, style=wx.LI_VERTICAL), 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(template_label, 0, wx.LEFT | wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 5)
        sizer.Add(template_file_picker, 1, wx.EXPAND | wx.ALL, 5)

        self.__tracks_checkbox = tracks_checkbox
        self.__template_file_picker = template_file_picker

        return sizer

    def get_layout_path(self) -> str:
        return self.__layout_file_picker.GetPath()

    def get_key_annotation_format(self) -> str:
        return self.__key_annotation_format.GetValue()

    def get_stabilizer_annotation_format(self) -> str:
        return self.__stabilizer_annotation_format.GetValue()

    def get_diode_annotation_format(self) -> str:
        return self.__diode_settings.annotation_format.GetValue()

    def is_tracks(self) -> bool:
        return self.__tracks_checkbox.GetValue()

    def is_diode_placement(self) -> bool:
        return self.__place_diodes_checkbox.GetValue()

    def get_key_distance(self) -> float:
        return self.__key_distance.GetValue()

    def get_template_path(self) -> str:
        return self.__template_file_picker.GetPath()

    def get_diode_position(self) -> Tuple[Position, Optional[ElementPosition]]:
        return self.__diode_settings.position_widget.GetValue()
