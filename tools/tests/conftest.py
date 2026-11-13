# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import base64
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--update-references",
        action="store_true",
        help="Overwrite expected reference files with actual tool output",
    )


@pytest.fixture
def update_references(request) -> bool:
    return request.config.getoption("--update-references")


@pytest.fixture(scope="session")
def requires_openscad_env():
    """Skip tests when 'tools-openscad' hatch environment can't be created,
    e.g. its pinned dependencies are not available for given python version"""
    project_root = Path(__file__).parent.parent.parent
    result = run_hatch_tool(
        project_root,
        "python",
        "-c",
        "import shapely, solid",
        env="tools-openscad",
        timeout=300,
    )
    if result.returncode != 0:
        pytest.skip(f"'tools-openscad' environment not available: {result.stderr}")


@pytest.fixture
def kle_layouts_dir(project_root):
    """Get the directory with KLE layouts shared with kbplacer tests."""
    return project_root / "tests" / "data" / "kle-layouts"


@pytest.fixture
def via_layouts_dir(project_root):
    """Get the directory with VIA layouts shared with kbplacer tests."""
    return project_root / "tests" / "data" / "via-layouts"


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


def add_to_report(tmp_output_dir: Path, image: Path, name: str = "") -> None:
    """Attach image to the HTML report entry of the currently running test.

    Images are shown in the order of adding, `name` (defaults to file name)
    is used as image caption.
    """
    report_dir = tmp_output_dir / "report"
    report_dir.mkdir(exist_ok=True)
    index = len(list(report_dir.iterdir()))
    shutil.copy(image, report_dir / f"{index:02d}-{name or image.stem}{image.suffix}")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    pytest_html = item.config.pluginmanager.getplugin("html")
    outcome = yield
    report = outcome.get_result()
    if pytest_html is None or report.when != "call" or report.skipped:
        return

    extras = getattr(report, "extras", [])
    if tmp_output_dir := item.funcargs.get("tmp_output_dir"):
        report_dir = tmp_output_dir / "report"
        images = sorted(report_dir.glob("*.svg")) if report_dir.is_dir() else []
        for image in images:
            content = base64.b64encode(image.read_bytes()).decode("utf-8")
            extras.append(
                pytest_html.extras.image(
                    content,
                    name=image.stem.split("-", 1)[1],
                    mime_type="image/svg+xml",
                    extension="svg",
                )
            )
    report.extras = extras


def run_hatch_tool(
    project_root: Path,
    tool_name: str,
    *args,
    cwd=None,
    env: str = "tools",
    timeout: int = 60,
):
    """
    Run a hatch tool command and return the result.

    Args:
        project_root: Path to project root
        tool_name: Name of the tool to run (e.g., 'layout2image')
        *args: Additional arguments to pass to the tool
        cwd: Working directory (defaults to project_root)
        env: Hatch environment defining the tool (e.g., 'tools-openscad')
        timeout: Timeout in seconds

    Returns:
        subprocess.CompletedProcess
    """
    if cwd is None:
        cwd = project_root

    cmd = ["hatch", "run", f"{env}:{tool_name}"] + list(args)
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
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


def render_plate(project_root: Path, scad_path: Path, svg_path: Path) -> None:
    """Render top view of OpenSCAD plate, see scad2svg.py"""
    result = run_hatch_tool(
        project_root,
        "python",
        "tools/tests/scad2svg.py",
        "--in",
        str(scad_path),
        "--out",
        str(svg_path),
        env="tools-openscad",
    )
    assert result.returncode == 0, f"scad2svg failed: {result.stderr}"


def normalize_scad(scad_content: str) -> str:
    """Remove comments (with generation timestamp and embedded tool source)
    and formatting from SolidPython output"""
    content = re.sub(r"/\*.*?\*/", "", scad_content, flags=re.DOTALL)
    content = re.sub(r"//[^\n]*", "", content)
    return re.sub(r"\s+", "", content)


def compare_scad_files(actual_path: Path, expected_path: Path) -> bool:
    return normalize_scad(actual_path.read_text()) == normalize_scad(
        expected_path.read_text()
    )


def assert_matches_reference(
    actual_path: Path, expected_path: Path, compare, update: bool
) -> None:
    """Compare tool output with reference file, or overwrite reference when
    running with `--update-references`"""
    if update:
        shutil.copy(actual_path, expected_path)
    assert expected_path.exists(), f"Missing reference file {expected_path}"
    assert compare(actual_path, expected_path), (
        f"{actual_path.name} differs from {expected_path}, "
        "run with --update-references if change is intended"
    )
