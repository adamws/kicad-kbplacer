import os
import pytest
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
