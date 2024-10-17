import copy
import ctypes
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import asdict
from typing import List

import pytest
import wx
from PIL import ImageGrab
from pyvirtualdisplay.smartdisplay import DisplayTimeoutError, SmartDisplay

from kbplacer.defaults import ZERO_POSITION
from kbplacer.element_position import ElementInfo, ElementPosition, PositionOption, Side
from kbplacer.kbplacer_dialog import (
    WindowState,
    load_window_state_from_log,
)

if sys.platform == "linux":
    import Xlib.XK
    from Xlib import X
    from Xlib.display import Display
    from Xlib.ext.xtest import fake_input

if sys.platform == "win32":
    from ctypes.wintypes import DWORD, HWND, RECT

logger = logging.getLogger(__name__)

WX_VERSION = tuple(map(int, wx.__version__.split(".")))
STATE_RESTORED_LOG = "Using window state found in previous log"
STATE_DEFAULT_LOG = "Failed to parse window state from log file, using default"

DEFAULT_WINDOW_STATE = WindowState()
CUSTOM_WINDOW_STATE_EXAMPLE1 = WindowState(
    layout_path="/home/user/kle.json",
    key_distance=(18, 18),
    key_info=ElementInfo(
        annotation_format="KEY{}",
        position_option=PositionOption.DEFAULT,
        position=ElementPosition(
            x=0.0,
            y=0.0,
            orientation=90.0,
            side=Side.BACK,
        ),
        template_path="",
    ),
    enable_diode_placement=False,
    route_switches_with_diodes=False,
    diode_info=ElementInfo(
        annotation_format="D{}",
        position_option=PositionOption.CUSTOM,
        position=ElementPosition(
            x=-5.0,
            y=5.5,
            orientation=180.0,
            side=Side.FRONT,
        ),
        template_path="",
    ),
    additional_elements=[
        ElementInfo(
            annotation_format="ST{}",
            position_option=PositionOption.CUSTOM,
            position=ElementPosition(
                x=0.0,
                y=-5.0,
                orientation=0.0,
                side=Side.FRONT,
            ),
            template_path="",
        ),
        ElementInfo(
            annotation_format="LED{}",
            position_option=PositionOption.RELATIVE,
            position=None,
            template_path="/home/user/led_template.kicad_pcb",
        ),
    ],
    route_rows_and_columns=False,
    template_path="/home/user/template.kicad_pcb",
    generate_outline=True,
    outline_delta=1.5,
)


class LinuxVirtualScreenManager:
    def __enter__(self):
        self.display = SmartDisplay(backend="xvfb", size=(960, 640))
        self.display.start()
        return self

    def __exit__(self, *exc):
        self.display.stop()
        return False

    def screenshot(self, window_name, path) -> bool:
        try:
            img = self.display.waitgrab(timeout=5)
            img.save(path)
            return True
        except DisplayTimeoutError as err:
            logger.error(err)
            return False


class HostScreenManager:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def screenshot(self, window_name, path):
        try:
            time.sleep(1)
            window_handle = find_window(window_name)
            window_rect = get_window_position(window_handle)
            img = ImageGrab.grab()
            if window_rect:
                img = img.crop(window_rect)
            img.save(path)
            return True
        except Exception as err:
            logger.error(err)
            return False


def find_window(name):
    if sys.platform != "win32":
        return None
    user32 = ctypes.windll.user32
    return user32.FindWindowW(None, name)


def get_window_position(window_handle):
    if sys.platform != "win32":
        return None
    dwmapi = ctypes.windll.dwmapi
    # based on https://stackoverflow.com/a/67137723
    rect = RECT()
    DMWA_EXTENDED_FRAME_BOUNDS = 9
    dwmapi.DwmGetWindowAttribute(
        HWND(window_handle),
        DWORD(DMWA_EXTENDED_FRAME_BOUNDS),
        ctypes.byref(rect),
        ctypes.sizeof(rect),
    )
    return (rect.left, rect.top, rect.right, rect.bottom)


def run_process(args, package_path):
    env = os.environ.copy()
    return subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.PIPE,
        text=True,
        cwd=package_path,
        env=env,
    )


def is_xvfb_avaiable() -> bool:
    try:
        p = subprocess.Popen(
            ["Xvfb", "-help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
        )
        _, _ = p.communicate()
        exit_code = p.returncode
        return exit_code == 0
    except FileNotFoundError:
        logger.warning("Xvfb was not found")
    return False


@pytest.fixture
def screen_manager():
    if sys.platform == "linux":
        if is_xvfb_avaiable():
            return LinuxVirtualScreenManager()
        else:
            return HostScreenManager()
    elif sys.platform == "win32":
        return HostScreenManager()
    else:
        pytest.skip(f"Platform '{sys.platform}' is not supported")


def run_gui_test(
    tmpdir, screen_manager, window_name, gui_callback, *, input_callback=None
) -> None:
    if input_callback:
        assert isinstance(
            screen_manager, LinuxVirtualScreenManager
        ), "input_callback not supported for current configuration"

    is_ok = False
    # for some reason, it occasionally may fail with
    # 'wxEntryStart failed, unable to initialize wxWidgets!' error, most likely
    # this is not related with plugin's code - try to get screenshot 3 times
    # to limit false positives
    max_attempts = 3
    for i in range(0, max_attempts):
        with screen_manager as mgr:
            p = gui_callback()

            if input_callback:
                is_ok = input_callback(mgr)
            else:
                is_ok = mgr.screenshot(window_name, f"{tmpdir}/report/screenshot.png")

            try:
                outs, errs = p.communicate("q\n", timeout=1)
            except subprocess.TimeoutExpired:
                logger.error("Process timeout expired")
                p.kill()
                outs, errs = p.communicate()

            logger.info(f"Process stdout: {outs}")
            logger.debug(f"Process stderr: {errs}")

            # here we used to check if stderr is empty but on some occasions
            # (linux only) it would contain `AssertionError: assert 'double free'`
            # or similar even though dialog opened correctly.
            # This probably is related to test harness (running GUI in Xvfb
            # virtual buffer) and not to tested code defect.
            # Decided to skip stderr check.
            # If gui fails to open then screenshot function of pyvirtualdisplay
            # would return 'screenshot is empty' which can be verified by swapping
            # order of gui_callback and screenshot calls.

            if is_ok:
                break
            else:
                logger.info(f"Failed to get screenshot, attempt {i+1}/{max_attempts}")

    assert is_ok


def test_gui_default_state(tmpdir, package_path, package_name, screen_manager) -> None:
    def _callback():
        return run_process(
            [
                "python3",
                "-m",
                f"{package_name}.kbplacer_dialog",
                "-o",
                tmpdir,
            ],
            package_path,
        )

    run_gui_test(tmpdir, screen_manager, "kbplacer", _callback)
    with open(f"{tmpdir}/window_state.json", "r") as f:
        state = WindowState.from_dict(json.load(f))
        # state not explicitly restored should result in default state:
        assert state == DEFAULT_WINDOW_STATE


def test_help_dialog(tmpdir, package_path, package_name, screen_manager) -> None:
    def _callback():
        return run_process(
            ["python3", "-m", f"{package_name}.help_dialog"], package_path
        )

    run_gui_test(tmpdir, screen_manager, "kbplacer help", _callback)


def test_error_dialog(tmpdir, package_path, package_name, screen_manager) -> None:
    def _callback():
        return run_process(
            ["python3", "-m", f"{package_name}.error_dialog"], package_path
        )

    run_gui_test(tmpdir, screen_manager, "kbplacer error", _callback)


def merge_dicts(dict1, dict2):
    for key, val in dict2.items():
        if key not in dict1:
            dict1[key] = val
            continue

        if isinstance(val, dict):
            merge_dicts(dict1[key], val)
        else:
            dict1[key] = val
    return dict1


def get_state_data(state: dict, name: str):
    input_state = copy.deepcopy(asdict(DEFAULT_WINDOW_STATE))
    input_state = merge_dicts(input_state, state)
    input_state = WindowState.from_dict(input_state)
    return pytest.param(input_state, id=name)


@pytest.mark.parametrize(
    "state",
    [
        # fmt: off
        get_state_data({"key_info": {
                "annotation_format": "KEY{}",
                "position_option": "Default",
                "position": {
                    "x": 0,
                    "y": 0,
                    "orientation": 90,
                    "side": "Back"
                },
                "template_path": ""
            }
        }, "non-default-key-annotation-and-position"),
        get_state_data({"diode_info": {
                "position_option": "Preset",
                "position": None,
                "template_path": "/example/preset/path.kicad_pcb"
            }
        }, "diode-position-preset"),
        get_state_data({"key_distance": (18, 18.01)}, "non-default-key-distance"),
        get_state_data({"additional_elements": []}, "no-additional-elements"),
        get_state_data(asdict(CUSTOM_WINDOW_STATE_EXAMPLE1), "custom-state-1"),
        # fmt: on
    ],
)
def test_gui_state_restore(
    state, tmpdir, package_path, package_name, screen_manager
) -> None:
    def _callback():
        return run_process(
            [
                "python3",
                "-m",
                f"{package_name}.kbplacer_dialog",
                "-i",
                f"{tmpdir}/input_state.log",
                "-o",
                tmpdir,
            ],
            package_path,
        )

    with open(f"{tmpdir}/input_state.log", "w") as f:
        f.write(f"GUI state: {state}")
    run_gui_test(tmpdir, screen_manager, "kbplacer", _callback)
    with open(f"{tmpdir}/window_state.json", "r") as f:
        output_state = WindowState.from_dict(json.load(f))
        assert state == output_state


@pytest.fixture
def log_file(tmpdir):
    def _create_log_file(content) -> str:
        logfile = tmpdir.join("kbplacer.log")
        logfile.write(content)
        return str(logfile)

    return _create_log_file


@pytest.mark.parametrize(
    "input_state",
    [DEFAULT_WINDOW_STATE, CUSTOM_WINDOW_STATE_EXAMPLE1],
)
def test_load_window_state_from_log(caplog, log_file, input_state: WindowState) -> None:
    logfile_path = log_file(f"GUI state: {input_state}")
    state = load_window_state_from_log(logfile_path)
    assert state == input_state
    assert len(caplog.records) == 1
    assert caplog.records[0].message == STATE_RESTORED_LOG


@pytest.mark.parametrize(
    "input_state",
    [
        "Not a valid log line",
        "GUI state: valid-line-invalid-state",
        'GUI state {"invalid": "dict"}',
    ],
)
def test_load_window_state_from_corrupted_log(
    caplog, log_file, input_state: str
) -> None:
    logfile_path = log_file(input_state)
    state = load_window_state_from_log(logfile_path)
    assert state == DEFAULT_WINDOW_STATE
    assert caplog.records[0].message == STATE_DEFAULT_LOG


def test_load_window_state_from_missing_log(caplog) -> None:
    state = load_window_state_from_log("")
    assert state == DEFAULT_WINDOW_STATE
    assert len(caplog.records) == 1
    assert caplog.records[0].message == STATE_DEFAULT_LOG


class TestGuiSimulatedUserInput:
    TABS_TO_FIELD_FOR_DEFAULT_STATE = {
        "LAYOUT_TEXTCTRL": 1,
        "LAYOUT_BROWSE_BUTTON": 2,
        "STEP_X_TEXTCTRL": 3,
        "STEP_Y_TEXTCTRL": 4,
        "SWITCH_ANNOTATION_TEXTCTRL": 5,
        "SWITCH_ORIENTATION_TEXTCTRL": 6,
        "SWITCH_SIDE_RADIO": 7,
        "DIODE_PLACEMENT_CHECKBOX": 8,
        "DIODE_ROUTE_CHECKBOX": 9,
        "DIODE_ANNOTATION_TEXTCTRL": 10,
        "DIODE_POSITION_TEXTCTRL": 11,
        "DIODE_POSITION_DROPDOWN": 12,
        "ELEMENT1_ANNOTATION_TEXTCTRL": 13,
        "ELEMENT1_POSITION_TEXTCTRL": 14,
        "ELEMENT1_POSITION_DROPDOWN": 15,
        "ELEMENT1_OFFSET_X_TEXTCTRL": 16,
        "ELEMENT1_OFFSET_Y_TEXTCTRL": 17,
        "ELEMENT1_ORIENTATION_TEXTCTRL": 18,
        "ELEMENT1_SIDE_RADIO": 19,
        "ADD_ELEMENT_BUTTON": 20,
        "REMOVE_ELEMENT_BUTTON": 21,
        "ROUTE_ROWS_AND_COLUMNS_CHECKBOX": 22,
        "CONTROLLER_LAYOUT_TEXTCTRL": 23,
        "CONTROLLER_LAYOUT_BUTTON": 24,
        "BOARD_OUTLINE_CHECKBOX": 25,
        "HELP_BUTTON": 26,
        "CANCEL_BUTTON": 27,
        "OK_BUTTON": 28,
    }

    @pytest.fixture(autouse=True)
    def check_conditions(self, screen_manager):
        if not isinstance(screen_manager, LinuxVirtualScreenManager):
            pytest.skip("unsupported configuration")

    def write_keys(self, display: Display, keys: List[str]) -> None:
        for k in keys:
            keysym = display.keysym_to_keycode(Xlib.XK.string_to_keysym(k))
            fake_input(display, X.KeyPress, keysym)
            display.sync()
            fake_input(display, X.KeyRelease, keysym)
            display.sync()

    def navigate_to(self, display: Display, field: str) -> None:
        number_of_tabs = self.TABS_TO_FIELD_FOR_DEFAULT_STATE[field]
        if WX_VERSION <= (4, 0, 7):
            number_of_tabs += 2
        self.write_keys(display, number_of_tabs * ["Tab"])

    def display(self, screen_manager) -> Display:
        display_str = screen_manager.display.new_display_var
        logger.info(f"Virtual screen on: {display_str}")
        d = Display(display_str)
        time.sleep(2)
        return d

    @pytest.fixture()
    def gui_callback(self, tmpdir, package_name, package_path):
        def _gui_callback():
            return run_process(
                [
                    "python3",
                    "-m",
                    f"{package_name}.kbplacer_dialog",
                    "-o",
                    tmpdir,
                ],
                package_path,
            )
        return _gui_callback

    def assert_window_state(self, tmpdir, expected: WindowState) -> None:
        with open(f"{tmpdir}/window_state.json", "r") as f:
            output_state = WindowState.from_dict(json.load(f))
            logger.info(f"output_state: {output_state}")
        assert output_state == expected

    def test_gui_user_float_input(
        self, tmpdir, gui_callback, screen_manager
    ) -> None:
        """This tests two things, first it ensures that Tab key field navigation workspace
        as expected, second it test if float validated input text does ignore some characters
        and correctly handles the others
        """
        def _input_callback(mgr) -> bool:
            display = self.display(mgr)
            self.navigate_to(display, "STEP_Y_TEXTCTRL")
            self.write_keys(
                display,
                [
                    "a",
                    "1",
                    "8",
                    "plus",
                    "period",
                    "period",
                    "minus",
                    "b",
                    "5",
                    "BackSpace",
                    "9",
                    "Left",
                    "5",
                    "Left",
                    "Left",
                    "Left",
                    "Left",
                    "minus",
                    "minus",
                ],
            )
            return mgr.screenshot("kbplacer", f"{tmpdir}/report/screenshot.png")

        run_gui_test(
            tmpdir,
            screen_manager,
            "kbplacer",
            gui_callback,
            input_callback=_input_callback,
        )
        expected = copy.deepcopy(DEFAULT_WINDOW_STATE)
        expected.key_distance = (19.05, -18.59)
        self.assert_window_state(tmpdir, expected)

    def test_gui_add_remove_additional_elements(
        self, tmpdir, gui_callback, screen_manager
    ) -> None:
        def _input_callback(mgr) -> bool:
            display = self.display(mgr)
            self.navigate_to(display, "ADD_ELEMENT_BUTTON")
            self.write_keys(
                display,
                [
                    "Return",
                    "Return",
                    "Tab", # navigate to remove element
                    "Return",
                ],
            )
            return mgr.screenshot("kbplacer", f"{tmpdir}/report/screenshot.png")

        run_gui_test(
            tmpdir,
            screen_manager,
            "kbplacer",
            gui_callback,
            input_callback=_input_callback,
        )
        expected = copy.deepcopy(DEFAULT_WINDOW_STATE)
        expected.additional_elements.append(ElementInfo("", PositionOption.CUSTOM, ZERO_POSITION, ""))
        self.assert_window_state(tmpdir, expected)

    def test_gui_remove_additional_elements(
        self, tmpdir, gui_callback, screen_manager
    ) -> None:
        def _input_callback(mgr) -> bool:
            display = self.display(mgr)
            self.navigate_to(display, "REMOVE_ELEMENT_BUTTON")
            self.write_keys(
                display,
                [
                    "Return",
                    "Return",
                    "Return",
                ],
            )
            return mgr.screenshot("kbplacer", f"{tmpdir}/report/screenshot.png")

        run_gui_test(
            tmpdir,
            screen_manager,
            "kbplacer",
            gui_callback,
            input_callback=_input_callback,
        )
        expected = copy.deepcopy(DEFAULT_WINDOW_STATE)
        expected.additional_elements = []
        self.assert_window_state(tmpdir, expected)

    def test_gui_ok_button(
        self, tmpdir, gui_callback, screen_manager
    ) -> None:
        def _input_callback(mgr) -> bool:
            display = self.display(mgr)
            self.navigate_to(display, "OK_BUTTON")
            is_ok = mgr.screenshot("kbplacer", f"{tmpdir}/report/screenshot.png")
            self.write_keys(
                display,
                [
                    "Return",
                ],
            )
            return is_ok

        run_gui_test(
            tmpdir,
            screen_manager,
            "kbplacer",
            gui_callback,
            input_callback=_input_callback,
        )
        expected = copy.deepcopy(DEFAULT_WINDOW_STATE)
        self.assert_window_state(tmpdir, expected)
