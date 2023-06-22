import glob
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile

from datetime import datetime
from textwrap import dedent
from typing import TypedDict


READ_SIZE = 65536

DIRNAME = os.path.abspath(os.path.dirname(__file__))
PLUGIN_NAME = "kicad-kbplacer"


class JsonMetadata(TypedDict):
    sha256: str
    update_time_utc: str
    update_timestamp: int


class PackageMetadata(TypedDict):
    download_sha256: str
    download_size: int
    install_size: int


def get_version() -> str:
    p = subprocess.Popen(
        ["git", "describe", "--tags", "--dirty", "--always"],
        cwd=DIRNAME,
        stdout=subprocess.PIPE,
    )
    output = p.communicate()[0]
    if p.returncode != 0:
        raise Exception("Failed to get git version")
    output = output.decode("utf-8").strip()
    return output


def get_simplified_version(version) -> str:
    # version in metadata needs to match simplified format where git digest and 'dirty'
    # status would not match. This function converts version to simple form:
    version_simple = ""
    dot_count = 0
    for char in re.sub(r"[^\d.]", "", version.replace("-", ".")):
        if char == ".":
            dot_count += 1
            if dot_count > 2:
                continue
        version_simple += char
    sections = version_simple.split(".")
    last_section = sections[-1][:6]
    sections[-1] = last_section
    version_simple = ".".join(sections)
    return version_simple


def get_status(version: str) -> str:
    pattern = r"v\d.\d$"
    if re.match(pattern, version):
        return "stable"
    else:
        return "development"


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


def create_plugin_package(version, metadata, output: str) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(f"{tmpdir}/plugins")
        os.makedirs(f"{tmpdir}/resources")
        sources = glob.glob(f"{DIRNAME}/../kbplacer/*.py")
        images = glob.glob(f"{DIRNAME}/../kbplacer/*.png")
        for f in sources + images:
            shutil.copy(f, f"{tmpdir}/plugins")
        shutil.copy(f"{DIRNAME}/../resources/icon.png", f"{tmpdir}/resources")

        with open(f"{tmpdir}/plugins/version.txt", "w") as f:
            f.write(version)
        with open(f"{tmpdir}/metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=4)

        zip_directory(tmpdir, output)


def print_zip_contents(zip_path) -> None:
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        print(f"Contents of '{zip_path}':")
        for file_name in zip_ref.namelist():
            print(file_name)


def getsha256(filename) -> str:
    hash = hashlib.sha256()
    with io.open(filename, "rb") as f:
        data = f.read(READ_SIZE)
        while data:
            hash.update(data)
            data = f.read(READ_SIZE)
    return hash.hexdigest()


def get_package_metadata(filename) -> PackageMetadata:
    install_size = 0
    z = zipfile.ZipFile(filename, "r")
    for entry in z.infolist():
        if not entry.is_dir():
            install_size += entry.file_size
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


if __name__ == "__main__":
    version = get_version()
    status = get_status(version)
    version_simple = get_simplified_version(version)

    print(f"version: {version}")
    print(f"status: {status}")
    print(f"version_simple: {version_simple}")

    repository_url = "https://adamws.github.io/kicad-kbplacer"
    author = {
        "contact": {"web": "https://adamws.github.io"},
        "name": "adamws",
    }

    metadata = {
        "$schema": "https://go.kicad.org/pcm/schemas/v1",
        "name": "Keyboard footprints placer",
        "description": "Plugin for mechanical keyboard design",
        "description_full": (
            "Plugin for mechanical keyboard design.\n"
            "It features automatic key placement based on popular layout description from www.keyboard-layout-editor.com"
        ),
        "identifier": "com.github.adamws.kicad-kbplacer",
        "type": "plugin",
        "author": author,
        "license": "GPL-3.0",
        "resources": {"homepage": repository_url},
        "tags": ["keyboard"],
        "versions": [
            {
                "version": version_simple,
                "status": status,
                "kicad_version": "6.0",
            }
        ],
    }

    output_dir = f"{DIRNAME}/output"
    shutil.rmtree(output_dir, ignore_errors=True)
    os.makedirs(output_dir)

    plugin_package = f"{output_dir}/{PLUGIN_NAME}.zip"
    create_plugin_package(version, metadata, plugin_package)
    print_zip_contents(plugin_package)

    package_version = metadata["versions"][0]
    package_version["download_url"] = f"{repository_url}/{PLUGIN_NAME}.zip"
    package_version.update(get_package_metadata(plugin_package))
    print(f"package details: {package_version}")

    packages = {"packages": [metadata]}

    packages_out = f"{output_dir}/packages.json"
    with open(packages_out, "w", encoding="utf-8") as f:
        json.dump(packages, f, indent=4)

    resources_package = f"{output_dir}/resources.zip"
    create_resources_package(metadata["identifier"], resources_package)

    repository = {
        "$schema": "https://gitlab.com/kicad/code/kicad/-/raw/master/kicad/pcm/schemas/pcm.v1.schema.json#/definitions/Repository",
        "maintainer": author,
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
        <p>Plugin: <a href="{repository_url}/{PLUGIN_NAME}.zip">{PLUGIN_NAME}.zip</a> version {version}</p>
        <p>Resources: <a href="{repository_url}/resources.zip">resources.zip</a></p>
      </body>
    </html>
    """

    with open(f"{output_dir}/index.html", "w") as f:
        f.write(dedent(html_index_template))
