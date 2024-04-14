import logging
import sys
from argparse import ArgumentTypeError
from contextlib import contextmanager
from typing import Dict, List
from unittest.mock import MagicMock, Mock, patch

import pytest

from kbplacer.__main__ import app
from kbplacer.defaults import DEFAULT_DIODE_POSITION, ZERO_POSITION
from kbplacer.element_position import ElementInfo, ElementPosition, PositionOption, Side
from kbplacer.kbplacer_plugin import PluginSettings

logger = logging.getLogger(__name__)


class ExitTest(Exception):
    pass


def get_default(board_path: str) -> PluginSettings:
    """Returns default run settings when using all default CLI values"""
    return PluginSettings(
        board_path=board_path,
        layout_path="",
        key_info=ElementInfo("SW{}", PositionOption.DEFAULT, ZERO_POSITION, ""),
        key_distance=(19.05, 19.05),
        diode_info=ElementInfo(
            "D{}", PositionOption.DEFAULT, DEFAULT_DIODE_POSITION, ""
        ),
        route_switches_with_diodes=False,  # this in True by default when using GUI
        route_rows_and_columns=False,  # same as above
        additional_elements=[
            ElementInfo("ST{}", PositionOption.CUSTOM, ZERO_POSITION, "")
        ],
        generate_outline=False,
        outline_delta=0.0,
        template_path="",
        create_from_annotated_layout=False,
        switch_footprint="",
        diode_footprint="",
    )


@pytest.fixture
def cli_isolation(monkeypatch):
    monkeypatch.setattr("kbplacer.__main__.pcbnew.Refresh", MagicMock())
    monkeypatch.setattr("kbplacer.__main__.pcbnew.SaveBoard", MagicMock())

    def mock_exit(*args, **kwargs):
        raise ExitTest(*args, **kwargs)

    monkeypatch.setattr("sys.exit", mock_exit)

    @contextmanager
    def _isolation(args: List):
        args.insert(0, "")
        with patch.object(sys, "argv", args):
            yield

    yield _isolation


@pytest.fixture
def fake_board(tmpdir) -> str:
    board_path = f"{tmpdir}/example.kicad_pcb"
    with open(board_path, "w") as f:
        # content not important, we just need file,
        # running actions on this file is mocked
        f.write("")
    return board_path


@contextmanager
def expects_settings(default_difference: Dict):
    # board_path must be set later, it depends on tmpdir
    settings = get_default("")
    for k, v in default_difference.items():
        settings.__setattr__(k, v)
    yield settings


@pytest.mark.parametrize(
    "extra_args,expectation",
    [
        # fmt: off
        # no extra args, expecting run with default options
        (
            [],
            expects_settings({}),
        ),
        # valid switch option values
        #   - valid when only annotation specified
        (
            ["--switch", "S{}"],
            expects_settings({"key_info": ElementInfo("S{}", PositionOption.DEFAULT, ZERO_POSITION, "")}),
        ),
        #   - valid with orientation and side
        (
            ["--switch", "S{} 90 BACK"],
            expects_settings({"key_info": ElementInfo("S{}", PositionOption.DEFAULT,
                                          ElementPosition(0, 0, 90, Side.BACK), "")}),
        ),
        # invalid switch option values
        #   - too many tokens
        (
            ["--switch", "SW{} DEFAULT 0 0 0 FRONT"],
            pytest.raises(ArgumentTypeError,
                match=r"--switch invalid format"
            ),
        ),
        #   - invalid side
        (
            ["--switch", "SW{} 0 NOT_A_SIDE"],
            pytest.raises(ArgumentTypeError,
                match=r"'NOT_A_SIDE' is not a valid Side"
            ),
        ),
        # valid diode option values
        #   - valid relative position setting
        (
            ["--diode", "D{} RELATIVE"],
            expects_settings({"diode_info": ElementInfo("D{}", PositionOption.RELATIVE, None, "")}),
        ),
        #   - valid relative position setting - it is case insensitive
        #     (it is not documented in --help, exist for convenience)
        (
            ["--diode", "D{} rElaTIve"],
            expects_settings({"diode_info": ElementInfo("D{}", PositionOption.RELATIVE, None, "")}),
        ),
        #   - valid relative position setting with destination template save path
        (
            ["--diode", "D{} RELATIVE /path/to/save.kicad_pcb"],
            expects_settings({"diode_info": ElementInfo("D{}", PositionOption.RELATIVE, None,
                                                        "/path/to/save.kicad_pcb")}),
        ),
        #   - valid preset with path (CLI does not check if file exist, this is done later)
        (
            ["--diode", "D{} PRESET /path/to/load.kicad_pcb"],
            expects_settings({"diode_info": ElementInfo("D{}", PositionOption.PRESET, None,
                                                        "/path/to/load.kicad_pcb")}),
        ),
        #   - valid custom position setting
        (
            ["--diode", "DIODE{} CUSTOM 1.5 -2.05 180.0 FRONT"],
            expects_settings({"diode_info": ElementInfo("DIODE{}", PositionOption.CUSTOM,
                                            ElementPosition(1.5, -2.05, 180.0, Side.FRONT), "")}),
        ),
        #   - valid custom position setting with side lowercase
        (
            ["--diode", "DIODE{} CUSTOM 1.5 -2.05 180.0 front"],
            expects_settings({"diode_info": ElementInfo("DIODE{}", PositionOption.CUSTOM,
                                            ElementPosition(1.5, -2.05, 180.0, Side.FRONT), "")}),
        ),
        # invalid diode option values
        #   - invalid position
        (
            ["--diode", "D{} NO_SUCH_OPTION"],
            pytest.raises(ArgumentTypeError,
                match=r"'NO_SUCH_OPTION' is not a valid PositionOption"
            ),
        ),
        #   - too little tokens
        (
            ["--diode", "D{}"],
            pytest.raises(ArgumentTypeError,
                match=r"--diode invalid format"
            ),
        ),
        #   - too many tokens
        (
            ["--diode", "D{} CUSTOM 0 0 0 FRONT 90"],
            pytest.raises(ArgumentTypeError,
                match=r"--diode invalid format"
            ),
        ),
        #   - invalid float numbers
        (
            ["--diode", "D{} CUSTOM 0 --10 0 FRONT"],
            pytest.raises(ArgumentTypeError,
                          match=r"could not convert string to float: '--10'"
            ),
        ),
        #   - annotation without placeholder
        (
            ["--diode", "D CUSTOM 0 0 0 FRONT"],
            pytest.raises(ArgumentTypeError,
                match=r"'D' invalid annotation specifier"
            ),
        ),
        #   - valid option with missing details
        (
            ["--diode", "D{} CUSTOM"],
            pytest.raises(ArgumentTypeError,
                match=r"needs to be equal RELATIVE or DEFAULT if position details not provided"
            ),
        ),
        #   - valid option with incomplete details
        #      '0' would be interpreted as template path, making CUSTOM illegal choice
        (
            ["--diode", "D{} CUSTOM 0"],
            pytest.raises(ArgumentTypeError,
                match=r"needs to be equal RELATIVE or PRESET when providing template path"
            ),
        ),
        #   - details with wrong option
        (
            ["--diode", "D{} PRESET 0 0 0 FRONT"],
            pytest.raises(ArgumentTypeError,
                match=r"needs to be equal CUSTOM when providing position details"
            ),
        ),
        # valid additional elements option values
        #   - valid relative position setting
        (
            ["--additional-elements", "LED{} RELATIVE;ST{} CUSTOM 0 0 0 FRONT"],
            expects_settings({"additional_elements": [
                ElementInfo("LED{}", PositionOption.RELATIVE, None, ""),
                ElementInfo("ST{}", PositionOption.CUSTOM, ZERO_POSITION, ""),
            ]}),
        ),
        # invalid additional elements option values
        #   - wrong separator
        (
            ["--additional-elements", "LED{} RELATIVE:ST{} CUSTOM 0 0 0 FRONT"],
            pytest.raises(ArgumentTypeError,
                match=r"--additional-elements invalid format."
            ),
        ),
        #   - using DEFAULT position
        (
            ["--additional-elements", "LED{} DEFAULT"],
            pytest.raises(ArgumentTypeError,
                match=r"--additional-elements does not support DEFAULT position"
            ),
        ),
        # valid key-distance option values
        #   - integers
        (
            ["--key-distance", "18 18"],
            expects_settings({"key_distance": (18, 18)}),
        ),
        #   - floats
        (
            ["--key-distance", "18.05 19.05"],
            expects_settings({"key_distance": (18.05, 19.05)}),
        ),
        # invalid key-distance option values
        #   - wrong separator # TODO: error message could be better
        (
            ["--key-distance", "18,18"],
            pytest.raises(ArgumentTypeError,
                match=r"could not convert string to float: '18,18'"
            ),
        ),
        #   - too many tokens
        (
            ["--key-distance", "18 18 18"],
            pytest.raises(ArgumentTypeError,
                match=r"--key-distance must be exactly two numeric values separated by a space."
            ),
        ),
        # some more complex scenarios combining multiple options:
        (
            ["--key-distance", "18 18.05", "--diode", "DIODE{} CUSTOM 1.5 -2.05 180.0 FRONT",
             "--template", "/some/path", "--route-switches-with-diodes", "--route-rows-and-columns"],
            expects_settings({"diode_info": ElementInfo("DIODE{}", PositionOption.CUSTOM,
                                            ElementPosition(1.5, -2.05, 180.0, Side.FRONT), ""),
                              "key_distance": (18, 18.05),
                              "template_path": "/some/path",
                              "route_switches_with_diodes": True,
                              "route_rows_and_columns": True,
                              }),
        ),
        # fmt: on
    ],
)
def test_cli_arguments(
    monkeypatch, cli_isolation, fake_board, extra_args, expectation
) -> None:
    run_mock = Mock()
    monkeypatch.setattr("kbplacer.__main__.run", run_mock)

    args = ["--board", fake_board] + extra_args
    with cli_isolation(args):
        with expectation as s:
            app()

        if isinstance(s, PluginSettings):
            s.board_path = fake_board
            run_mock.assert_called_once_with(s)
        else:
            run_mock.assert_not_called()


def test_board_creation_when_exist(
    caplog, monkeypatch, cli_isolation, fake_board
) -> None:
    run_mock = Mock()
    monkeypatch.setattr("kbplacer.__main__.run", run_mock)

    args = ["--board", fake_board, "--create-from-annotated-layout"]
    with cli_isolation(args):
        with pytest.raises(ExitTest):
            app()

    run_mock.assert_not_called()
    assert caplog.records[0].message == f"File {fake_board} already exist, aborting"
