import os
import pytest
import shutil
import subprocess
from pathlib import Path


def run_kbplacer_process(tmpdir):
    layout_file = "{}/kle-internal.json".format(tmpdir)
    pcb_path = "{}/keyboard-before.kicad_pcb".format(tmpdir)

    home_directory = Path.home()
    workdir = f"{home_directory}/.local/share/kicad/6.0/3rdparty/plugins"
    package_name = "com_github_adamws_kicad-kbplacer"
    kbplacer_args = [
        "python3",
        "-m",
        package_name,
        "-l",
        layout_file,
        "-b",
        pcb_path,
        "--route",
    ]
    p = subprocess.Popen(
        kbplacer_args,
        cwd=workdir,
    )
    p.communicate()
    if p.returncode != 0:
        raise Exception("Switch placement failed")


@pytest.mark.parametrize(
    ("example"),
    ["2x2", "3x2-sizes", "2x3-rotations", "1x4-rotations-90-step"],
)
def test_with_examples(example, tmpdir, request):
    test_dir = request.fspath.dirname

    source_dir = "{}/../examples/{}".format(test_dir, example)
    shutil.copy("{}/keyboard-before.kicad_pcb".format(source_dir), tmpdir)
    shutil.copy("{}/kle-internal.json".format(source_dir), tmpdir)
    run_kbplacer_process(tmpdir)
