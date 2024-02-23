#!/bin/sh

# helper script for rebuilding images after kicad version update
# update tag values and Dockerfiles before usage

set -o nounset
set -o errexit

CUR_DIR="$(dirname $(readlink -f "$0"))"

build_and_push() {
  docker build -t admwscki/kicad-kbplacer-primary:$1 \
    --no-cache --progress=plain -f $CUR_DIR/$2 .
  docker push admwscki/kicad-kbplacer-primary:$1
}

build_and_push 7.0.11-focal focal/kicad7.Dockerfile
build_and_push 7.0.11-mantic mantic/kicad7.Dockerfile
