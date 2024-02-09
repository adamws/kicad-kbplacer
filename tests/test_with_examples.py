from __future__ import annotations

import difflib
import glob
import logging
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import cast

import pcbnew
import pytest
from xmldiff import actions, main

from .conftest import (
    KICAD_VERSION,
    generate_drc,
    generate_render,
    get_footprints_dir,
    get_references_dir,
    request_to_references_dir,
    rotate,
)

logger = logging.getLogger(__name__)


def run_kbplacer_process(
    route,
    diode_position,
    package_path,
    package_name,
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
    layout_options = {"RAW": "kle.json", "INTERNAL": "kle-internal.json"}
    test_params = []
    for example in examples:
        for route_option_name, route_option in route_options.items():
            for diode_option_name, diode_option in diode_options.items():
                for layout_option_name, layout_option in layout_options.items():
                    test_id = f"{example};{route_option_name};{diode_option_name};{layout_option_name}"
                    param = pytest.param(
                        example, route_option, diode_option, layout_option, id=test_id
                    )
                    test_params.append(param)

    # this special examples can't be used with all option combinations, appended here:
    for layout_option_name, layout_option in layout_options.items():
        test_id = f"2x3-rotations-custom-diode-with-track;Tracks;DiodeOption2;{layout_option_name}"
        param = pytest.param(
            "2x3-rotations-custom-diode-with-track",
            True,
            "D{} RELATIVE",
            layout_option,
            id=test_id,
        )
        test_params.append(param)

    # add test with complex footprint
    example = "2x3-rotations-custom-diode-with-track-and-complex-footprint"
    param = pytest.param(
        example,
        True,
        "D{} RELATIVE",
        "kle.json",
        id=f"{example};Tracks;DiodeOption2;RAW",
    )
    test_params.append(param)

    # add test with complex footprint
    param = pytest.param(
        example,
        True,
        "D{} PRESET diode_template.kicad_pcb",
        "kle.json",
        id=f"{example};Tracks;DiodeOption2;RAW;PRESET",
    )
    test_params.append(param)

    # add one test for via layout
    param = pytest.param(
        "2x2",
        True,
        None,
        "via.json",
        id="2x2;Tracks;DefaultDiode;VIA",
    )
    test_params.append(param)

    return test_params


def get_reference_files(references_dir):
    references = Path(references_dir).glob("*.svg")
    reference_files = list(references)
    # ignore silkscreen svg when asserting results. Plugin does not do anything on those layers
    # and maintaining them is a bit tedious, for example between 7.0.0 and 7.0.5 there is very
    # slight difference in silkscreen digits which would be falsely detected as failure here.
    # `generate_render` will still produce silkscreen svg to have nice images in test report but
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


@pytest.mark.parametrize(
    "example,route,diode_position,layout_option", __get_parameters()
)
def test_with_examples(
    example,
    route,
    diode_position,
    layout_option,
    tmpdir,
    request,
    package_path,
    package_name,
) -> None:
    prepare_project(request, tmpdir, example, layout_option)

    pcb_path = f"{tmpdir}/keyboard-before.kicad_pcb"

    run_kbplacer_process(
        route,
        diode_position,
        package_path,
        package_name,
        f"{tmpdir}/{layout_option}",
        pcb_path,
    )

    generate_render(tmpdir, request)
    generate_drc(tmpdir, pcb_path)

    references_dir = request_to_references_dir(request)
    assert_example(tmpdir, references_dir)
    for t in pcbnew.LoadBoard(pcb_path).GetTracks():
        assert t.GetNetCode() != 0


def test_with_examples_offset_diode_annotations(
    tmpdir,
    request,
    package_path,
    package_name,
) -> None:
    example = "2x3-rotations"
    layout_option = "kle.json"
    prepare_project(request, tmpdir, example, layout_option)

    pcb_path = f"{tmpdir}/keyboard-before.kicad_pcb"
    board = pcbnew.LoadBoard(pcb_path)
    # diode annotations no longer must match 1-to-1 with key annotations
    for i, f in enumerate(board.GetFootprints()):
        if f.GetReference().startswith("D"):
            f.SetReference(f"D{10 + i}")
    pcbnew.SaveBoard(pcb_path, board)

    run_kbplacer_process(
        True,
        None,
        package_path,
        package_name,
        f"{tmpdir}/{layout_option}",
        pcb_path,
    )

    generate_render(tmpdir, request)
    generate_drc(tmpdir, pcb_path)

    references_dir = get_references_dir(request, example, "Tracks", "DefaultDiode")
    assert_example(tmpdir, references_dir)
    for t in pcbnew.LoadBoard(pcb_path).GetTracks():
        assert t.GetNetCode() != 0


def test_saving_connection_template(
    tmpdir,
    request,
    package_path,
    package_name,
) -> None:
    example = "2x3-rotations-custom-diode-with-track-and-complex-footprint"
    layout_option = "kle.json"
    prepare_project(request, tmpdir, example, layout_option)

    pcb_path = f"{tmpdir}/keyboard-before.kicad_pcb"
    template_destination = f"{tmpdir}/temp.kicad_pcb"

    run_kbplacer_process(
        True,
        f"D{{}} RELATIVE {template_destination}",
        package_path,
        package_name,
        f"{tmpdir}/{layout_option}",
        pcb_path,
    )

    # must replace actual board with template in order to use `generate_render`
    # which still supports hardcoded path only
    shutil.copy(template_destination, pcb_path)
    generate_render(tmpdir, request)

    board = pcbnew.LoadBoard(template_destination)
    for t in board.GetTracks():
        assert t.GetNetCode() != 0


def test_placing_and_routing_separately(tmpdir, request, package_path, package_name):
    # It should be possible to run placing only (in first kbplacer invoke) and
    # then routing only (in second invoke).
    # Result should be the same as running all at once.
    # This tests if running routing without layout defined works
    example = "2x3-rotations"
    layout_file = "kle.json"
    prepare_project(request, tmpdir, example, layout_file)

    pcb_path = f"{tmpdir}/keyboard-before.kicad_pcb"

    # run without routing:
    run_kbplacer_process(
        False,
        None,
        package_path,
        package_name,
        f"{tmpdir}/{layout_file}",
        pcb_path,
    )
    # run with routing, without layout
    run_kbplacer_process(
        True,
        None,
        package_path,
        package_name,
        None,
        pcb_path,
    )

    generate_render(tmpdir, request)
    generate_drc(tmpdir, pcb_path)

    references_dir = get_references_dir(request, example, "Tracks", "DefaultDiode")
    assert_example(tmpdir, references_dir)


@pytest.mark.parametrize(
    "angle",
    [90, 180, 270, 360, 60, -60, 30, -30, 10, -10, 5, -5],
)
def test_placing_and_routing_when_reference_pair_rotated(
    tmpdir, request, package_path, package_name, angle
):
    # this scenario reproduces https://github.com/adamws/kicad-kbplacer/issues/17
    example = "2x3-rotations-custom-diode-with-track"
    layout_file = "kle.json"
    prepare_project(request, tmpdir, example, layout_file)

    pcb_path = f"{tmpdir}/keyboard-before.kicad_pcb"
    saved_template_path = f"{tmpdir}/template.kicad_pcb"

    board = pcbnew.LoadBoard(pcb_path)
    switch = board.FindFootprintByReference("SW1")
    diode = board.FindFootprintByReference("D1")
    rotation_center = switch.GetPosition()

    for footprint in [switch, diode]:
        rotate(footprint, rotation_center, angle)
    for track in board.GetTracks():
        rotate(track, rotation_center, angle)

    board.Save(pcb_path)

    run_kbplacer_process(
        True,
        f"D{{}} RELATIVE {saved_template_path}",
        package_path,
        package_name,
        f"{tmpdir}/{layout_file}",
        pcb_path,
    )

    generate_render(tmpdir, request)
    generate_drc(tmpdir, pcb_path)

    # note that template is always the same because we normalize it
    # (it does not depend on initial rotation)
    assert Path(saved_template_path).is_file()
    board = pcbnew.LoadBoard(saved_template_path)
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

    references_dir = get_references_dir(request, example, "Tracks", "DiodeOption2")
    if KICAD_VERSION < (7, 0, 0) and angle in [60, 10, -60]:
        # the differences are not noticible, not worth creating dedicated reference files
        # support for KiCad 6 should be dropped soon anyway.
        logger.debug(
            "These angles fail on KiCad 6 due to some rounding errors... ignoring"
        )
    else:
        assert_example(tmpdir, references_dir)


@pytest.mark.parametrize("layout_file", ["kle.json", "via.json"])
def test_board_creation(tmpdir, request, package_path, package_name, layout_file):
    example = "2x2"

    test_dir = request.fspath.dirname

    source_dir = f"{test_dir}/../examples/{example}"
    shutil.copy(f"{source_dir}/{layout_file}", tmpdir)

    pcb_path = f"{tmpdir}/keyboard-before.kicad_pcb"

    # run without routing:
    run_kbplacer_process(
        True,
        None,
        package_path,
        package_name,
        f"{tmpdir}/{layout_file}",
        pcb_path,
        flags=["--create-from-annotated-layout"],
        args={
            "--switch-footprint": f"{get_footprints_dir(request)}:SW_Cherry_MX_PCB_1.00u",
            "--diode-footprint": f"{get_footprints_dir(request)}:D_SOD-323F",
        },
    )

    generate_render(tmpdir, request)
    generate_drc(tmpdir, pcb_path)

    references_dir = get_references_dir(request, example, "Tracks", "DefaultDiode")
    assert_example(tmpdir, references_dir)


# Use area of board edges bounding box to test if outline is generated.
# Before plugin run, the area must be zero, then it must be approximately equal reference.
# References were obtained by dry-running and manual inspection of resulting PCBs
@pytest.mark.parametrize(
    "delta,expected_area",
    [(0, 1490), (2, 1815), (-2, 1197)],
)
def test_board_outline_building(
    tmpdir, request, package_path, package_name, delta, expected_area
):
    example = "2x2"
    layout_file = "kle.json"

    prepare_project(request, tmpdir, example, layout_file)
    pcb_path = f"{tmpdir}/keyboard-before.kicad_pcb"

    def get_area():
        board = pcbnew.LoadBoard(pcb_path)
        bbox = board.GetBoardEdgesBoundingBox()
        width = cast(float, pcbnew.ToMM(bbox.GetWidth()))
        height = cast(float, pcbnew.ToMM(bbox.GetHeight()))
        return width * height

    assert get_area() == 0

    run_kbplacer_process(
        False,
        None,
        package_path,
        package_name,
        f"{tmpdir}/{layout_file}",
        pcb_path,
        flags=["--build-board-outline"],
        args={"--outline-delta": str(delta)},
    )

    generate_render(tmpdir, request)
    generate_drc(tmpdir, pcb_path)

    references_dir = get_references_dir(request, example, "NoTracks", "DefaultDiode")
    assert_example(tmpdir, references_dir)

    error_margin = expected_area * (1 / 100.0)
    assert abs(get_area() - expected_area) <= error_margin
