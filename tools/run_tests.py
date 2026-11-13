# SPDX-FileCopyrightText: 2025 adamws <adamws@users.noreply.github.com>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import subprocess
import sys
from pathlib import Path


def main():
    project_root = Path(__file__).resolve().parent.parent
    test_dir = project_root / "tools" / "tests"

    os.chdir(test_dir)

    # Run pytest with any additional arguments
    # Override the main project's pytest.ini settings that conflict with tools testing
    args = [
        "python",
        "-m",
        "pytest",
        ".",
        "--override-ini=addopts=--tb=short",
        "--no-header",
        f"--html={project_root / 'report-tools.html'}",
        f"--css={project_root / 'tests' / 'report' / 'style.css'}",
        "--self-contained-html",
    ] + sys.argv[1:]
    return subprocess.run(args, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
