import glob
import hashlib
import io
import os
import re
import shutil
import subprocess
import tempfile
import zipfile

from jinja2 import Template


READ_SIZE = 65536

DIRNAME = os.path.abspath(os.path.dirname(__file__))
ZIP_PACKAGE = f"{DIRNAME}/kicad-kbplacer.zip"
METADATA_IN = f"{DIRNAME}/metadata.json.in"
METADATA_OUT = f"{DIRNAME}/metadata.json"
VERSION_FILE = f"{DIRNAME}/version.txt"

def get_version() -> str:
    p = subprocess.Popen(
        ["git", "describe", "--long", "--tags", "--dirty", "--always"],
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


def create_package(output: str) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(f"{tmpdir}/plugins")
        os.makedirs(f"{tmpdir}/resources")
        sources = glob.glob(f"{DIRNAME}/../kbplacer/*.py")
        images = glob.glob(f"{DIRNAME}/../kbplacer/*.png")
        for f in sources + images:
            shutil.copy(f, f"{tmpdir}/plugins")
        shutil.copy(VERSION_FILE, f"{tmpdir}/plugins")
        shutil.copy(f"{DIRNAME}/../resources/icon.png", f"{tmpdir}/resources")
        shutil.copy(METADATA_OUT, f"{tmpdir}")

        zip_directory(tmpdir, output)


def print_zip_contents(zip_path):
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


def get_stats(filename):
    instsize = 0
    z = zipfile.ZipFile(filename, "r")
    for entry in z.infolist():
        if not entry.is_dir():
            instsize += entry.file_size
    return getsha256(filename), os.path.getsize(filename), instsize


if __name__ == "__main__":
    with open(METADATA_IN) as f:
        template = Template(f.read())
        version = get_version()
        print(f"version: {version}")
        with open(VERSION_FILE, "w") as f:
            f.write(version)
        status = get_status(version)
        print(f"status: {status}")
        version_simple = get_simplified_version(version)
        print(f"version_simple: {version_simple}")
        template.stream(version=version_simple, status=status).dump(METADATA_OUT)

    create_package(ZIP_PACKAGE)

    print("")
    print_zip_contents(ZIP_PACKAGE)

    print("")
    print("Calculate package metadata:")
    sha, size, instsize = get_stats(ZIP_PACKAGE)
    print(f"sha: {sha}")
    print(f"size: {size}")
    print(f"intsize: {instsize}")

    os.remove(METADATA_OUT)
    os.remove(VERSION_FILE)
