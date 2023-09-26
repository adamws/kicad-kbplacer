from __future__ import annotations

import difflib
import logging
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from xmldiff import actions, main

from .conftest import (
    generate_render,
    get_footprints_dir,
    get_references_dir,
    request_to_references_dir,
)

logger = logging.getLogger(__name__)


def run_kbplacer_process(
    route,
    diode_position,
    workdir,
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
        cwd=workdir,
    )
    p.communicate()
    if p.returncode != 0:
        raise Exception("Switch placement failed")


def assert_group(expected: ET.ElementTree, actual: ET.ElementTree):
    expected = ET.tostring(expected).decode()
    actual = ET.tostring(actual).decode()

    edit_script = None
    try:
        edit_script = main.diff_texts(
            expected, actual, diff_options={"F": 0, "ratio_mode": "accurate"}
        )
    except Exception as e:
        logger.warning(f"Running diff on xml failed: {e}")
        diff = difflib.unified_diff(expected.splitlines(), actual.splitlines())
        for d in diff:
            logger.info(d)
        assert False, "Difference probably found"

    if edit_script and any(type(node) != actions.MoveNode for node in edit_script):
        logger.info("Difference found")
        diff = difflib.unified_diff(expected.splitlines(), actual.splitlines())
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

    number_of_groups = len(expected_groups)

    for i in range(0, number_of_groups):
        logger.info(f"Analyzing {expected.name} file, group {i+1}/{number_of_groups}")
        assert_group(expected_groups[i], actual_groups[i])


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
            "D{} CURRENT_RELATIVE",
            layout_option,
            id=test_id,
        )
        test_params.append(param)

    # add test with complex footprint
    param = pytest.param(
        "2x3-rotations-custom-diode-with-track-and-complex-footprint",
        True,
        "D{} CURRENT_RELATIVE",
        "kle.json",
        id="2x3-rotations-custom-diode-with-track-and-complex-footprint;Tracks;DiodeOption2;RAW",
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
    workdir,
    package_name,
) -> None:
    prepare_project(request, tmpdir, example, layout_option)

    pcb_path = f"{tmpdir}/keyboard-before.kicad_pcb"

    run_kbplacer_process(
        route,
        diode_position,
        workdir,
        package_name,
        f"{tmpdir}/{layout_option}",
        pcb_path,
    )

    generate_render(tmpdir, request)

    references_dir = request_to_references_dir(request)
    assert_example(tmpdir, references_dir)


def test_placing_and_routing_separately(tmpdir, request, workdir, package_name):
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
        workdir,
        package_name,
        f"{tmpdir}/{layout_file}",
        pcb_path,
    )
    # run with routing, without layout
    run_kbplacer_process(
        True,
        None,
        workdir,
        package_name,
        None,
        pcb_path,
    )

    generate_render(tmpdir, request)

    references_dir = get_references_dir(request, example, "Tracks", "DefaultDiode")
    assert_example(tmpdir, references_dir)


def test_board_creation(tmpdir, request, workdir, package_name):
    example = "2x2"
    layout_file = "via.json"

    test_dir = request.fspath.dirname

    source_dir = f"{test_dir}/../examples/{example}"
    shutil.copy(f"{source_dir}/{layout_file}", tmpdir)

    pcb_path = f"{tmpdir}/keyboard-before.kicad_pcb"

    # run without routing:
    run_kbplacer_process(
        True,
        None,
        workdir,
        package_name,
        f"{tmpdir}/{layout_file}",
        pcb_path,
        flags=["--create-from-via"],
        args={
            "--switch-footprint": f"{get_footprints_dir(request)}:SW_Cherry_MX_PCB_1.00u",
            "--diode-footprint": f"{get_footprints_dir(request)}:D_SOD-323F",
        },
    )

    generate_render(tmpdir, request)

    references_dir = get_references_dir(request, example, "Tracks", "DefaultDiode")
    assert_example(tmpdir, references_dir)
