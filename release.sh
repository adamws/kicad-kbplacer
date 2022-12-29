#!/bin/sh

set -o nounset
set -o errexit

NAME="kicad-kbplacer"
OUTPUT_DIR="release"

mkdir -p ${OUTPUT_DIR}/plugins ${OUTPUT_DIR}/resources

cp -r kbplacer/*.py ${OUTPUT_DIR}/plugins/
cp resources/icon.png ${OUTPUT_DIR}/resources/icon.png
cp metadata.json ${OUTPUT_DIR}/metadata.json

cd ${OUTPUT_DIR}
zip -r ./${NAME}.zip ./plugins ./resources ./metadata.json
