import logging
import pytest
import subprocess
import sys

from pyvirtualdisplay.smartdisplay import DisplayTimeoutError, SmartDisplay


logger = logging.getLogger(__name__)


def run_kbplacer_process(workdir, package_name):
    kbplacer_args = [
        "python3",
        "-m",
        package_name,
        "gui",
        "-b",
        "",  # board path is required but it is not important in this test
    ]

    p = subprocess.Popen(
        kbplacer_args,
        cwd=workdir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    return p


@pytest.mark.skipif(sys.platform != "linux", reason="GUI test available only on linux")
def test_gui(tmpdir, workdir, package_name) -> None:
    is_ok = True
    # for some reason, it occasionally may fail with
    # 'wxEntryStart failed, unable to initialize wxWidgets!' error, most likely
    # this is not related with plugin's code - try to get screenshot 3 times
    # to limit false positives
    max_attempts = 3
    for i in range(0, max_attempts):
        with SmartDisplay(backend="xvfb", size=(960, 640)) as disp:
            p = run_kbplacer_process(workdir, package_name)
            try:
                img = disp.waitgrab(timeout=5)
                img.save(f"{tmpdir}/screenshot.png")
                is_ok = True
            except DisplayTimeoutError:
                is_ok = False

            try:
                outs, errs = p.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                p.kill()
                outs, errs = p.communicate()

            logger.info(outs)
            logger.info(errs)
            if is_ok:
                break
            else:
                logger.info(f"Failed to get screenshot, attempt {i+1}/{max_attempts}")

    assert is_ok
