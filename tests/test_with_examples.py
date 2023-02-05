import pytest
import shutil
import subprocess


def run_kbplacer_process(tmpdir, route, diode_position, workdir, package_name):
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
    if diode_position:
        kbplacer_args.append("--diode-position")
        kbplacer_args.append(diode_position)

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
@pytest.mark.parametrize(("diode_position"), [None, "0,4.5,0,BACK"])
def test_with_examples(
    example, route, diode_position, tmpdir, request, workdir, package_name
):
    test_dir = request.fspath.dirname

    source_dir = "{}/../examples/{}".format(test_dir, example)
    shutil.copy("{}/keyboard-before.kicad_pcb".format(source_dir), tmpdir)
    shutil.copy("{}/kle-internal.json".format(source_dir), tmpdir)

    if route and diode_position != None:
        pytest.skip("Routing with non-default diode position not supported yet")

    run_kbplacer_process(tmpdir, route, diode_position, workdir, package_name)
