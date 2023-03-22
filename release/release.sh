#!/bin/sh

set -o nounset
set -o errexit

SCRIPT_PATH=$(dirname "$0")
OUTPUT_DIR="${SCRIPT_PATH}/tmp-release"
NAME="kicad-kbplacer"

mkdir -p ${OUTPUT_DIR}/plugins ${OUTPUT_DIR}/resources

cp -r ${SCRIPT_PATH}/../kbplacer/*.py ${OUTPUT_DIR}/plugins/
cp ${SCRIPT_PATH}/../kbplacer/icon.png ${OUTPUT_DIR}/plugins/
cp ${SCRIPT_PATH}/../resources/icon.png ${OUTPUT_DIR}/resources/icon.png
cp ${SCRIPT_PATH}/../metadata.json ${OUTPUT_DIR}/metadata.json

(cd ${OUTPUT_DIR} && zip -r ../${NAME}.zip ./plugins ./resources ./metadata.json)
rm -rf ${OUTPUT_DIR}

python ${SCRIPT_PATH}/stats.py ${SCRIPT_PATH}/${NAME}.zip
