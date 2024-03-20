from __future__ import annotations

import difflib
import glob
import logging
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path
from typing import cast

import pcbnew
import pytest
from xmldiff import actions, main

from .conftest import (
    KICAD_VERSION,
    add_track,
    generate_drc,
    generate_render,
    get_footprints_dir,
    get_references_dir,
    pointMM,
    rotate,
)

logger = logging.getLogger(__name__)


@pytest.fixture
def kbplacer_process(
    package_path,
    package_name,
):
    def _process(
        route,
        diode_position,
        layout_file,
        pcb_path,
        flags: list[str] = [],
        args: dict[str, str] = {},
    ):
        kbplacer_args = [
            "python3",
            "-m",
            package_name,
            "-b",
            pcb_path,
        ]
        if layout_file:
            kbplacer_args.append("-l")
            kbplacer_args.append(layout_file)
        if route:
            kbplacer_args.append("--route-switches-with-diodes")
            kbplacer_args.append("--route-rows-and-columns")
        if diode_position:
            kbplacer_args.append("--diode")
            kbplacer_args.append(diode_position)
        for v in flags:
            kbplacer_args.append(v)
        for k, v in args.items():
            kbplacer_args.append(k)
            kbplacer_args.append(v)

        p = subprocess.Popen(
            kbplacer_args,
            cwd=package_path,
        )
        p.communicate()
        if p.returncode != 0:
            raise Exception("Switch placement failed")

    return _process


def assert_group(expected: ET.Element, actual: ET.Element):
    expected_str = ET.tostring(expected).decode()
    actual_str = ET.tostring(actual).decode()

    edit_script = None
    try:
        edit_script = main.diff_texts(
            expected_str, actual_str, diff_options={"F": 0, "ratio_mode": "accurate"}
        )
    except Exception as e:
        logger.warning(f"Running diff on xml failed: {e}")
        diff = difflib.unified_diff(expected_str.splitlines(), actual_str.splitlines())
        for d in diff:
            logger.info(d)
        assert False, "Difference probably found"

    if edit_script and any(type(node) != actions.MoveNode for node in edit_script):
        logger.info("Difference found")
        diff = difflib.unified_diff(expected_str.splitlines(), actual_str.splitlines())
        for d in diff:
            logger.info(d)

        logger.info("Evaluating rules exceptions")
        differences = [node for node in edit_script if type(node) != actions.MoveNode]

        for node in list(differences):
            logger.info(f"Action node: {node}")
            if type(node) == actions.UpdateAttrib and node.name == "textLength":
                # let 'textLength' attributes to differ:
                logger.info("'textLength' attribute is allowed to be different")
                differences.remove(node)

        assert not differences, "Not allowed differences found"
    else:
        logger.info("No differences found")


def assert_kicad_svg(expected: Path, actual: Path):
    ns = {"svg": "http://www.w3.org/2000/svg"}
    expected_root = ET.parse(expected).getroot()
    expected_groups = expected_root.findall("svg:g", ns)

    actual_root = ET.parse(actual).getroot()
    actual_groups = actual_root.findall("svg:g", ns)

    assert len(expected_groups) == len(actual_groups)

    if KICAD_VERSION < (8, 0, 0):
        number_of_groups = len(expected_groups)
        for i in range(0, number_of_groups):
            logger.info(
                f"Analyzing {expected.name} file, group {i+1}/{number_of_groups}"
            )
            assert_group(expected_groups[i], actual_groups[i])
    else:
        # svgs produced by KiCad 8 have less nested groups, for example circle
        # elements are not grouped together, in order to re-use existing comparison
        # logic (used for KiCad 6 & 7) we need to wrap everything with additional
        # parent group:
        expected_parent_group = ET.Element("g", ns)
        actual_parent_group = ET.Element("g", ns)

        for element in expected_groups:
            expected_parent_group.append(element)
        for element in actual_groups:
            actual_parent_group.append(element)

        logger.info(f"Analyzing {expected.name} file")
        assert_group(expected_parent_group, actual_parent_group)


def assert_example(tmpdir, references_dir: Path) -> None:
    reference_files = get_reference_files(references_dir)
    assert len(reference_files) == 4, "Reference files not found"
    for path in reference_files:
        assert_kicad_svg(path, Path(f"{tmpdir}/{path.name}"))


def __get_parameters():
    examples = ["2x2", "3x2-sizes", "2x3-rotations", "1x4-rotations-90-step"]
    route_options = {"NoTracks": False, "Tracks": True}
    diode_options = {"DefaultDiode": None, "DiodeOption1": "D{} CUSTOM 0 4.5 0 BACK"}
    layout_options = {"RAW": "kle.json", "RAW_ANNOTATED": "kle-annotated.json"}
    test_params = []
    for example in examples:
        for route_option_name, route_option in route_options.items():
            for diode_option_name, diode_option in diode_options.items():
                for layout_option_name, layout_option in layout_options.items():
                    test_id = (
                        f"{example};{route_option_name};"
                        f"{diode_option_name};{layout_option_name}"
                    )
                    param = pytest.param(
                        example,
                        (route_option_name, route_option),
                        (diode_option_name, diode_option),
                        layout_option,
                        id=test_id,
                    )
                    test_params.append(param)

    # this special examples can't be used with all option combinations, appended here:
    for layout_option_name, layout_option in layout_options.items():
        test_id = (
            f"2x3-rotations-custom-diode-with-track;"
            f"Tracks;DiodeOption2;{layout_option_name}"
        )
        param = pytest.param(
            "2x3-rotations-custom-diode-with-track",
            ("Tracks", True),
            ("DiodeOption2", "D{} RELATIVE"),
            layout_option,
            id=test_id,
        )
        test_params.append(param)

    # add test with complex footprint
    example = "2x3-rotations-custom-diode-with-track-and-complex-footprint"
    param = pytest.param(
        example,
        ("Tracks", True),
        ("DiodeOption2", "D{} RELATIVE"),
        "kle.json",
        id=f"{example};Tracks;DiodeOption2;RAW",
    )
    test_params.append(param)

    # add test with complex footprint
    param = pytest.param(
        example,
        ("Tracks", True),
        ("DiodeOption2", "D{} PRESET diode_template.kicad_pcb"),
        "kle.json",
        id=f"{example};Tracks;DiodeOption2;RAW;PRESET",
    )
    test_params.append(param)

    # add one test for via layout
    param = pytest.param(
        "2x2",
        ("Tracks", True),
        ("DefaultDiode", None),
        "via.json",
        id="2x2;Tracks;DefaultDiode;VIA",
    )
    test_params.append(param)

    # add one test with layout where each switch have two diodes
    param = pytest.param(
        "2x3-rotations-double-diodes",
        ("Tracks", True),
        ("DiodeOption2", "D{} RELATIVE"),
        "kle.json",
        id="2x3-rotations-double-diodes;Tracks;DiodeOption2;RAW",
    )
    test_params.append(param)

    # add one test alternative keys and via annotated layout
    param = pytest.param(
        "2x2-with-alternative-layout",
        ("Tracks", True),
        ("DefaultDiode", None),
        "via.json",
        id="2x2-with-alternative-layout;Tracks;DefaultDiode;VIA",
    )
    test_params.append(param)

    return test_params


def get_reference_files(references_dir):
    references = Path(references_dir).glob("*.svg")
    reference_files = list(references)
    # ignore silkscreen svg when asserting results.
    # Plugin does not do anything on those layers and maintaining them
    # is a bit tedious, for example between 7.0.0 and 7.0.5 there is very
    # slight difference in silkscreen digits which would be falsely detected
    # as failure here. The `generate_render` will still produce silkscreen
    # svg to have nice images in test report but
    # for checking result it is ignored:
    reference_files = [
        item for item in reference_files if "Silkscreen" not in str(item)
    ]
    return reference_files


def prepare_project(request, tmpdir, example: str, layout_file: str) -> None:
    test_dir = request.fspath.dirname

    source_dir = f"{test_dir}/../examples/{example}"
    for filename in ["keyboard-before.kicad_pcb", layout_file]:
        shutil.copy(f"{source_dir}/{filename}", tmpdir)
    for template in glob.glob(f"{source_dir}/*_template.kicad_pcb"):
        shutil.copy(template, tmpdir)


def common_board_checks(pcb_path: str) -> None:
    for t in pcbnew.LoadBoard(pcb_path).GetTracks():
        assert t.GetNetCode() != 0


@pytest.fixture
def example_isolation(request, tmpdir):
    @contextmanager
    def _isolation(
        example: str, layout_file: str, tracks_variant: str, diode_variant: str
    ):
        prepare_project(request, tmpdir, example, layout_file)
        pcb_path = f"{tmpdir}/keyboard-before.kicad_pcb"
        layout_path = f"{tmpdir}/{layout_file}"

        yield layout_path, pcb_path

        generate_render(tmpdir, request)
        generate_drc(tmpdir, pcb_path)
        references_dir = get_references_dir(
            request, example, tracks_variant, diode_variant
        )
        assert_example(tmpdir, references_dir)
        common_board_checks(pcb_path)

    yield _isolation


@pytest.mark.parametrize(
    "example,route,diode_position,layout_option", __get_parameters()
)
def test_with_examples(
    example, route, diode_position, layout_option, example_isolation, kbplacer_process
) -> None:
    with example_isolation(example, layout_option, route[0], diode_position[0]) as e:
        layout_path, pcb_path = e
        kbplacer_process(route[1], diode_position[1], layout_path, pcb_path)


def test_with_examples_offset_diode_references(
    example_isolation, kbplacer_process
) -> None:
    example = "2x3-rotations"
    layout_file = "kle-annotated.json"
    with example_isolation(example, layout_file, "Tracks", "DefaultDiode") as e:
        layout_path, pcb_path = e
        board = pcbnew.LoadBoard(pcb_path)
        # diode references no longer must match 1-to-1 with key annotations
        # the diode-switch associated is inferred from netlists
        for i, f in enumerate(board.GetFootprints()):
            if f.GetReference().startswith("D"):
                f.SetReference(f"D{10 + i}")
        pcbnew.SaveBoard(pcb_path, board)

        kbplacer_process(True, None, layout_path, pcb_path)


def test_with_examples_annotated_layout_shuffled_references(
    example_isolation, kbplacer_process
) -> None:
    example = "2x3-rotations"
    layout_file = "kle-annotated.json"
    with example_isolation(example, layout_file, "Tracks", "DefaultDiode") as e:
        layout_path, pcb_path = e
        board = pcbnew.LoadBoard(pcb_path)

        # switches references no longer must match kle order if kle
        # file has row,column annotation labels
        def _swap_references(ref1, ref2) -> None:
            f1 = board.FindFootprintByReference(ref1)
            f2 = board.FindFootprintByReference(ref2)
            f1.SetReference("temp")
            f2.SetReference(ref1)
            f1.SetReference(ref2)

        _swap_references("SW1", "SW5")
        _swap_references("SW2", "SW3")
        # remember to modify stabilizer reference number which must match key
        board.FindFootprintByReference("ST3").SetReference("ST2")
        pcbnew.SaveBoard(pcb_path, board)

        kbplacer_process(True, None, layout_path, pcb_path)


def test_saving_connection_template(
    request, tmpdir, example_isolation, kbplacer_process
) -> None:
    example = "2x3-rotations-custom-diode-with-track-and-complex-footprint"
    layout_option = "kle.json"
    with example_isolation(example, layout_option, "Tracks", "DiodeOption2") as e:
        layout_path, pcb_path = e

        template_destination = Path(pcb_path).parent / "temp.kicad_pcb"
        kbplacer_process(
            True, f"D{{}} RELATIVE {template_destination}", layout_path, pcb_path
        )
        board = pcbnew.LoadBoard(str(template_destination))
        for t in board.GetTracks():
            assert t.GetNetCode() != 0
    # Override render for html report:
    # must replace actual board with template in order to use `generate_render`
    # which still supports hardcoded path only
    shutil.copy(template_destination, pcb_path)
    generate_render(tmpdir, request)


def test_placing_and_routing_separately(example_isolation, kbplacer_process):
    # It should be possible to run placing only (in first kbplacer invoke) and
    # then routing only (in second invoke).
    # Result should be the same as running all at once.
    # This tests if running routing without layout defined works
    example = "2x3-rotations"
    layout_file = "kle.json"
    with example_isolation(example, layout_file, "Tracks", "DefaultDiode") as e:
        layout_path, pcb_path = e
        # run without routing:
        kbplacer_process(False, None, layout_path, pcb_path)
        # run with routing, without layout
        kbplacer_process(True, None, None, pcb_path)


def test_empty_run_after_placing_and_routing(example_isolation, kbplacer_process):
    # The 'empty run' is when user deselects all options but still clicks OK
    # instead of Cancel (if using GUI). This should not change the state of
    # previously placed & routed PCB. Simulate this scenario with CLI subprocess:
    example = "2x3-rotations"
    layout_file = "kle.json"
    with example_isolation(example, layout_file, "Tracks", "DefaultDiode") as e:
        layout_path, pcb_path = e
        # run without routing:
        kbplacer_process(True, None, layout_path, pcb_path)
        # 'empty run':
        kbplacer_process(False, "D{} UNCHANGED", None, pcb_path)


def test_routing_with_template_without_diode_placement(
    example_isolation, kbplacer_process
):
    example = "2x3-rotations-custom-diode-with-track"
    layout_file = "kle.json"
    with example_isolation(example, layout_file, "Tracks", "DiodeOption2") as e:
        layout_path, pcb_path = e

        # run without routing:
        kbplacer_process(
            False, "D{} CUSTOM -5.197 4.503 90 BACK", layout_path, pcb_path
        )

        # add expected tracks template
        board = pcbnew.LoadBoard(pcb_path)
        for track in board.GetTracks():
            board.RemoveNative(track)
        assert len(board.GetTracks()) == 0

        add_track(board, pointMM(32.903, 41.503), pointMM(39.718, 41.503), pcbnew.B_Cu)
        add_track(board, pointMM(39.718, 41.503), pointMM(40.64, 40.581), pcbnew.B_Cu)
        add_track(board, pointMM(40.64, 40.581), pointMM(40.64, 33.02), pcbnew.B_Cu)

        board.Save(pcb_path)

        # run with routing, without layout and without diode placement,
        # template should be applied
        kbplacer_process(True, "D{} UNCHANGED", None, pcb_path)


@pytest.mark.parametrize(
    "angle",
    [90, 180, 270, 360, 60, -60, 30, -30, 10, -10, 5, -5],
)
def test_placing_and_routing_when_reference_pair_rotated(
    example_isolation, kbplacer_process, angle
):
    if KICAD_VERSION < (7, 0, 0) and angle in [60, 10, -60]:
        # the differences are not noticible, not worth creating dedicated
        # reference files support for KiCad 6 should be dropped soon anyway.
        pytest.skip(
            "These angles fail on KiCad 6 due to some rounding errors... ignoring"
        )

    # this scenario reproduces https://github.com/adamws/kicad-kbplacer/issues/17
    example = "2x3-rotations-custom-diode-with-track"
    layout_file = "kle.json"
    with example_isolation(example, layout_file, "Tracks", "DiodeOption2") as e:
        layout_path, pcb_path = e
        saved_template_path = Path(pcb_path).parent / "template.kicad_pcb"

        board = pcbnew.LoadBoard(pcb_path)
        switch = board.FindFootprintByReference("SW1")
        diode = board.FindFootprintByReference("D1")
        rotation_center = switch.GetPosition()

        for footprint in [switch, diode]:
            rotate(footprint, rotation_center, angle)
        for track in board.GetTracks():
            rotate(track, rotation_center, angle)

        board.Save(pcb_path)

        kbplacer_process(
            True, f"D{{}} RELATIVE {saved_template_path}", layout_path, pcb_path
        )

    # note that template is always the same because we normalize it
    # (it does not depend on initial rotation)
    assert Path(saved_template_path).is_file()
    board = pcbnew.LoadBoard(str(saved_template_path))
    switch = board.FindFootprintByReference("SW1")
    diode = board.FindFootprintByReference("D1")
    assert switch.GetPosition().x == 0
    assert switch.GetPosition().y == 0
    assert diode.GetPosition().x == -5197000
    assert diode.GetPosition().y == 4503000

    def tracks_to_sets():
        starts = []
        ends = []
        for t in board.GetTracks():
            start = t.GetStart()
            end = t.GetEnd()
            starts.append((start.x, start.y))
            ends.append((end.x, end.y))
        return set(starts), set(ends)

    starts, ends = tracks_to_sets()
    assert starts == {(-5197000, 3403000), (1618000, 3403000), (2540000, 2481000)}
    assert ends == {(2540000, -5080000), (1618000, 3403000), (2540000, 2481000)}


def __filter_for_board_creation(parameters):
    new_parameters = []
    for p in parameters:
        example, route_option, diode_option, layout_option = p.values
        # 2x3-rotations excluded because adding stabilizers not yet supported
        if (
            example != "2x3-rotations"
            and route_option[0] == "Tracks"
            and diode_option[0] != "DiodeOption2"
            and layout_option in ["kle-annotated.json", "via.json"]
        ):
            new_parameters.append(p)
    return new_parameters


@pytest.mark.parametrize(
    "example,route,diode_position,layout_option",
    __filter_for_board_creation(__get_parameters()),
)
def test_board_creation(
    request,
    example,
    route,
    diode_position,
    layout_option,
    example_isolation,
    kbplacer_process,
) -> None:
    with example_isolation(example, layout_option, route[0], diode_position[0]) as e:
        layout_path, pcb_path = e
        # remove board file, it should be created from scratch
        os.remove(pcb_path)

        kbplacer_process(
            route[1],
            diode_position[1],
            layout_path,
            pcb_path,
            flags=["--create-from-annotated-layout"],
            args={
                "--switch-footprint": f"{get_footprints_dir(request)}:SW_Cherry_MX_PCB_1.00u",
                "--diode-footprint": f"{get_footprints_dir(request)}:D_SOD-323F",
                # TODO: handle stabilizer footprints
            },
        )


# Use area of board edges bounding box to test if outline is generated.
# Before plugin run, the area must be zero, then it must be approximately
# equal reference.
# References were obtained by dry-running and manual inspection of resulting PCBs
@pytest.mark.parametrize(
    "delta,expected_area",
    [(0, 1490), (2, 1815), (-2, 1197)],
)
def test_board_outline_building(
    example_isolation, kbplacer_process, delta, expected_area
):
    def get_area():
        board = pcbnew.LoadBoard(pcb_path)
        bbox = board.GetBoardEdgesBoundingBox()
        width = cast(float, pcbnew.ToMM(bbox.GetWidth()))
        height = cast(float, pcbnew.ToMM(bbox.GetHeight()))
        return width * height

    example = "2x2"
    layout_file = "kle.json"
    with example_isolation(example, layout_file, "NoTracks", "DefaultDiode") as e:
        layout_path, pcb_path = e
        assert get_area() == 0

        kbplacer_process(
            False,
            None,
            layout_path,
            pcb_path,
            flags=["--build-board-outline"],
            args={"--outline-delta": str(delta)},
        )

        error_margin = expected_area * (1 / 100.0)
        assert abs(get_area() - expected_area) <= error_margin
