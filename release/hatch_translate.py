import os
import shutil
import subprocess
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class TranslateHook(BuildHookInterface):
    DIRNAME = os.path.abspath(os.path.dirname(__file__))

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        self.app.display_info("Running translate hook...")
        try:
            locale_dir = f"{self.directory}/locale"
            shutil.rmtree(locale_dir, ignore_errors=True)
            os.makedirs(locale_dir)
            self.generate_translations(locale_dir)
        except Exception as e:
            self.app.abort(str(e))
        self.app.display_info("...done")

    def finalize(
        self, version: str, build_data: dict[str, Any], artifact_path: str
    ) -> None:
        locale_dir = f"{self.directory}/locale"
        shutil.rmtree(locale_dir, ignore_errors=True)

    def generate_translations(self, locale_directory):
        install_languages = []
        with open(f"{self.DIRNAME}/../translation/pofiles/LINGUAS_INSTALL") as f:
            languages = f.readlines()
            install_languages = [
                lang.strip() for lang in languages if not lang.startswith("#")
            ]
        for lang in install_languages:
            po_file = f"{self.DIRNAME}/../translation/pofiles/{lang}.po"
            dst = f"{locale_directory}/{lang}/LC_MESSAGES"
            os.makedirs(dst)
            self.app.display_info(f"\t{lang}", end="")
            res = subprocess.run(
                ["msgfmt", "--statistics", po_file, "-o", f"{dst}/kbplacer.mo"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            msgfmt_output = res.stdout.decode("utf-8").strip()
            status = "ok" if res.returncode == 0 else "nok"
            self.app.display_info(f": {status}: {msgfmt_output}")
