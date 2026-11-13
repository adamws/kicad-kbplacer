# SPDX-FileCopyrightText: 2026 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import re

import pytest

from .conftest import (
    add_to_report,
    assert_matches_reference,
    compare_scad_files,
    render_plate,
    run_hatch_tool,
)
from .test_layout2image import REGULAR_LAYOUTS, render_layout

# layout2openscad dependencies are not available on all supported python versions
pytestmark = pytest.mark.usefixtures("requires_openscad_env")

U = 19.05

# options tested with rotated-keys.json layout
OPTIONS = [
    ("envelope", ["--shape", "envelope"]),
    ("convex-hull", ["--shape", "convex_hull"]),
    ("margin", ["--shape", "convex_hull", "--margin", "5"]),
    ("align-origin", ["--align-origin"]),
    ("cutout", ["--cutout-size", "13.8", "--cutout-outline-thickness", "1"]),
    ("plate-thickness", ["--plate-thickness", "1.5"]),
    ("key-distance", ["--key-distance-x", "18", "--key-distance-y", "17"]),
    (
        "outline-ignore-keys",
        ["--shape", "convex_hull", "--outline-ignore-keys", "0"],
    ),
]


def generate_plate(project_root, tmp_output_dir, input_layout, *args):
    """Run layout2openscad and add layout and plate renderings to the report"""
    output_scad = tmp_output_dir / f"{input_layout.stem}.scad"

    result = run_hatch_tool(
        project_root,
        "layout2openscad",
        "--in",
        str(input_layout),
        "--out",
        str(output_scad),
        "--force",
        *args,
        env="tools-openscad",
    )
    if result.returncode != 0:
        pytest.fail(
            f"layout2openscad command failed with return code {result.returncode}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
    assert output_scad.exists()

    layout_svg = tmp_output_dir / f"{input_layout.stem}-layout.svg"
    render_layout(project_root, input_layout, layout_svg)
    add_to_report(tmp_output_dir, layout_svg, "layout")

    plate_svg = tmp_output_dir / f"{input_layout.stem}-plate.svg"
    render_plate(project_root, output_scad, plate_svg)
    add_to_report(tmp_output_dir, plate_svg, "plate")

    return output_scad


def parse_plate(scad_path):
    """Get switch holes centers and plate outline points from generated file"""
    scad = scad_path.read_text()
    holes = [
        (float(x), float(y))
        for x, y in re.findall(r"translate\(v = \[([-\d.]+), ([-\d.]+), 0\]\)", scad)
    ]
    plate = re.search(r"polygon\(points = (\[.*\])\)", scad)
    assert plate
    return holes, json.loads(plate.group(1))


def bounds(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


class TestLayout2OpenScad:
    """Test suite for layout2openscad tool."""

    @pytest.mark.parametrize("layout", REGULAR_LAYOUTS)
    def test_regular_layouts(
        self,
        project_root,
        kle_layouts_dir,
        tools_data_dir,
        tmp_output_dir,
        update_references,
        layout,
    ):
        input_layout = kle_layouts_dir / f"{layout}.json"
        expected = tools_data_dir / "layout2openscad" / f"expected-{layout}.scad"

        output_scad = generate_plate(project_root, tmp_output_dir, input_layout)

        assert_matches_reference(
            output_scad, expected, compare_scad_files, update_references
        )

    @pytest.mark.parametrize("layout", ["rotated-keys", "stepped-keys"])
    def test_layouts_shared_with_layout2image(
        self, project_root, tools_data_dir, tmp_output_dir, update_references, layout
    ):
        """
        Rotated keys holes follow key rotation, stepped keys holes are centered
        on the raised part with plate covering the lower step.
        """
        input_layout = tools_data_dir / "layout2image" / f"{layout}.json"
        expected = tools_data_dir / "layout2openscad" / f"expected-{layout}.scad"

        output_scad = generate_plate(
            project_root, tmp_output_dir, input_layout, "--shape", "convex_hull"
        )

        assert_matches_reference(
            output_scad, expected, compare_scad_files, update_references
        )

    @pytest.mark.parametrize(
        "name,args", [pytest.param(name, args, id=name) for name, args in OPTIONS]
    )
    def test_options(
        self,
        project_root,
        tools_data_dir,
        tmp_output_dir,
        update_references,
        name,
        args,
    ):
        input_layout = tools_data_dir / "layout2image" / "rotated-keys.json"
        expected = tools_data_dir / "layout2openscad" / f"expected-option-{name}.scad"

        output_scad = generate_plate(project_root, tmp_output_dir, input_layout, *args)

        assert_matches_reference(
            output_scad, expected, compare_scad_files, update_references
        )

    def test_ignore_alternative_layouts(
        self, project_root, via_layouts_dir, tmp_output_dir
    ):
        """VIA layout alternative keys get holes unless explicitly ignored."""
        # 5x12 ortholinear with alternative bottom rows (2U keys)
        input_layout = via_layouts_dir / "0_sixty.json"

        all_holes, _ = parse_plate(
            generate_plate(project_root, tmp_output_dir, input_layout)
        )
        default_holes, _ = parse_plate(
            generate_plate(
                project_root,
                tmp_output_dir,
                input_layout,
                "--ignore-alternative-layouts",
            )
        )

        assert len(default_holes) == 60
        assert len(all_holes) > len(default_holes)
        assert set(default_holes) < set(all_holes)

    @pytest.mark.parametrize(
        "key,hole_x,plate_x",
        [
            # step on the right of the raised part
            pytest.param(
                {"w": 1.25, "w2": 1.75, "l": True}, 0.625, (0, 1.75), id="step-right"
            ),
            # step on the left of the raised part
            pytest.param(
                {"x": 0.5, "w": 1.25, "w2": 1.75, "x2": -0.5, "l": True},
                1.125,
                (0, 1.75),
                id="step-left",
            ),
        ],
    )
    def test_stepped_key(self, project_root, tmp_output_dir, key, hole_x, plate_x):
        """Switch hole is centered on the raised part, plate covers the step."""
        input_layout = tmp_output_dir / "stepped-key.json"
        input_layout.write_text(json.dumps([[key, ""]]))

        holes, points = parse_plate(
            generate_plate(project_root, tmp_output_dir, input_layout)
        )

        assert holes == [(pytest.approx(hole_x * U), pytest.approx(-0.5 * U))]
        assert bounds(points) == pytest.approx((plate_x[0] * U, -U, plate_x[1] * U, 0))

    def test_rotated_stepped_key(self, project_root, tmp_output_dir):
        """Step follows key rotation, 90 degrees moves it below the raised part."""
        # key starts at rotation origin (0, 0), 90 degrees moves it to x -1..0
        key = {"r": 90, "rx": 0, "ry": 0, "w2": 1.75, "l": True}
        input_layout = tmp_output_dir / "rotated-stepped-key.json"
        input_layout.write_text(json.dumps([[key, ""]]))

        holes, points = parse_plate(
            generate_plate(project_root, tmp_output_dir, input_layout)
        )

        assert holes == [(pytest.approx(-0.5 * U), pytest.approx(-0.5 * U))]
        assert bounds(points) == pytest.approx((-U, -1.75 * U, 0, 0))

    def test_layout2openscad_help(self, project_root):
        result = run_hatch_tool(
            project_root, "layout2openscad", "--help", env="tools-openscad"
        )

        assert result.returncode == 0, f"Help command failed: {result.stderr}"

    def test_layout2openscad_invalid_input(self, project_root, tmp_output_dir):
        result = run_hatch_tool(
            project_root,
            "layout2openscad",
            "--in",
            "non-existent-file.json",
            "--out",
            str(tmp_output_dir / "invalid-test.scad"),
            "--force",
            env="tools-openscad",
        )

        assert result.returncode != 0

    def test_layout2openscad_existing_output(
        self, project_root, tools_data_dir, tmp_output_dir
    ):
        """Existing output is not overwritten without --force."""
        output_scad = tmp_output_dir / "existing.scad"
        output_scad.write_text("keep")

        result = run_hatch_tool(
            project_root,
            "layout2openscad",
            "--in",
            str(tools_data_dir / "layout2image" / "rotated-keys.json"),
            "--out",
            str(output_scad),
            env="tools-openscad",
        )

        assert result.returncode != 0
        assert output_scad.read_text() == "keep"
