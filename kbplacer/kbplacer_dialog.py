# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import gettext
import json
import logging
import os
import re
import string
import sys
from dataclasses import asdict, dataclass, field
from enum import Flag
from typing import List, Optional, Tuple

import wx
from wx.lib.embeddedimage import PyEmbeddedImage

from .defaults import DEFAULT_DIODE_POSITION, ZERO_POSITION
from .element_position import ElementInfo, ElementPosition, PositionOption, Side
from .help_dialog import HelpDialog

logger = logging.getLogger(__name__)
TEXT_CTRL_EXTRA_SPACE = 25

# Most of the phrases used in this plugin are already in use in KiCad.
# It means that we get translations for free using `wx.GetTranslation`.
# All strings translated with 'wx_' are expected to be a part of
# KiCad's translation files. All remaining will be translated with
# another custom mechanism or will remain default.
wx_ = wx.GetTranslation

# Currently there is no elegant way to check which language is loaded by KiCad.
# This feature has been requested here:
#   https://gitlab.com/kicad/code/kicad/-/issues/10573
# Until then, use workaroud - request translation with wx_ and use result
# in lookup table. This lookup should contain all installed languages defined
# in translation/pofiles/LINGUAS_INSTALL.
KICAD_TRANSLATIONS_LOOKUP = {
    "Sprache": "de",
    "Set Language": "en",
    "Seleccionar idioma": "es",
    "Aseta Kieli": "fi",
    "言語設定": "ja",
    "언어 설정": "ko",
    "Taal instellen": "nl",
    "Ustaw język": "pl",
    "Установить язык": "ru",
    "Nastaviť jazyk": "sk",
    "Встановити мову": "uk",
    "設定語言": "zh_CN",
}


@dataclass
class WindowState:
    layout_path: str = ""
    key_distance: Tuple[float, float] = (19.05, 19.05)
    key_info: ElementInfo = field(
        default_factory=lambda: ElementInfo(
            "SW{}", PositionOption.DEFAULT, ZERO_POSITION, ""
        )
    )
    enable_diode_placement: bool = True
    route_switches_with_diodes: bool = True
    optimize_diodes_orientation: bool = False
    diode_info: ElementInfo = field(
        default_factory=lambda: ElementInfo(
            "D{}", PositionOption.DEFAULT, DEFAULT_DIODE_POSITION, ""
        )
    )
    additional_elements: List[ElementInfo] = field(
        default_factory=lambda: [
            ElementInfo("ST{}", PositionOption.CUSTOM, ZERO_POSITION, "")
        ]
    )
    route_rows_and_columns: bool = True
    template_path: str = ""
    generate_outline: bool = False
    outline_delta: float = 0.0
    # starting index for footprint numbering (default preserves legacy behavior)
    start_index: int = 1

    def __str__(self) -> str:
        return json.dumps(asdict(self), indent=None)

    @classmethod
    def from_dict(cls, data: dict) -> WindowState:
        key_distance = data.pop("key_distance")
        if type(key_distance) is list:
            key_distance = tuple(key_distance)
        key_info = ElementInfo.from_dict(data.pop("key_info"))
        diode_info = ElementInfo.from_dict(data.pop("diode_info"))
        additional_elements = [
            ElementInfo.from_dict(i) for i in data.pop("additional_elements")
        ]
        start_index = data.pop("start_index", 1)
        return cls(
            key_distance=key_distance,
            key_info=key_info,
            diode_info=diode_info,
            additional_elements=additional_elements,
            start_index=start_index,
            **data,
        )


def get_current_kicad_language() -> str:
    kicad_lang = KICAD_TRANSLATIONS_LOOKUP.get(wx_("Set Language"), "en")
    # some languages require additional lookup to detect correctly,
    # for example es vs es_MX:
    if kicad_lang == "es" and wx_("Enabled:") == "Activado:":
        # es: Enabled -> Habilitado, es_MX: Enabled -> Activado
        kicad_lang = "es_MX"
    return kicad_lang


def get_plugin_translator(lang: str = "en"):
    localedir = os.path.join(os.path.dirname(__file__), "locale")
    trans = gettext.translation(
        "kbplacer", localedir=localedir, languages=(lang,), fallback=True
    )
    return trans.gettext


def get_file_picker(*args, **kwargs) -> wx.FilePickerCtrl:
    file_picker = wx.FilePickerCtrl(*args, **kwargs)
    file_picker.SetTextCtrlGrowable(True)

    def _update_position(_) -> None:
        text_ctrl = file_picker.GetTextCtrl()
        # when updating from file chooser window we want automatically
        # move to the end (it looks better when not whole path fits),
        # but when user updates by typing in text control we don't
        # want to mess up with it. This can be done by checking
        # if current insertion point is 0.
        if text_ctrl.GetInsertionPoint() == 0:
            text_ctrl.SetInsertionPointEnd()

    file_picker.Bind(wx.EVT_FILEPICKER_CHANGED, _update_position)
    return file_picker


class FloatValidator(wx.Validator):
    def __init__(self) -> None:
        wx.Validator.__init__(self)
        self.Bind(wx.EVT_CHAR, self.OnChar)

    def Clone(self) -> FloatValidator:
        return FloatValidator()

    def Validate(self, _) -> bool:
        text_ctrl = self.GetWindow()
        if not text_ctrl.IsEnabled():
            return True

        text = text_ctrl.GetValue()
        try:
            float(text)
            return True
        except ValueError:
            # this can happen when value is empty, equal '-', '.', or '-.',
            # other invalid values should not be allowed by 'OnChar' filtering
            name = text_ctrl.GetName()
            wx.MessageBox(f"Invalid '{name}' value: '{text}' is not a number!", "Error")
            text_ctrl.SetFocus()
            return False

    def TransferToWindow(self) -> bool:
        return True

    def TransferFromWindow(self) -> bool:
        return True

    def OnChar(self, event: wx.KeyEvent) -> None:
        text_ctrl = self.GetWindow()
        current_position = text_ctrl.GetInsertionPoint()
        keycode = int(event.GetKeyCode())
        if keycode in [
            wx.WXK_BACK,
            wx.WXK_DELETE,
            wx.WXK_LEFT,
            wx.WXK_RIGHT,
            wx.WXK_NUMPAD_LEFT,
            wx.WXK_NUMPAD_RIGHT,
            wx.WXK_TAB,
        ]:
            event.Skip()
        else:
            text_ctrl = self.GetWindow()
            text = text_ctrl.GetValue()
            key = chr(keycode)
            if (
                # allow only digits
                # or single '-' when as first character
                # or single '.'
                key in string.digits
                or (key == "-" and "-" not in text and current_position == 0)
                or (key == "." and "." not in text)
            ):
                event.Skip()


class IntValidator(wx.Validator):
    def __init__(self) -> None:
        wx.Validator.__init__(self)
        self.Bind(wx.EVT_CHAR, self.OnChar)

    def Clone(self) -> IntValidator:
        return IntValidator()

    def Validate(self, _) -> bool:
        text_ctrl = self.GetWindow()
        if not text_ctrl.IsEnabled():
            return True

        text = text_ctrl.GetValue()
        try:
            int(text)
            return True
        except ValueError:
            name = text_ctrl.GetName()
            wx.MessageBox(f"Invalid '{name}' value: '{text}' is not an integer!", "Error")
            text_ctrl.SetFocus()
            return False

    def TransferToWindow(self) -> bool:
        return True

    def TransferFromWindow(self) -> bool:
        return True

    def OnChar(self, event: wx.KeyEvent) -> None:
        keycode = int(event.GetKeyCode())
        if keycode in [
            wx.WXK_BACK,
            wx.WXK_DELETE,
            wx.WXK_LEFT,
            wx.WXK_RIGHT,
            wx.WXK_NUMPAD_LEFT,
            wx.WXK_NUMPAD_RIGHT,
            wx.WXK_TAB,
        ]:
            event.Skip()
        else:
            key = chr(keycode)
            # allow only digits and optional leading '-'
            text_ctrl = self.GetWindow()
            text = text_ctrl.GetValue()
            current_position = text_ctrl.GetInsertionPoint()
            if key in string.digits or (key == "-" and "-" not in text and current_position == 0):
                event.Skip()


class AnnotationValidator(wx.Validator):
    # probably not as strict as KiCad footprints annotations,
    # we just check if there is exactly one '{}' placeholder which
    # must be a part of some non-whitespace content
    PATTERN = r"^(?!\s*\{\}\s*$)(?:[^{}]*\{\}[^{}]*)$"

    def __init__(self) -> None:
        wx.Validator.__init__(self)

    def Clone(self) -> AnnotationValidator:
        return AnnotationValidator()

    def Validate(self, _) -> bool:
        text_ctrl = self.GetWindow()
        text = text_ctrl.GetValue()
        if not re.fullmatch(AnnotationValidator.PATTERN, text):
            name = text_ctrl.GetName()
            wx.MessageBox(
                f"Invalid '{name}' value. Annotation must have exactly one "
                "'{}' placeholder, and it must be a part of non-whitespace "
                f"content. Received: '{text}'",
                "Error",
            )
            text_ctrl.SetFocus()
            return False
        return True

    def TransferToWindow(self) -> bool:
        return True

    def TransferFromWindow(self) -> bool:
        return True


class LabeledTextCtrl(wx.Panel):
    def __init__(
        self,
        parent: wx.Window,
        label: str,
        value: str,
        width: int = -1,
        validator: wx.Validator = wx.DefaultValidator,
        *,
        tooltip: str = "",
    ) -> None:
        super().__init__(parent)

        expected_char_width = self.GetTextExtent("x").x
        if width != -1:
            annotation_format_size = wx.Size(
                expected_char_width * width + TEXT_CTRL_EXTRA_SPACE, -1
            )
        else:
            annotation_format_size = wx.Size(-1, -1)

        self.label = wx.StaticText(self, -1, label)
        self.text = wx.TextCtrl(
            self,
            value=value,
            size=annotation_format_size,
            validator=validator,
            name=label.strip(":"),
        )
        if tooltip:
            self.label.SetToolTip(tooltip)
            self.text.SetToolTip(tooltip)

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(self.label, 0, wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 5)
        sizer.Add(self.text, 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 5)

        self.SetSizer(sizer)

    def Enable(self) -> None:
        self.label.Enable()
        self.text.Enable()

    def Disable(self) -> None:
        self.label.Disable()
        self.text.Disable()

    def Hide(self) -> None:
        self.label.Hide()
        self.text.Hide()


class CustomRadioBox(wx.Panel):
    def __init__(self, parent: wx.Window, choices: List[str]) -> None:
        super().__init__(parent)
        self.radio_buttons: dict[str, wx.RadioButton] = {}

        for choice in choices:
            radio_button = wx.RadioButton(self, label=choice)
            self.radio_buttons[choice] = radio_button

        # this is special hidden option to allow clearing (selecting none)
        self.none_button = wx.RadioButton(self, label="")
        self.none_button.Hide()

        # on linux, use negative border because otherwise it looks too spaced out
        space = 0 if sys.platform == "win32" else -2
        sizer = wx.BoxSizer(wx.VERTICAL)
        for radio_button in self.radio_buttons.values():
            sizer.Add(radio_button, 0, wx.TOP | wx.BOTTOM, space)

        self.SetSizer(sizer)

    def Select(self, choice: str) -> None:
        self.radio_buttons[choice].SetValue(True)

    def Clear(self) -> None:
        self.none_button.SetValue(True)

    def GetValue(self) -> Optional[str]:
        if not self.none_button.GetValue():
            for choice, button in self.radio_buttons.items():
                if button.GetValue():
                    return choice
        return None


class ElementPositionWidget(wx.Panel):
    def __init__(
        self,
        parent: wx.Window,
        default_position: Optional[ElementPosition] = None,
        disable_offsets: bool = False,
    ) -> None:
        super().__init__(parent)

        self.default = default_position
        self.x = LabeledTextCtrl(
            self, wx_("Offset X:"), value="", width=5, validator=FloatValidator()
        )
        self.y = LabeledTextCtrl(
            self, wx_("Y:"), value="", width=5, validator=FloatValidator()
        )
        self.orientation = LabeledTextCtrl(
            self, wx_("Orientation:"), value="", width=5, validator=FloatValidator()
        )
        if disable_offsets:
            self.x.Hide()
            self.y.Hide()
        self.side_label = wx.StaticText(self, -1, wx_("Side:"))
        self.side = CustomRadioBox(self, choices=[wx_("Front"), wx_("Back")])

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        if not disable_offsets:
            sizer.Add(self.x, 0, wx.EXPAND | wx.LEFT, 5)
            sizer.Add(self.y, 0, wx.EXPAND | wx.LEFT, 5)
        sizer.Add(self.orientation, 0, wx.EXPAND | wx.LEFT, 5)
        sizer.Add(self.side_label, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 5)
        sizer.Add(self.side, 0, wx.EXPAND | wx.LEFT, 5)

        self.SetSizer(sizer)

    def set_position_by_choice(self, choice: str) -> None:
        if choice == PositionOption.DEFAULT:
            self.__set_position_to_default()
        elif choice == PositionOption.CUSTOM:
            self.__set_position_to_zero_editable()
        else:
            self.__set_position_to_empty_non_editable()

    def set_position(self, position: ElementPosition) -> None:
        self.__set_coordinates(str(position.x), str(position.y))
        self.__set_orientation(str(position.orientation))
        self.__set_side(position.side)

    def __set_position_to_default(self) -> None:
        if self.default:
            x = str(self.default.x)
            y = str(self.default.y)
            self.__set_coordinates(x, y)
            self.__set_orientation(str(self.default.orientation))
            self.__set_side(self.default.side)
            self.Disable()

    def __set_position_to_zero_editable(self) -> None:
        self.__set_coordinates("0", "0")
        self.__set_orientation("0")
        self.__set_side(Side.FRONT)
        self.Enable()

    def __set_position_to_empty_non_editable(self) -> None:
        self.__set_coordinates("-", "-")
        self.__set_orientation("-")
        self.side.Clear()
        self.Disable()

    def __set_coordinates(self, x: str, y: str) -> None:
        self.x.text.SetValue(x)
        self.y.text.SetValue(y)

    def __set_orientation(self, orientation: str) -> None:
        self.orientation.text.SetValue(orientation)

    def __set_side(self, side: Side) -> None:
        if side == Side.BACK:
            self.side.Select(wx_("Back"))
        else:
            self.side.Select(wx_("Front"))

    def __get_side(self) -> Side:
        side_str = str(self.side.GetValue())
        if side_str == wx_("Back"):
            return Side.BACK
        else:
            return Side.FRONT

    def GetValue(self) -> ElementPosition:
        x = float(self.x.text.GetValue())
        y = float(self.y.text.GetValue())
        orientation = float(self.orientation.text.GetValue())
        return ElementPosition(x, y, orientation, self.__get_side())

    def Enable(self) -> None:
        self.x.Enable()
        self.y.Enable()
        self.orientation.Enable()
        self.side_label.Enable()
        self.side.Enable()

    def Disable(self) -> None:
        self.x.Disable()
        self.y.Disable()
        self.orientation.Disable()
        self.side_label.Disable()
        self.side.Disable()


class TemplateType(Flag):
    LOAD = False
    SAVE = True


class ElementTemplateSelectionWidget(wx.Panel):
    def __init__(
        self, parent: wx.Window, picker_type: TemplateType, initial_path: str = ""
    ) -> None:
        super().__init__(parent)
        self._ = self.GetTopLevelParent()._

        label = (
            self._("Save to:")
            if picker_type == TemplateType.SAVE
            else self._("Load from:")
        )
        layout_label = wx.StaticText(self, -1, label)
        layout_picker = get_file_picker(
            self,
            -1,
            wildcard="KiCad printed circuit board files (*.kicad_pcb)|*.kicad_pcb",
            style=wx.FLP_USE_TEXTCTRL
            | (wx.FLP_SAVE if picker_type == TemplateType.SAVE else wx.FLP_OPEN),
        )

        if initial_path:
            layout_picker.SetPath(initial_path)
            layout_picker.GetTextCtrl().SetInsertionPointEnd()

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(layout_label, 0, wx.LEFT | wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 5)
        sizer.Add(layout_picker, 1, wx.EXPAND | wx.ALL, 5)
        self.SetSizer(sizer)

        self.__layout_picker = layout_picker

    def GetValue(self) -> str:
        return self.__layout_picker.GetPath()


class ElementPositionChoiceWidget(wx.Panel):
    def __init__(
        self,
        parent: wx.Window,
        initial_choice: PositionOption,
        initial_position: Optional[ElementPosition] = None,
        default_position: Optional[ElementPosition] = None,
        initial_path: str = "",
    ) -> None:
        super().__init__(parent)

        choices = [
            PositionOption.CUSTOM,
            PositionOption.RELATIVE,
            PositionOption.PRESET,
        ]
        if default_position:
            choices.insert(0, PositionOption.DEFAULT)

        self.dropdown = wx.ComboBox(self, choices=choices, style=wx.CB_DROPDOWN)
        self.dropdown.Bind(wx.EVT_COMBOBOX, self.__on_position_choice_change)

        dropdown_sizer = wx.BoxSizer(wx.HORIZONTAL)
        dropdown_sizer.Add(
            wx.StaticText(self, -1, wx_("Position") + ":"),
            0,
            wx.RIGHT | wx.ALIGN_CENTER_VERTICAL,
            5,
        )
        dropdown_sizer.Add(self.dropdown, 0, wx.EXPAND | wx.TOP | wx.BOTTOM, 5)

        self.position = ElementPositionWidget(self, default_position)
        self.load_template = ElementTemplateSelectionWidget(
            self, picker_type=TemplateType.LOAD, initial_path=initial_path
        )
        self.save_template = ElementTemplateSelectionWidget(
            self, picker_type=TemplateType.SAVE, initial_path=initial_path
        )

        self.__set_initial_state(initial_choice)
        if initial_position and initial_choice == PositionOption.CUSTOM:
            self.position.set_position(initial_position)

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(dropdown_sizer, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(self.position, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(self.load_template, 1, wx.EXPAND | wx.ALL, 5)
        sizer.Add(self.save_template, 1, wx.EXPAND | wx.ALL, 5)

        self.SetSizer(sizer)

    def __set_initial_state(self, choice: str) -> None:
        self.dropdown.SetValue(choice)
        self.__set_position_by_choice(choice)

    def __on_position_choice_change(self, event: wx.CommandEvent) -> None:
        choice = event.GetString()
        self.__set_position_by_choice(choice)

    def __set_position_by_choice(self, choice: str) -> None:
        if choice == PositionOption.RELATIVE:
            self.position.Hide()
            self.load_template.Hide()
            self.save_template.Show()
        elif choice == PositionOption.PRESET:
            self.position.Hide()
            self.load_template.Show()
            self.save_template.Hide()
        else:
            self.position.Show()
            self.load_template.Hide()
            self.save_template.Hide()
        self.GetTopLevelParent().Layout()
        self.position.set_position_by_choice(choice)
        self.choice = PositionOption(choice)

    def GetValue(self) -> Tuple[PositionOption, Optional[ElementPosition], str]:
        template_path = ""
        if self.dropdown.GetValue() == PositionOption.RELATIVE:
            template_path = self.save_template.GetValue()
        elif self.dropdown.GetValue() == PositionOption.PRESET:
            template_path = self.load_template.GetValue()

        if self.choice not in [PositionOption.DEFAULT, PositionOption.CUSTOM]:
            return self.choice, None, template_path
        return self.choice, self.position.GetValue(), template_path

    def Enable(self) -> None:
        self.dropdown.Enable()
        if self.dropdown.GetValue() == PositionOption.CUSTOM:
            self.position.Enable()
        self.load_template.Enable()
        self.save_template.Enable()

    def Disable(self) -> None:
        self.dropdown.Disable()
        self.position.Disable()
        self.load_template.Disable()
        self.save_template.Disable()


class ElementSettingsWidget(wx.Panel):
    def __init__(
        self,
        parent: wx.Window,
        element_info: ElementInfo,
        default_position: Optional[ElementPosition] = None,
    ) -> None:
        super().__init__(parent)

        self.annotation_format = LabeledTextCtrl(
            self,
            label=wx_("Footprint Annotation") + ":",
            value=element_info.annotation_format,
            width=3,
            validator=AnnotationValidator(),
        )
        self.position_widget = ElementPositionChoiceWidget(
            self,
            element_info.position_option,
            element_info.position,
            default_position=default_position,
            initial_path=element_info.template_path,
        )

        sizer = wx.BoxSizer(wx.HORIZONTAL)

        sizer.Add(
            self.annotation_format, 0, wx.EXPAND | wx.TOP | wx.BOTTOM | wx.RIGHT, 5
        )
        sizer.Add(self.position_widget, 1, wx.EXPAND | wx.ALL, 0)

        self.SetSizer(sizer)

    def GetValue(self) -> ElementInfo:
        annotation = self.annotation_format.text.GetValue()
        position = self.position_widget.GetValue()
        return ElementInfo(annotation, *position)

    def Enable(self) -> None:
        self.position_widget.Enable()

    def Disable(self) -> None:
        self.position_widget.Disable()


class KbplacerDialog(wx.Dialog):
    def __init__(
        self,
        parent: Optional[wx.Window],
        title: str,
        initial_state: WindowState = WindowState(),
    ) -> None:
        style = wx.DEFAULT_DIALOG_STYLE
        super(KbplacerDialog, self).__init__(parent, -1, title, style=style)

        language = get_current_kicad_language()
        logger.info(f"Language: {language}")
        self._ = get_plugin_translator(language)

        switch_section = self.get_switch_section(
            layout_path=initial_state.layout_path,
            key_distance=initial_state.key_distance,
            element_info=initial_state.key_info,
            start_index=initial_state.start_index,
        )

        switch_diodes_section = self.get_switch_diodes_section(
            enable=initial_state.enable_diode_placement,
            route_switches_with_diodes=initial_state.route_switches_with_diodes,
            optimize_diodes_orientation=initial_state.optimize_diodes_orientation,
            element_info=initial_state.diode_info,
        )

        additional_elements_section = self.get_additional_elements_section(
            elements_info=initial_state.additional_elements,
        )

        misc_section = self.get_misc_section(
            route_rows_and_columns=initial_state.route_rows_and_columns,
            template_path=initial_state.template_path,
            generate_outline=initial_state.generate_outline,
            outline_delta=initial_state.outline_delta,
        )

        box = wx.BoxSizer(wx.VERTICAL)

        box.Add(switch_section, 0, wx.EXPAND | wx.ALL, 5)
        box.Add(switch_diodes_section, 0, wx.EXPAND | wx.ALL, 5)
        box.Add(additional_elements_section, 0, wx.EXPAND | wx.ALL, 5)
        box.Add(misc_section, 0, wx.EXPAND | wx.ALL, 5)

        buttons = self.CreateButtonSizer(wx.OK | wx.CANCEL | wx.HELP)

        if help_button := wx.FindWindowById(wx.ID_HELP, self):
            help_button.Bind(wx.EVT_BUTTON, self.on_help_button)

        box.Add(buttons, 0, wx.EXPAND | wx.ALL, 5)

        self.SetSizerAndFit(box)

    def get_switch_section(
        self,
        layout_path: str = "",
        key_distance: Tuple[float, float] = (19.05, 19.05),
        element_info: ElementInfo = ElementInfo(
            "SW{}", PositionOption.DEFAULT, ZERO_POSITION, ""
        ),
        start_index: int = 1,
    ) -> wx.Sizer:
        layout_label = wx.StaticText(self, -1, self._("Keyboard layout file:"))
        layout_picker = get_file_picker(
            self,
            -1,
            wildcard="JSON files (*.json)|*.json|All files (*)|*",
            style=wx.FLP_USE_TEXTCTRL,
        )
        layout_picker.SetMinSize((400, -1))
        if layout_path:
            layout_picker.SetPath(layout_path)
            layout_picker.GetTextCtrl().SetInsertionPointEnd()

        key_distance_x = LabeledTextCtrl(
            self,
            wx_("Step X:"),
            value=str(key_distance[0]),
            width=5,
            validator=FloatValidator(),
            tooltip=self._(
                "How many millimeters 1U spans between switches horizontally"
            ),
        )

        key_distance_y = LabeledTextCtrl(
            self,
            wx_("Step Y:"),
            value=str(key_distance[1]),
            width=5,
            validator=FloatValidator(),
            tooltip=self._("How many millimeters 1U spans between switches vertically"),
        )

        key_annotation = LabeledTextCtrl(
            self,
            wx_("Footprint Annotation") + ":",
            element_info.annotation_format,
            validator=AnnotationValidator(),
        )

        key_start_index = LabeledTextCtrl(
            self,
            wx_("Start index") + ":",
            value=str(start_index),
            width=3,
            validator=IntValidator(),
            tooltip=self._("Starting index used to match footprint annotations"),
        )

        key_position = ElementPositionWidget(self, ZERO_POSITION, disable_offsets=True)
        if element_info.position:
            key_position.set_position(element_info.position)

        box = wx.StaticBox(self, label=self._("Switch settings"))
        sizer = wx.StaticBoxSizer(box, wx.VERTICAL)

        row1 = wx.BoxSizer(wx.HORIZONTAL)
        row1.Add(layout_label, 0, wx.LEFT | wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 5)
        row1.Add(layout_picker, 1, wx.ALL, 5)
        row1.Add(key_distance_x, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)
        row1.Add(key_distance_y, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)
        sizer.Add(row1, 0, wx.EXPAND | wx.ALL, 5)

        row2 = wx.BoxSizer(wx.HORIZONTAL)
        row2.Add(key_annotation, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)
        row2.Add(key_position, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)
        row2.Add(key_start_index, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)
        sizer.Add(row2, 0, wx.EXPAND | wx.ALL, 5)

        self.__layout_picker = layout_picker
        self.__key_distance_x = key_distance_x.text
        self.__key_distance_y = key_distance_y.text
        self.__key_annotation_format = key_annotation.text
        self.__key_position = key_position
        self.__key_start_index = key_start_index.text

        return sizer

    def get_switch_diodes_section(
        self,
        enable: bool = True,
        route_switches_with_diodes: bool = True,
        optimize_diodes_orientation: bool = False,
        element_info: ElementInfo = ElementInfo(
            "D{}", PositionOption.DEFAULT, DEFAULT_DIODE_POSITION, ""
        ),
    ) -> wx.Sizer:
        place_diodes_checkbox = wx.CheckBox(self, label=wx_("Allow autoplacement"))
        place_diodes_checkbox.SetValue(enable)
        place_diodes_checkbox.Bind(wx.EVT_CHECKBOX, self.on_diode_place_checkbox)

        switches_and_diodes_tracks_checkbox = wx.CheckBox(
            self, label=self._("Route with switches")
        )
        switches_and_diodes_tracks_checkbox.SetValue(route_switches_with_diodes)

        optimize_diodes_orientation_checkbox = wx.CheckBox(
            self, label=self._("Automatically adjust orientation")
        )
        optimize_diodes_orientation_checkbox.SetValue(optimize_diodes_orientation)
        optimize_diodes_orientation_checkbox.SetToolTip(
            self._(
                "Find optimal diode orientation for minimal distance between switch and diode common net pads"
            )
        )

        diode_settings = ElementSettingsWidget(
            self,
            element_info,
            default_position=DEFAULT_DIODE_POSITION,
        )

        box = wx.StaticBox(self, label=self._("Switch diodes settings"))
        sizer = wx.StaticBoxSizer(box, wx.VERTICAL)

        row1 = wx.BoxSizer(wx.HORIZONTAL)
        row1.Add(place_diodes_checkbox, 0, wx.ALL, 0)
        row1.Add(switches_and_diodes_tracks_checkbox, 0, wx.ALL, 0)
        row1.Add(optimize_diodes_orientation_checkbox, 0, wx.ALL, 0)

        sizer.Add(row1, 0, wx.EXPAND | wx.ALL, 5)
        # weird border value to make it aligned with 'additional_elements_section':
        sizer.Add(diode_settings, 0, wx.EXPAND | wx.ALL, 9)

        self.__place_diodes_checkbox = place_diodes_checkbox
        self.__switches_and_diodes_tracks_checkbox = switches_and_diodes_tracks_checkbox
        self.__optimize_diodes_orientation_checkbox = (
            optimize_diodes_orientation_checkbox
        )
        self.__diode_settings = diode_settings

        self.__enable_diode_settings(enable)

        return sizer

    def __enable_diode_settings(self, enable: bool) -> None:
        if enable:
            self.__diode_settings.Enable()
            self.__optimize_diodes_orientation_checkbox.Enable()
        else:
            self.__diode_settings.Disable()
            self.__optimize_diodes_orientation_checkbox.Disable()

    def on_diode_place_checkbox(self, event: wx.CommandEvent) -> None:
        is_checked = event.GetEventObject().IsChecked()
        self.__enable_diode_settings(is_checked)

    def get_additional_elements_section(
        self,
        elements_info: List[ElementInfo] = [
            ElementInfo("ST{}", PositionOption.CUSTOM, ZERO_POSITION, "")
        ],
    ) -> wx.Sizer:
        self.__additional_elements = []

        scrolled_window = wx.ScrolledWindow(self)
        scrolled_window_sizer = wx.BoxSizer(wx.VERTICAL)

        scrolled_window.SetSizer(scrolled_window_sizer)
        virtual_width, virtual_height = scrolled_window_sizer.GetMinSize()
        scrolled_window.SetVirtualSize((virtual_width, virtual_height))
        scrolled_window.SetScrollRate(0, 10)

        box = wx.StaticBox(self, label=self._("Additional elements settings"))
        sizer = wx.StaticBoxSizer(box, wx.VERTICAL)

        sizer.Add(scrolled_window, 1, wx.EXPAND | wx.ALL, 10)

        dialog_width, _ = self.GetSize()
        sizer.SetMinSize((dialog_width, 180))

        buttons_sizer = wx.BoxSizer(wx.HORIZONTAL)

        def add_element(element_info: ElementInfo) -> None:
            element_settings = ElementSettingsWidget(scrolled_window, element_info)
            self.__additional_elements.append(element_settings)
            scrolled_window_sizer.Add(element_settings, 0, wx.EXPAND | wx.ALIGN_LEFT, 0)
            self.GetTopLevelParent().Layout()

        def add_element_callback(_) -> None:
            add_element(ElementInfo("", PositionOption.CUSTOM, ZERO_POSITION, ""))

        for element_info in elements_info:
            add_element(element_info)

        add_icon = PyEmbeddedImage(
            b"iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAABHNCSVQICAgIfAhkiAAAACtJ"
            b"REFUOI1jYKAx+A/FOAETpTaMGsDAwAil8YY0Pv0Uu4AQGE0H9DCAYgAADfAFFDV6vY8AAAAA"
            b"SUVORK5CYII="
        ).GetBitmap()
        add_button = wx.BitmapButton(self, bitmap=add_icon)
        add_button.Bind(wx.EVT_BUTTON, add_element_callback)

        def remove_element(_) -> None:
            element_settings = (
                self.__additional_elements.pop() if self.__additional_elements else None
            )
            if element_settings:
                element_settings.Destroy()
                self.Layout()

        remove_icon = PyEmbeddedImage(
            b"iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAABHNCSVQICAgIfAhkiAAAABtJ"
            b"REFUOI1jYBgFwwAwQun/5OpnopZLRsGQBgBLTwEEpzJYVwAAAABJRU5ErkJggg=="
        ).GetBitmap()
        remove_button = wx.BitmapButton(self, bitmap=remove_icon)
        remove_button.Bind(wx.EVT_BUTTON, remove_element)

        buttons_sizer.Add(add_button, 0, wx.EXPAND | wx.ALL, 0)
        buttons_sizer.Add(remove_button, 0, wx.EXPAND | wx.ALL, 0)

        sizer.Add(buttons_sizer, 0, wx.EXPAND | wx.ALL, 5)

        return sizer

    def get_misc_section(
        self,
        route_rows_and_columns: bool = True,
        template_path: str = "",
        generate_outline: bool = False,
        outline_delta: float = 0.0,
    ) -> wx.Sizer:
        row_and_columns_tracks_checkbox = wx.CheckBox(
            self, label=self._("Route rows and columns")
        )
        row_and_columns_tracks_checkbox.SetValue(route_rows_and_columns)

        template_label = wx.StaticText(
            self, -1, self._("Controller circuit template file:")
        )
        template_picker = get_file_picker(
            self,
            -1,
            wildcard="KiCad printed circuit board files (*.kicad_pcb)|*.kicad_pcb",
            style=wx.FLP_USE_TEXTCTRL,
        )
        if template_path:
            template_picker.SetPath(template_path)
            template_picker.GetTextCtrl().SetInsertionPointEnd()

        row1 = wx.BoxSizer(wx.HORIZONTAL)
        row1.Add(row_and_columns_tracks_checkbox, 0, wx.EXPAND | wx.ALL, 5)
        row1.Add(wx.StaticLine(self, style=wx.LI_VERTICAL), 0, wx.EXPAND | wx.ALL, 5)
        row1.Add(template_label, 0, wx.LEFT | wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 5)
        row1.Add(template_picker, 1, wx.EXPAND | wx.ALL, 5)

        generate_outline_checkbox = wx.CheckBox(
            self, label=self._("Build board outline")
        )
        generate_outline_checkbox.SetValue(generate_outline)
        generate_outline_checkbox.Bind(
            wx.EVT_CHECKBOX, self.on_generate_outline_checkbox
        )
        outline_delta_ctrl = LabeledTextCtrl(
            self,
            self._("Outline delta:"),
            value=str(outline_delta),
            width=5,
            validator=FloatValidator(),
        )

        row2 = wx.BoxSizer(wx.HORIZONTAL)
        row2.Add(generate_outline_checkbox, 0, wx.EXPAND | wx.ALL, 5)
        row2.Add(wx.StaticLine(self, style=wx.LI_VERTICAL), 0, wx.EXPAND | wx.ALL, 5)
        row2.Add(outline_delta_ctrl, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 5)

        box = wx.StaticBox(self, label=self._("Other settings"))
        sizer = wx.StaticBoxSizer(box, wx.VERTICAL)
        sizer.Add(row1, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(row2, 0, wx.EXPAND | wx.ALL, 5)

        self.__rows_and_columns_tracks_checkbox = row_and_columns_tracks_checkbox
        self.__template_picker = template_picker
        self.__generate_outline_checkbox = generate_outline_checkbox
        self.__outline_delta_ctrl = outline_delta_ctrl

        self.__enable_outline_delta(generate_outline)

        return sizer

    def __enable_outline_delta(self, enable: bool) -> None:
        if enable:
            self.__outline_delta_ctrl.Enable()
        else:
            self.__outline_delta_ctrl.Disable()

    def on_generate_outline_checkbox(self, event: wx.CommandEvent) -> None:
        is_checked = event.GetEventObject().IsChecked()
        self.__enable_outline_delta(is_checked)

    def on_help_button(self, event: wx.CommandEvent) -> None:
        del event
        help_dialog = HelpDialog(self)
        help_dialog.ShowModal()
        help_dialog.Destroy()

    def get_layout_path(self) -> str:
        return self.__layout_picker.GetPath()

    def get_key_annotation_format(self) -> str:
        return self.__key_annotation_format.GetValue()

    def route_switches_with_diodes(self) -> bool:
        return self.__switches_and_diodes_tracks_checkbox.GetValue()

    def optimize_diodes_orientation(self) -> bool:
        return self.__optimize_diodes_orientation_checkbox.GetValue()

    def route_rows_and_columns(self) -> bool:
        return self.__rows_and_columns_tracks_checkbox.GetValue()

    def get_key_distance(self) -> Tuple[float, float]:
        x = float(self.__key_distance_x.GetValue())
        y = float(self.__key_distance_y.GetValue())
        return x, y

    def get_template_path(self) -> str:
        return self.__template_picker.GetPath()

    def get_key_info(self) -> ElementInfo:
        return ElementInfo(
            self.get_key_annotation_format(),
            PositionOption.DEFAULT,
            self.__key_position.GetValue(),
            "",
        )

    def enable_diode_placement(self) -> bool:
        return self.__place_diodes_checkbox.GetValue()

    def get_diode_info(self) -> ElementInfo:
        return self.__diode_settings.GetValue()

    def get_additional_elements_info(self) -> List[ElementInfo]:
        return [e.GetValue() for e in self.__additional_elements]

    def generate_outline(self) -> bool:
        return self.__generate_outline_checkbox.GetValue()

    def get_outline_delta(self) -> float:
        return float(self.__outline_delta_ctrl.text.GetValue())

    def get_window_state(self) -> WindowState:
        return WindowState(
            layout_path=self.get_layout_path(),
            key_distance=self.get_key_distance(),
            key_info=self.get_key_info(),
            enable_diode_placement=self.enable_diode_placement(),
            route_switches_with_diodes=self.route_switches_with_diodes(),
            optimize_diodes_orientation=self.optimize_diodes_orientation(),
            diode_info=self.get_diode_info(),
            additional_elements=self.get_additional_elements_info(),
            route_rows_and_columns=self.route_rows_and_columns(),
            template_path=self.get_template_path(),
            generate_outline=self.generate_outline(),
            outline_delta=self.get_outline_delta(),
            start_index=self.get_start_index(),
        )

    def get_start_index(self) -> int:
        try:
            return int(self.__key_start_index.GetValue())
        except Exception:
            return 1


def load_window_state_from_log(filepath: str) -> WindowState:
    try:
        with open(filepath, "r") as f:
            for line in f:
                if "GUI state:" in line:
                    state = WindowState.from_dict(json.loads(line[line.find("{") :]))
                    logger.info("Using window state found in previous log")
                    return state
    except Exception:
        # if something went wrong use default
        pass
    logger.warning("Failed to parse window state from log file, using default")
    return WindowState()


# used for tests
if __name__ == "__main__":
    import argparse

    from .dialog_helper import show_with_test_support
    from .kbplacer_plugin import run_from_gui

    parser = argparse.ArgumentParser(description="dialog test")
    parser.add_argument(
        "-i", "--initial-state-file", default="", help="Initial gui state file"
    )
    parser.add_argument(
        "-o", "--output-dir", required=True, help="Directory for output files"
    )
    parser.add_argument(
        "--run-without-dialog",
        required=False,
        action="store_true",
        help="Run with loaded state without displaying dialog window",
    )
    parser.add_argument(
        "-b",
        "--board",
        required=False,
        default="",
        help=".kicad_pcb file to be used with --run-without-dialog option",
    )
    args = parser.parse_args()

    initial_state = load_window_state_from_log(args.initial_state_file)
    if not args.run_without_dialog:
        dlg = show_with_test_support(
            KbplacerDialog, None, "kbplacer", initial_state=initial_state
        )

        with open(f"{args.output_dir}/window_state.json", "w") as f:
            f.write(f"{dlg.get_window_state()}")

        print("exit ok")
    else:
        import pcbnew

        board = run_from_gui(args.board, initial_state)
        pcbnew.Refresh()
        pcbnew.SaveBoard(args.board, board)
