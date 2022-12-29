import base64
import os
import pcbnew
import pytest
import svgpathtools

import xml.etree.ElementTree as ET
from typing import Callable, Tuple, Union

Numeric = Union[int, float]
Box = Tuple[Numeric, Numeric, Numeric, Numeric]


# pcb plotting based on https://github.com/kitspace/kitspace-v2/tree/master/processor/src/tasks/processKicadPCB


def merge_bbox(left: Box, right: Box) -> Box:
    """
    Merge bounding boxes in format (xmin, xmax, ymin, ymax)
    """
    return tuple([f(l, r) for l, r, f in zip(left, right, [min, max, min, max])])  #


def shrink_svg(svg: ET.ElementTree) -> None:
    """
    Shrink the SVG canvas to the size of the drawing.
    """
    root = svg.getroot()
    paths = svgpathtools.document.flattened_paths(ET.fromstring(ET.tostring(root)))

    if len(paths) == 0:
        return
    bbox = paths[0].bbox()
    for x in paths:
        bbox = merge_bbox(bbox, x.bbox())
    bbox = list(bbox)

    root.set(
        "viewBox",
        "{} {} {} {}".format(bbox[0], bbox[2], bbox[1] - bbox[0], bbox[3] - bbox[2]),
    )
    root.set("width", str(int(bbox[1] - bbox[0])))
    root.set("height", str(int(bbox[3] - bbox[2])))


def generate_render(tmpdir):
    project_name = "keyboard-before"
    pcb_path = "{}/{}.kicad_pcb".format(tmpdir, project_name)
    board = pcbnew.LoadBoard(pcb_path)

    plot_control = pcbnew.PLOT_CONTROLLER(board)
    plot_options = plot_control.GetPlotOptions()
    plot_options.SetOutputDirectory(tmpdir)
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
        plot_plan.append((name, i))

    for (layer_name, layer_id) in plot_plan:
        plot_control.SetLayer(layer_id)
        plot_control.OpenPlotfile(layer_name, pcbnew.PLOT_FORMAT_SVG, aSheetDesc=layer_name)
        plot_control.PlotLayer()
        plot_control.ClosePlot()

    new_tree = None
    new_root = None
    for i, (layer_name, _) in enumerate(plot_plan):
        filepath = os.path.join(tmpdir, f"{project_name}-{layer_name}.svg")
        tree = ET.parse(filepath)
        layer = tree.getroot()
        if i == 0:
            new_tree = tree
            new_root = layer
        else:
            for child in layer:
                new_root.append(child)

    shrink_svg(new_tree)
    new_tree.write(f"{tmpdir}/render.svg")


def to_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def svg_to_base64_html(path):
    b64 = to_base64(path)
    return '<div class="image"><img src="data:image/svg+xml;base64,{}"></div>'.format(
        b64
    )


@pytest.mark.hookwrapper
def pytest_runtest_makereport(item, call):
    pytest_html = item.config.pluginmanager.getplugin("html")
    outcome = yield
    report = outcome.get_result()
    extra = getattr(report, "extra", [])

    if report.when == "call":
        tmpdir = item.funcargs["tmpdir"]
        generate_render(tmpdir)
        render = svg_to_base64_html(os.path.join(tmpdir, "render.svg"))
        extra.append(pytest_html.extras.html(render))
        report.extra = extra
