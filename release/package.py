import argparse
import glob
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from textwrap import dedent
from typing import TypedDict

READ_SIZE = 65536

DIRNAME = os.path.abspath(os.path.dirname(__file__))
PLUGIN_NAME = "kbplacer"


class JsonMetadata(TypedDict):
    sha256: str
    update_time_utc: str
    update_timestamp: int


class PackageMetadata(TypedDict):
    download_sha256: str
    download_size: int
    install_size: int


def zip_directory(directory, output_zip) -> None:
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(directory):
            for file in files:
                file_path = os.path.join(root, file)
                zipf.write(file_path, os.path.relpath(file_path, directory))


def create_resources_package(identifier: str, output: str) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        dst = f"{tmpdir}/{identifier}"
        os.makedirs(dst)
        shutil.copy(f"{DIRNAME}/../resources/icon.png", dst)
        zip_directory(tmpdir, output)


def getsha256(filename) -> str:
    hash = hashlib.sha256()
    with io.open(filename, "rb") as f:
        while data := f.read(READ_SIZE):
            hash.update(data)
    return hash.hexdigest()


def get_package_metadata(filename) -> PackageMetadata:
    z = zipfile.ZipFile(filename, "r")
    install_size = sum(entry.file_size for entry in z.infolist() if not entry.is_dir())
    return {
        "download_sha256": getsha256(filename),
        "download_size": os.path.getsize(filename),
        "install_size": install_size,
    }


def get_json_metadata(filename) -> JsonMetadata:
    mtime = os.path.getmtime(filename)
    dt = datetime.fromtimestamp(mtime)
    return {
        "sha256": getsha256(filename),
        "update_time_utc": dt.strftime("%Y-%m-%d %H:%M:%S"),
        "update_timestamp": int(mtime),
    }


def build_repository(input_dir: str, output_dir: str):
    package = glob.glob(f"{input_dir}/*.zip")[0]
    package_name = Path(package).name
    shutil.copy(f"{package}", f"{output_dir}/")

    with open(f"{input_dir}/metadata.json", "r") as f:
        metadata = json.load(f)

    repository_url = "https://adamws.github.io/kicad-kbplacer"

    package_version = metadata["versions"][0]
    package_version["download_url"] = f"{repository_url}/{package_name}"

    packages = {"packages": [metadata]}

    packages_out = f"{output_dir}/packages.json"
    with open(packages_out, "w", encoding="utf-8") as f:
        json.dump(packages, f, indent=4)

    resources_package = f"{output_dir}/resources.zip"
    create_resources_package(metadata["identifier"], resources_package)

    repository = {
        "$schema": "https://gitlab.com/kicad/code/kicad/-/raw/master/kicad/pcm/schemas/pcm.v1.schema.json#/definitions/Repository",
        "maintainer": metadata["author"],
        "name": f"{PLUGIN_NAME} development repository",
        "packages": {"url": f"{repository_url}/packages.json"},
        "resources": {"url": f"{repository_url}/resources.zip"},
    }

    repository["packages"].update(get_json_metadata(packages_out))
    repository["resources"].update(get_json_metadata(resources_package))
    with open(f"{output_dir}/repository.json", "w", encoding="utf-8") as f:
        json.dump(repository, f, indent=4)

    css: str = "p {margin: 0;}"
    html_index_template: str = f"""\
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>kicad-kbplacer repository</title>
        <link rel="icon" href="data:,">
        <style>{css}</style>
      </head>
      <body>
        <p>Add <i>{repository_url}/repository.json</i> to KiCad's repository list to install these files with PCM:</p>
        <p>Repository: <a href="{repository_url}/repository.json">repository.json</a></p>
        <p>Packages: <a href="{repository_url}/packages.json">packages.json</a></p>
        <p>Plugin: <a href="{repository_url}/{package_name}">{package_name}</a></p>
        <p>Resources: <a href="{repository_url}/resources.zip">resources.zip</a></p>
        <br>
        <p>Go back to <a href="https://github.com/adamws/kicad-kbplacer">project site</a></p>
      </body>
    </html>
    """

    with open(f"{output_dir}/index.html", "w") as f:
        f.write(dedent(html_index_template))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Plugin packaging utilities",
    )
    parser.add_argument(
        "-i",
        "--input",
        default=Path("dist"),
        type=Path,
        help="Distribution directory",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=Path(f"{DIRNAME}/output"),
        type=Path,
        help="Output directory path",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Override output directory if already exists",
    )

    args = parser.parse_args()

    input_dir = args.input
    output_dir = args.output
    force = args.force

    if force:
        shutil.rmtree(output_dir, ignore_errors=True)
    elif output_dir.is_dir():
        print(f"Output directory '{output_dir}' already exists, exiting...")
        sys.exit(1)

    os.makedirs(output_dir)

    build_repository(input_dir, output_dir)
