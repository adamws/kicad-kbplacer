import os
import pcbnew
import pytest
import re
import shutil
import subprocess


def run_keyautoplace_process(tmpdir):
    layout_file = "kle-internal.json"
    pcb_path = "{}/keyboard-before.kicad_pcb".format(tmpdir)

    script_path = os.path.dirname(os.path.abspath(__file__)) + "/../keyautoplace.py"
    keyautoplace_args = [
        "python3",
        script_path,
        "-l",
        layout_file,
        "-b",
        pcb_path,
        "--route",
    ]
    p = subprocess.Popen(
        keyautoplace_args,
        cwd=tmpdir,
    )
    p.communicate()
    if p.returncode != 0:
        raise Exception("Switch placement failed")


def add_edge_cuts(tmpdir):
    pcb_path = "{}/keyboard-before.kicad_pcb".format(tmpdir)
    try:
        board = pcbnew.LoadBoard(pcb_path)
        positions = [
            module.GetPosition()
            for module in board.GetModules()
            if re.match(r"^SW\d+$", module.GetReference())
        ]
        xvals = [position.x for position in positions]
        yvals = [position.y for position in positions]
        xmin = min(xvals) - pcbnew.FromMM(12)
        xmax = max(xvals) + pcbnew.FromMM(12)
        ymin = min(yvals) - pcbnew.FromMM(12)
        ymax = max(yvals) + pcbnew.FromMM(12)
        corners = [
            pcbnew.wxPoint(xmin, ymin),
            pcbnew.wxPoint(xmax, ymin),
            pcbnew.wxPoint(xmax, ymax),
            pcbnew.wxPoint(xmin, ymax),
        ]
        for i in range(len(corners)):
            start = corners[i]
            end = corners[(i + 1) % len(corners)]
            segment = pcbnew.DRAWSEGMENT(board)
            segment.SetLayer(pcbnew.Edge_Cuts)
            segment.SetStart(start)
            segment.SetEnd(end)
            board.Add(segment)

        pcbnew.Refresh()
        pcbnew.SaveBoard(pcb_path, board)
    except Exception as err:
        raise Exception("Adding egde cuts failed") from err


# Would be better to export same way as KiCad's export->SVG but
# API for that isn't directly exposed to python. Instead of two images
# it would be easier to have all layers in one.
# For now let's stick to pcbdraw utility.
def generate_render(tmpdir):
    # without edge cuts pcbdraw isn't working
    add_edge_cuts(tmpdir)

    pcb_path = "{}/keyboard-before.kicad_pcb".format(tmpdir)

    for side in ["front", "back"]:
        render_path = "{}/{}.svg".format(tmpdir, side)

        render_args = ["pcbdraw", "--filter", '""', pcb_path, render_path]
        if side == "back":
            render_args.append("--back")
            render_args.append("--mirror")

        p = subprocess.Popen(render_args)
        p.communicate()
        if p.returncode != 0:
            raise Exception("Preview render failed")


@pytest.mark.parametrize(
    ("example"),
    ["2x2", "3x2-sizes", "2x3-rotations", "1x4-rotations-90-step"],
)
def test_with_examples(example, tmpdir, request):
    test_dir = request.fspath.dirname

    source_dir = "{}/../examples/{}".format(test_dir, example)
    shutil.copy("{}/keyboard-before.kicad_pcb".format(source_dir), tmpdir)
    shutil.copy("{}/kle-internal.json".format(source_dir), tmpdir)
    run_keyautoplace_process(tmpdir)
    generate_render(tmpdir)
