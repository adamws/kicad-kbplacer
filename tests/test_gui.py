import copy
import json
import logging
import os
import re
import subprocess
from dataclasses import asdict

import pytest
import wx

from kbplacer.element_position import ElementInfo, ElementPosition, PositionOption, Side
from kbplacer.kbplacer_dialog import (
    AnnotationValidator,
    FloatValidator,
    WindowState,
    load_window_state_from_log,
)

from .conftest import get_screen_manager

logger = logging.getLogger(__name__)

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


def run_gui_test(tmpdir, screen_manager, window_name, gui_callback) -> None:
    is_ok = True
    # for some reason, it occasionally may fail with
    # 'wxEntryStart failed, unable to initialize wxWidgets!' error, most likely
    # this is not related with plugin's code - try to get screenshot 3 times
    # to limit false positives
    max_attempts = 3
    for i in range(0, max_attempts):
        with screen_manager as mgr:
            p = gui_callback()

            is_ok = mgr.screenshot(window_name, f"{tmpdir}/report/screenshot.png")
            try:
                outs, errs = p.communicate("q\n", timeout=1)
            except subprocess.TimeoutExpired:
                logger.error("Process timeout expired")
                p.kill()
                outs, errs = p.communicate()

            logger.info(f"Process stdout: {outs}")
            logger.info(f"Process stderr: {errs}")

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


@pytest.fixture(scope="class")
def validator_screen_manager():
    with get_screen_manager():
        app = wx.App()
        yield
        app.Destroy()


@pytest.mark.usefixtures("validator_screen_manager")
class TestValidators:

    VALID_INTS = [
        "0",
        "42",
        "-42",
        "+42",
        "999999",
    ]
    VALID_FLOATS = [
        "0.0",
        "123.456",
        "-1.23",
        "+0.5",
        ".75",
        "-.999",
        "+.001",
        "1e3",  # scientific notation (supported)
        "-2e-2",
    ]
    INVALID_FLOAT_INPUTS = [
        "abc",  # non-numeric
        "12a",  # mixed
        "++1",  # double sign
        "--1",
        "1..2",  # multiple dots
        "1.2.3",
        "0x123",  # hex-like
        "1e3.5",  # malformed scientific notation
        "",  # empty string
        " ",  # whitespace
        ".",  # standalone dot
        "-",  # standalone minus
        "+",  # standalone plus
    ]
    VALID_ANNOTATIONS = [
        "SW{}",
        "{}SW",
        "SW {}",
        "SW_{}",
        "SW_{}_a",
    ]
    INVALID_ANNOTATIONS = [
        "SW",
        "SW{",
        "SW{}{}",
        "{}",
        "  {}",
    ]

    @pytest.fixture
    def frame(self):
        frame = wx.Frame(None)
        yield frame
        frame.Destroy()

    @pytest.fixture
    def float_ctrl(self, frame):
        ctrl = wx.TextCtrl(frame, validator=FloatValidator(), name="TestFloat")
        frame.Show()
        return ctrl

    @pytest.fixture
    def annotation_ctrl(self, frame):
        ctrl = wx.TextCtrl(
            frame, validator=AnnotationValidator(), name="TestAnnotation"
        )
        frame.Show()
        return ctrl

    def valid(self, ctrl, monkeypatch, text):
        call_count = {"count": 0}

        def fake_messagebox(msg, caption, *args, **kwargs):
            call_count["count"] += 1
            return wx.OK

        monkeypatch.setattr(wx, "MessageBox", fake_messagebox)

        ctrl.SetValue(text)
        assert ctrl.GetValidator().Validate(ctrl.GetParent() or ctrl)
        assert call_count["count"] == 0

    @pytest.mark.parametrize("text", VALID_FLOATS + VALID_INTS)
    def test_valid_float(self, float_ctrl, monkeypatch, text):
        self.valid(float_ctrl, monkeypatch, text)

    @pytest.mark.parametrize("text", VALID_ANNOTATIONS)
    def test_valid_annotation(self, annotation_ctrl, monkeypatch, text):
        self.valid(annotation_ctrl, monkeypatch, text)

    def invalid(self, ctrl, monkeypatch, text, expected_err):
        captured = {}

        def fake_messagebox(msg, caption, *args, **kwargs):
            captured["msg"] = msg
            captured["caption"] = caption
            return wx.OK

        monkeypatch.setattr(wx, "MessageBox", fake_messagebox)

        ctrl.SetValue(text)
        assert not ctrl.GetValidator().Validate(ctrl.GetParent() or ctrl)
        assert captured["caption"] == "Error"
        assert re.match(expected_err, captured["msg"])

    @pytest.mark.parametrize("text", INVALID_FLOAT_INPUTS)
    def test_invalid_float(self, float_ctrl, monkeypatch, text):
        expected_err = r"Invalid 'TestFloat' value: '.*' is not a number!"
        self.invalid(float_ctrl, monkeypatch, text, expected_err)

    @pytest.mark.parametrize("text", INVALID_ANNOTATIONS)
    def test_invalid_annotation(self, annotation_ctrl, monkeypatch, text):
        expected_err = (
            r"Invalid 'TestAnnotation' value. Annotation must have exactly one "
            "'{}' placeholder, and it must be a part of non-whitespace content. "
            "Received: '.*'"
        )
        self.invalid(annotation_ctrl, monkeypatch, text, expected_err)
