# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import pytest

from .conftest import compare_svg_files, run_hatch_tool


class TestLayout2Image:
    """Test suite for layout2image tool."""

    def test_rotated_keys_positioning(
        self, project_root, tools_data_dir, tmp_output_dir
    ):
        """
        Test that rotated keys with same y-coordinates are positioned correctly.

        This is a regression test for the bug where rotated keys with the same
        y-coordinate in the layout were rendered at different visual positions
        due to coordinate system mismatch in rotation transforms.
        """
        input_layout = tools_data_dir / "layout2image" / "rotated-keys.json"
        expected_svg = tools_data_dir / "layout2image" / "expected-rotated-keys.svg"
        output_svg = tmp_output_dir / "output-rotated-keys.svg"

        assert input_layout.exists()
        assert expected_svg.exists()

        result = run_hatch_tool(
            project_root,
            "layout2image",
            "--in",
            str(input_layout),
            "--out",
            str(output_svg),
            "--force",
        )

        if result.returncode != 0:
            pytest.fail(
                f"layout2image command failed with return code {result.returncode}\n"
                f"stdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            )

        assert output_svg.exists()
        assert compare_svg_files(output_svg, expected_svg)

    def test_layout2image_help(self, project_root):
        result = run_hatch_tool(project_root, "layout2image", "--help")

        assert result.returncode == 0, f"Help command failed: {result.stderr}"

    def test_layout2image_invalid_input(self, project_root, tmp_output_dir):
        output_svg = tmp_output_dir / "invalid-test.svg"

        # Run with non-existent input file
        result = run_hatch_tool(
            project_root,
            "layout2image",
            "--in",
            "non-existent-file.json",
            "--out",
            str(output_svg),
            "--force",
        )

        # Should fail with non-zero return code
        assert result.returncode != 0
