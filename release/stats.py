import hashlib
import io
import os
import sys
import zipfile


READ_SIZE = 65536


def getsha256(filename):
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
    sha, size, instsize = get_stats(sys.argv[1])
    print(f"sha: {sha}")
    print(f"size: {size}")
    print(f"intsize: {instsize}")
