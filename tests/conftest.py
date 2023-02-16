import base64
import logging
import os
import pcbnew
import pytest
import shutil
import svgpathtools

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable, Tuple, Union


Numeric = Union[int, float]
Box = Tuple[Numeric, Numeric, Numeric, Numeric]


logger = logging.getLogger(__name__)


def pytest_addoption(parser):
    parser.addoption(
        "--test-plugin-installation",
        action="store_true",
        help="Run tests using ~/.local/hsare/kicad/6.0/3rdparty/plugins instance instead of local one",
        default=False,
    )
    parser.addoption(
        "--save-results-as-reference",
        action="store_true",
        help="Save test results as expected results."
        "This option is for updating expected results and NOT for testing",
        default=False,
    )


@pytest.fixture(scope="session")
def workdir(request):
    if request.config.getoption("--test-plugin-installation"):
        home_directory = Path.home()
        return f"{home_directory}/.local/share/kicad/6.0/3rdparty/plugins"
    return Path(os.path.realpath(__file__)).parents[1]


@pytest.fixture(scope="session")
def package_name(request):
    if request.config.getoption("--test-plugin-installation"):
        return "com_github_adamws_kicad-kbplacer"
    return "kbplacer"


@pytest.fixture(autouse=True, scope="session")
def prepare_kicad_config(request):
    config_path = pcbnew.SETTINGS_MANAGER.GetUserSettingsPath()
    colors_path = config_path + "/colors"
    os.makedirs(colors_path, exist_ok=True)
    if not os.path.exists(colors_path + "/user.json"):
        shutil.copy("./colors/user.json", colors_path)


def get_references_dir(request):
    test_dir = Path(request.module.__file__).parent
    test_name, test_parameters = request.node.name.split("[")
    example_name, route_option, diode_option = test_parameters[:-1].split(";")
    references_dir = (
        test_dir / "data" / test_name / example_name / f"{route_option}-{diode_option}"
    )
    return references_dir


def merge_bbox(left: Box, right: Box) -> Box:
    """
    Merge bounding boxes in format (xmin, xmax, ymin, ymax)
    """
    return tuple([f(l, r) for l, r, f in zip(left, right, [min, max, min, max])])


def shrink_svg(svg: ET.ElementTree, margin: int) -> None:
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
        "{} {} {} {}".format(bbox[0], bbox[2], bbox[1] - bbox[0], bbox[3] - bbox[2]),
    )
    root.set("width", str(float((bbox[1] - bbox[0]) / 1000)) + "cm")
    root.set("height", str(float((bbox[3] - bbox[2]) / 1000)) + "cm")


def remove_empty_groups(root):
    name = "{http://www.w3.org/2000/svg}g"
    for elem in root.findall(name):
        if len(elem) == 0:
            root.remove(elem)
    for child in root:
        remove_empty_groups(child)


def remove_tags(root, name):
    for elem in root.findall(name):
        root.remove(elem)


# pcb plotting based on https://github.com/kitspace/kitspace-v2/tree/master/processor/src/tasks/processKicadPCB
# and https://gitlab.com/kicad/code/kicad/-/blob/master/demos/python_scripts_examples/plot_board.py
def generate_render(tmpdir, request):
    project_name = "keyboard-before"
    pcb_path = "{}/{}.kicad_pcb".format(tmpdir, project_name)
    board = pcbnew.LoadBoard(pcb_path)

    plot_layers = [
        "B_Cu",
        "F_Cu",
        "B_Silkscreen",
        "F_Silkscreen",
        "Edge_cuts",
        "B_Mask",  # always printed in black, see: https://gitlab.com/kicad/code/kicad/-/issues/10293
        "F_Mask",
    ]
    plot_control = pcbnew.PLOT_CONTROLLER(board)
    plot_options = plot_control.GetPlotOptions()
    plot_options.SetOutputDirectory(tmpdir)
    plot_options.SetColorSettings(pcbnew.GetSettingsManager().GetColorSettings("user"))
    plot_options.SetPlotFrameRef(False)
    plot_options.SetSketchPadLineWidth(pcbnew.FromMM(0.35))
    plot_options.SetAutoScale(False)
    plot_options.SetMirror(False)
    plot_options.SetUseGerberAttributes(False)
    plot_options.SetExcludeEdgeLayer(True)
    plot_options.SetScale(1)
    plot_options.SetUseAuxOrigin(True)
    plot_options.SetNegative(False)
    plot_options.SetPlotReference(True)
    plot_options.SetPlotValue(True)
    plot_options.SetPlotInvisibleText(False)
    plot_options.SetDrillMarksType(pcbnew.PCB_PLOT_PARAMS.NO_DRILL_SHAPE)
    plot_options.SetSvgPrecision(aPrecision=1, aUseInch=False)

    plot_plan = []
    start = pcbnew.PCBNEW_LAYER_ID_START
    end = pcbnew.PCBNEW_LAYER_ID_START + pcbnew.PCB_LAYER_ID_COUNT
    for i in range(start, end):
        name = pcbnew.LayerName(i).replace(".", "_")
        if name in plot_layers:
            plot_plan.append((name, i))

    for (layer_name, layer_id) in plot_plan:
        plot_control.SetLayer(layer_id)
        plot_control.OpenPlotfile(
            layer_name, pcbnew.PLOT_FORMAT_SVG, aSheetDesc=layer_name
        )
        plot_control.SetColorMode(True)
        plot_control.PlotLayer()
        plot_control.ClosePlot()

        filepath = os.path.join(tmpdir, f"{project_name}-{layer_name}.svg")
        tree = ET.parse(filepath)
        root = tree.getroot()
        # for some reason there is plenty empty groups in generated svg's (kicad bug?)
        # remove for clarity:
        remove_empty_groups(root)
        shrink_svg(tree, margin=1000)
        tree.write(f"{tmpdir}/{layer_name}.svg")
        os.remove(f"{tmpdir}/{project_name}-{layer_name}.svg")

    if request.config.getoption("--save-results-as-reference"):
        references_dir = get_references_dir(request)
        references_dir.mkdir(parents=True, exist_ok=True)

        for i, (layer_name, _) in enumerate(plot_plan):
            filepath = os.path.join(tmpdir, f"{layer_name}.svg")
            shutil.copy(filepath, references_dir)

    new_tree = None
    new_root = None
    for i, (layer_name, _) in enumerate(plot_plan):
        filepath = os.path.join(tmpdir, f"{layer_name}.svg")
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

    shrink_svg(new_tree, margin=1000)
    new_tree.write(f"{tmpdir}/render.svg")


def to_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def svg_to_base64_html(path):
    b64 = to_base64(path)
    return '<div class="image"><img src="data:image/svg+xml;base64,{}"></div>'.format(
        b64
    )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    pytest_html = item.config.pluginmanager.getplugin("html")
    outcome = yield
    report = outcome.get_result()
    extra = getattr(report, "extra", [])

    if report.when == "call" and not report.skipped:
        tmpdir = item.funcargs["tmpdir"]
        render = svg_to_base64_html(os.path.join(tmpdir, "render.svg"))
        extra.append(pytest_html.extras.html(render))
        report.extra = extra
