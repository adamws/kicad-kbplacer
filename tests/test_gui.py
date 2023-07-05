import ctypes
import logging
import pytest
import subprocess
import sys
import time

from ctypes.wintypes import HWND, DWORD, RECT
from pyvirtualdisplay.smartdisplay import DisplayTimeoutError, SmartDisplay
from PIL import ImageGrab


logger = logging.getLogger(__name__)


class LinuxVirtualScreenManager:
    def __enter__(self):
        self.display = SmartDisplay(backend="xvfb", size=(960, 640))
        self.display.start()
        return self

    def __exit__(self, *exc):
        self.display.stop()
        return False

    def screenshot(self, path):
        try:
            img = self.display.waitgrab(timeout=5)
            img.save(path)
            return True
        except DisplayTimeoutError as err:
            logger.error(err)
            return False


class HostScreenManager:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def screenshot(self, path):
        try:
            time.sleep(1)
            window_handle = find_window("kbplacer")
            window_rect = get_window_position(window_handle)
            img = ImageGrab.grab()
            if window_rect:
                img = img.crop(window_rect)
            img.save(path)
            return True
        except Exception as err:
            logger.error(err)
            return False


def find_window(name):
    if sys.platform == "win32":
        user32 = ctypes.windll.user32
        return user32.FindWindowW(None, name)
    else:
        return None


def get_window_position(window_handle):
    if sys.platform == "win32":
        dwmapi = ctypes.windll.dwmapi
        # based on https://stackoverflow.com/a/67137723
        rect = RECT()
        DMWA_EXTENDED_FRAME_BOUNDS = 9
        dwmapi.DwmGetWindowAttribute(
            HWND(window_handle),
            DWORD(DMWA_EXTENDED_FRAME_BOUNDS),
            ctypes.byref(rect),
            ctypes.sizeof(rect),
        )
        return (rect.left, rect.top, rect.right, rect.bottom)
    else:
        return None


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


def is_xvfb_avaiable() -> bool:
    try:
        p = subprocess.Popen(
            ["Xvfb", "-help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
        )
        _, _ = p.communicate()
        exit_code = p.returncode
        return exit_code == 0
    except FileNotFoundError:
        logger.warning("Xvfb was not found")
    return False


@pytest.fixture
def screen_manager():
    if sys.platform == "linux":
        if is_xvfb_avaiable():
            return LinuxVirtualScreenManager()
        else:
            return HostScreenManager()
    elif sys.platform == "win32":
        return HostScreenManager()
    else:
        pytest.skip(f"Platform '{sys.platform}' is not supported")


def test_gui(tmpdir, workdir, package_name, screen_manager) -> None:
    is_ok = True
    # for some reason, it occasionally may fail with
    # 'wxEntryStart failed, unable to initialize wxWidgets!' error, most likely
    # this is not related with plugin's code - try to get screenshot 3 times
    # to limit false positives
    max_attempts = 3
    for i in range(0, max_attempts):
        with screen_manager as mgr:
            p = run_kbplacer_process(workdir, package_name)
            is_ok = mgr.screenshot(f"{tmpdir}/screenshot.png")

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
