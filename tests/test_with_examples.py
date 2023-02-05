import pytest
import shutil
import subprocess


def run_kbplacer_process(tmpdir, route, workdir, package_name):
    layout_file = "{}/kle-internal.json".format(tmpdir)
    pcb_path = "{}/keyboard-before.kicad_pcb".format(tmpdir)

    kbplacer_args = [
        "python3",
        "-m",
        package_name,
        "-l",
        layout_file,
        "-b",
        pcb_path,
    ]
    if route:
        kbplacer_args.append("--route")

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
@pytest.mark.parametrize(("route"), [False, True])
def test_with_examples(example, route, tmpdir, request, workdir, package_name):
    test_dir = request.fspath.dirname

    source_dir = "{}/../examples/{}".format(test_dir, example)
    shutil.copy("{}/keyboard-before.kicad_pcb".format(source_dir), tmpdir)
    shutil.copy("{}/kle-internal.json".format(source_dir), tmpdir)

    run_kbplacer_process(tmpdir, route, workdir, package_name)
