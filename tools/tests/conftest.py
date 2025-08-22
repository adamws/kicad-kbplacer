# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


@pytest.fixture
def project_root():
    """Get the project root directory."""
    return Path(__file__).parent.parent.parent


@pytest.fixture
def tools_data_dir():
    """Get the tools test data directory."""
    return Path(__file__).parent / "data"


@pytest.fixture
def tmp_output_dir():
    """Create a temporary directory for test outputs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def run_hatch_tool(project_root: Path, tool_name: str, *args, cwd=None):
    """
    Run a hatch tool command and return the result.

    Args:
        project_root: Path to project root
        tool_name: Name of the tool to run (e.g., 'layout2image')
        *args: Additional arguments to pass to the tool
        cwd: Working directory (defaults to project_root)

    Returns:
        subprocess.CompletedProcess
    """
    if cwd is None:
        cwd = project_root

    cmd = ["hatch", "run", f"tools:{tool_name}"] + list(args)
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=60, check=False
    )


def normalize_svg_for_comparison(svg_content: str) -> ET.Element:
    """
    Parse SVG and normalize for comparison by removing whitespace
    and formatting differences.

    Args:
        svg_content: SVG content as string

    Returns:
        Normalized XML Element
    """
    # Parse the SVG
    root = ET.fromstring(svg_content)

    # Remove whitespace from text content
    for elem in root.iter():
        if elem.text:
            elem.text = elem.text.strip()
        if elem.tail:
            elem.tail = elem.tail.strip()

    return root


def compare_svg_files(actual_path: Path, expected_path: Path) -> bool:
    """
    Compare two SVG files, ignoring whitespace and formatting differences.

    Args:
        actual_path: Path to actual SVG output
        expected_path: Path to expected SVG reference

    Returns:
        True if SVGs are equivalent, False otherwise
    """
    with open(actual_path, "r") as f:
        actual_content = f.read()
    with open(expected_path, "r") as f:
        expected_content = f.read()

    actual_root = normalize_svg_for_comparison(actual_content)
    expected_root = normalize_svg_for_comparison(expected_content)

    # Convert to string for comparison (removes formatting differences)
    actual_normalized = ET.tostring(actual_root, encoding="unicode")
    expected_normalized = ET.tostring(expected_root, encoding="unicode")

    return actual_normalized == expected_normalized
