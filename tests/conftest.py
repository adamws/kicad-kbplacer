import base64
import ctypes
import glob
import logging
import mimetypes
import os
import re
import shutil
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Tuple, Union

import pcbnew
import pytest
import svgpathtools

Numeric = Union[int, float]
Box = Tuple[Numeric, Numeric, Numeric, Numeric]


version_match = re.search(r"(\d+)\.(\d+)\.(\d+)", pcbnew.Version())
KICAD_VERSION = tuple(map(int, version_match.groups())) if version_match else ()
logger = logging.getLogger(__name__)


def pytest_collection_modifyitems(items) -> None:
    try:
        is_nightly = pcbnew.IsNightlyVersion()
    except AttributeError:
        is_nightly = False

    for i, item in enumerate(items):
        if item.get_closest_marker("run_first"):
            items.insert(0, items.pop(i))
            break

    if is_nightly:
        for item in items:
            if not item.get_closest_marker("no_ignore_nightly"):
                item.add_marker(
                    pytest.mark.xfail(reason="Failures on nightly version ignored")
                )


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--test-plugin-installation",
        action="store_true",
        help="Run tests using ~/.local/share/kicad/8.0/3rdparty/plugins instance instead of local one",
        default=False,
    )
    parser.addoption(
        "--save-results-as-reference",
        action="store_true",
        help="Save test results as expected results."
        "This option is for updating expected results and NOT for testing",
        default=False,
    )
    parser.addoption(
        "--profile",
        action="store_true",
        help="Run example tests with cProfile",
        default=False,
    )


@pytest.fixture(scope="session")
def package_path(request):
    if request.config.getoption("--test-plugin-installation"):
        home_directory = Path.home()
        return f"{home_directory}/.local/share/kicad/8.0/3rdparty/plugins"
    return Path(os.path.realpath(__file__)).parents[1]


@pytest.fixture(scope="session")
def package_name(request):
    if request.config.getoption("--test-plugin-installation"):
        return "com_github_adamws_kicad-kbplacer"
    return "kbplacer"


@pytest.fixture(scope="session")
def profile_args(request):
    if request.config.getoption("--profile"):
        return "-m", "cProfile"
    return None


@pytest.fixture(autouse=True, scope="session")
def prepare_ci_machine() -> None:
    # when running on CircleCI's Windows machine, there is annoying
    # notification po-up opened which may obstruct tested plugin window
    # when GUI testing. When running on Windows and CI, simulate single
    # 'ESC' press to close notification. Do this once before testing starts.
    if "CIRCLECI" in os.environ and sys.platform == "win32":
        VK_ESCAPE = 0x1B
        KEYEVENTF_EXTENDEDKEY = 0x0001
        KEYEVENTF_KEYUP = 0x0002
        user32 = ctypes.windll.user32
        user32.keybd_event(VK_ESCAPE, 0, KEYEVENTF_EXTENDEDKEY, 0)
        time.sleep(0.1)
        user32.keybd_event(VK_ESCAPE, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)


@pytest.fixture(autouse=True, scope="session")
def prepare_kicad_config() -> None:
    test_dir = Path(__file__).parent
    config_path = pcbnew.SETTINGS_MANAGER.GetUserSettingsPath()
    colors_path = f"{config_path}/colors"
    os.makedirs(colors_path, exist_ok=True)
    if not os.path.exists(f"{colors_path}/user.json"):
        shutil.copy(f"{test_dir}/colors/user.json", colors_path)


@pytest.fixture(autouse=True, scope="function")
def prepare_report_dir(tmpdir) -> None:
    os.mkdir(f"{tmpdir}/report")


def get_footprints_dir(request):
    test_dir = Path(request.module.__file__).parent
    return test_dir / "data/footprints/tests.pretty"


def get_references_dir(request, example_name, route_option, diode_option):
    test_dir = Path(request.module.__file__).parent
    major = KICAD_VERSION[0] if KICAD_VERSION else 0
    references_dir = test_dir / f"data/examples-references/kicad{major}"
    if not references_dir.exists():
        msg = f"Reference directory '{references_dir}' does not exists"
        raise RuntimeError(msg)
    return references_dir / f"{example_name}/{route_option}-{diode_option}"


def request_to_references_dir(request):
    _, test_parameters = request.node.name.split("[")
    example_name, route_option, diode_option, *_ = test_parameters[:-1].split(";")
    return get_references_dir(request, example_name, route_option, diode_option)


def merge_bbox(left: Box, right: Box) -> Box:
    """
    Merge bounding boxes in format (xmin, xmax, ymin, ymax)
    """
    return tuple([f(l, r) for l, r, f in zip(left, right, [min, max, min, max])])


def shrink_svg(svg: ET.ElementTree, margin: int = 0) -> None:
    """
    Shrink the SVG canvas to the size of the drawing.
    """
    root = svg.getroot()
    paths = svgpathtools.document.flattened_paths(root)

    if len(paths) == 0:
        return
    bbox = paths[0].bbox()
    for x in paths:
        bbox = merge_bbox(bbox, x.bbox())
    bbox = list(bbox)
    bbox[0] -= int(margin)
    bbox[1] += int(margin)
    bbox[2] -= int(margin)
    bbox[3] += int(margin)

    root.set(
        "viewBox",
        f"{bbox[0]} {bbox[2]} {bbox[1] - bbox[0]} {bbox[3] - bbox[2]}",
    )

    root.set("width", f"{float(bbox[1] - bbox[0])}mm")
    root.set("height", f"{float(bbox[3] - bbox[2])}mm")


def remove_empty_groups(root) -> None:
    name = "{http://www.w3.org/2000/svg}g"
    for elem in root.findall(name):
        if len(elem) == 0:
            root.remove(elem)
    for child in root:
        remove_empty_groups(child)


def remove_tags(root, name) -> None:
    for elem in root.findall(name):
        root.remove(elem)


# pcb plotting based on https://github.com/kitspace/kitspace-v2/tree/master/processor/src/tasks/processKicadPCB
# and https://gitlab.com/kicad/code/kicad/-/blob/master/demos/python_scripts_examples/plot_board.py
def generate_render(
    request,
    pcb_path: Union[str, os.PathLike],
    *,
    destination_dir: Union[str, os.PathLike] = "",
) -> None:
    pcb_path = Path(pcb_path)
    pcb_name = pcb_path.stem
    board = pcbnew.LoadBoard(str(pcb_path))
    if destination_dir == "":
        destination_dir = pcb_path.parent

    destination_dir = Path(destination_dir)
    layers_dir = destination_dir / f"{pcb_name}-layers"
    assert destination_dir.is_dir()
    assert not layers_dir.is_dir()

    os.mkdir(layers_dir)

    plot_layers = [
        "B_Cu",
        "F_Cu",
        "B_Silkscreen",
        "F_Silkscreen",
        "Edge_cuts",
        # on Kicad6 always printed in black, see: https://gitlab.com/kicad/code/kicad/-/issues/10293:
        "B_Mask",
        "F_Mask",
    ]
    plot_control = pcbnew.PLOT_CONTROLLER(board)
    plot_options = plot_control.GetPlotOptions()
    plot_options.SetOutputDirectory(destination_dir)
    plot_options.SetColorSettings(pcbnew.GetSettingsManager().GetColorSettings("user"))
    plot_options.SetPlotFrameRef(False)
    plot_options.SetSketchPadLineWidth(pcbnew.FromMM(0.35))
    plot_options.SetAutoScale(False)
    plot_options.SetMirror(False)
    plot_options.SetUseGerberAttributes(False)
    plot_options.SetScale(1)
    plot_options.SetUseAuxOrigin(True)
    plot_options.SetNegative(False)
    plot_options.SetPlotReference(True)
    plot_options.SetPlotValue(True)
    plot_options.SetPlotInvisibleText(False)
    if KICAD_VERSION >= (7, 0, 0):
        plot_options.SetDrillMarksType(pcbnew.DRILL_MARKS_NO_DRILL_SHAPE)
        plot_options.SetSvgPrecision(aPrecision=1)
    else:
        plot_options.SetDrillMarksType(pcbnew.PCB_PLOT_PARAMS.NO_DRILL_SHAPE)
        plot_options.SetSvgPrecision(aPrecision=1, aUseInch=False)

    plot_plan = []
    start = pcbnew.PCBNEW_LAYER_ID_START
    end = pcbnew.PCBNEW_LAYER_ID_START + pcbnew.PCB_LAYER_ID_COUNT
    for i in range(start, end):
        name = pcbnew.LayerName(i).replace(".", "_")
        if name in plot_layers:
            plot_plan.append((name, i))

    for layer_name, layer_id in plot_plan:
        plot_control.SetLayer(layer_id)
        if KICAD_VERSION >= (7, 0, 0):
            plot_control.OpenPlotfile(layer_name, pcbnew.PLOT_FORMAT_SVG)
        else:
            plot_control.OpenPlotfile(
                layer_name, pcbnew.PLOT_FORMAT_SVG, aSheetDesc=layer_name
            )
        plot_control.SetColorMode(True)
        plot_control.PlotLayer()
        plot_control.ClosePlot()

        filepath = os.path.join(destination_dir, f"{pcb_name}-{layer_name}.svg")
        tree = ET.parse(filepath)
        root = tree.getroot()
        # for some reason there is plenty empty groups in generated svg's (kicad bug?)
        # remove for clarity:
        remove_empty_groups(root)
        shrink_svg(tree, margin=1)
        tree.write(f"{layers_dir}/{layer_name}.svg")
        os.remove(f"{destination_dir}/{pcb_name}-{layer_name}.svg")

    if request.config.getoption("--save-results-as-reference"):
        references_dir = request_to_references_dir(request)
        references_dir.mkdir(parents=True, exist_ok=True)

        for layer_name, _ in plot_plan:
            if "Silkscreen" not in layer_name:
                filepath = os.path.join(layers_dir, f"{layer_name}.svg")
                shutil.copy(filepath, references_dir)

    new_tree = None
    new_root = None
    for i, (layer_name, _) in enumerate(plot_plan):
        filepath = os.path.join(layers_dir, f"{layer_name}.svg")
        tree = ET.parse(filepath)
        layer = tree.getroot()
        if i == 0:
            new_tree = tree
            new_root = layer
        else:
            for child in layer:
                new_root.append(child)

    # due to merging of multiple files we have multiple titles/descriptions,
    # remove all title/desc from root since we do not care about them:
    remove_tags(new_root, "{http://www.w3.org/2000/svg}title")
    remove_tags(new_root, "{http://www.w3.org/2000/svg}desc")

    shrink_svg(new_tree, margin=1)

    if not (destination_dir / "report").is_dir:
        os.mkdir(f"{destination_dir}/report")
    new_tree.write(f"{destination_dir}/report/{pcb_name}.svg")


def generate_drc(tmpdir, board_path: Union[str, os.PathLike]) -> None:
    if KICAD_VERSION in [(8, 0, 1), (8, 0, 2), (8, 0, 3), (8, 0, 4)]:
        # there is some kind of KiCad regression, this function
        # causes assertion fail randomly, see
        # https://gitlab.com/kicad/code/kicad/-/issues/17504
        return

    board_path = Path(board_path)
    board_name = board_path.stem

    board = pcbnew.LoadBoard(str(board_path))
    drc_path = tmpdir / f"report/{board_name}-drc.log"
    pcbnew.WriteDRCReport(board, drc_path, pcbnew.EDA_UNITS_MILLIMETRES, True)
    with open(drc_path, "r") as f:
        logger.debug(f.read())


def add_url_to_report(tmpdir, url: str) -> None:
    url_path = tmpdir / "report"
    urls = len(glob.glob(f"{url_path}/*url"))
    with open(url_path / f"{urls + 1}.url", "w") as f:
        f.write(url)


def pointMM(x, y) -> pcbnew.VECTOR2I:
    return pcbnew.VECTOR2I_MM(x, y)


def equal_ignore_order(a, b):
    unmatched = list(b)
    for element in a:
        try:
            unmatched.remove(element)
        except ValueError:
            return False
    return not unmatched


def _add_footprint(board, request, footprint, annotation) -> pcbnew.FOOTPRINT:
    library = get_footprints_dir(request)
    f = pcbnew.FootprintLoad(str(library), footprint)
    f.SetReference(annotation)
    board.Add(f)
    return f


def add_switch_footprint(
    board, request, ref_count, footprint: str = "SW_Cherry_MX_PCB_1.00u"
) -> pcbnew.FOOTPRINT:
    return _add_footprint(board, request, footprint, f"SW{ref_count}")


def add_diode_footprint(board, request, ref_count) -> pcbnew.FOOTPRINT:
    return _add_footprint(board, request, "D_SOD-323", f"D{ref_count}")


def add_led_footprint(board, request, ref_count) -> pcbnew.FOOTPRINT:
    # NOTE: should use different footprint but that is
    # not that important for testing
    return _add_footprint(board, request, "D_SOD-323", f"LED{ref_count}")


def get_track(board, start: pcbnew.VECTOR2I, end: pcbnew.VECTOR2I, layer):
    track = pcbnew.PCB_TRACK(board)
    track.SetWidth(pcbnew.FromMM(0.25))
    track.SetLayer(layer)
    if KICAD_VERSION < (7, 0, 0):
        track.SetStart(pcbnew.wxPoint(start.x, start.y))
        track.SetEnd(pcbnew.wxPoint(end.x, end.y))
    else:
        track.SetStart(start)
        track.SetEnd(end)
    return track


def add_track(board, start: pcbnew.VECTOR2I, end: pcbnew.VECTOR2I, layer):
    track = get_track(board, start, end, layer)
    board.Add(track)
    return track


def rotate(
    item: pcbnew.BOARD_ITEM,
    rotation_reference: pcbnew.VECTOR2I,
    angle: float,
) -> None:
    if KICAD_VERSION < (7, 0, 0):
        item.Rotate(
            pcbnew.wxPoint(rotation_reference.x, rotation_reference.y), angle * -10
        )
    else:
        item.Rotate(
            rotation_reference,
            pcbnew.EDA_ANGLE(angle * -1, pcbnew.DEGREES_T),
        )


def update_netinfo(board: pcbnew.BOARD, net: pcbnew.NETINFO_ITEM) -> None:
    if KICAD_VERSION < (8, 0, 0):
        net_info = board.GetNetInfo()
        net_info.AppendNet(net)


def to_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def image_to_base64(path):
    b64 = to_base64(path)
    mime = mimetypes.guess_type(path)
    return f"data:{mime[0]};base64,{b64}"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    pytest_html = item.config.pluginmanager.getplugin("html")
    outcome = yield
    report = outcome.get_result()
    extras = getattr(report, "extras", [])

    if report.when == "call" and not report.skipped:
        if tmpdir := item.funcargs.get("tmpdir"):
            images = glob.glob(f"{tmpdir}/report/*png") + glob.glob(
                f"{tmpdir}/report/*svg"
            )
            for f in images:
                render = image_to_base64(f)
                extras.append(pytest_html.extras.image(render))
            urls = glob.glob(f"{tmpdir}/report/*url")
            for url in urls:
                with open(url, "r") as f:
                    extras.append(pytest_html.extras.url(f.read()))
        report.extras = extras
