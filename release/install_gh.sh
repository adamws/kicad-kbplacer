#!/bin/sh

# script for installing GitHub's CLI on circleci machines

set -o nounset
set -o errexit

VERSION=2.40.0
ARCHIVE=gh_${VERSION}_linux_amd64.tar.gz
CHECKSUMS=gh_${VERSION}_checksums.txt

INSTALL_PATH=$HOME/.local/bin

curl -OL https://github.com/cli/cli/releases/download/v${VERSION}/${ARCHIVE}
curl -OL https://github.com/cli/cli/releases/download/v${VERSION}/${CHECKSUMS}

sha256sum --ignore-missing -c ${CHECKSUMS}
rm ${CHECKSUMS}

tar -xzvf ${ARCHIVE}
rm -rf ${ARCHIVE}

mv gh_${VERSION}_linux_amd64/bin/gh ${INSTALL_PATH}/gh
chmod +x ${INSTALL_PATH}/gh

echo "export GH_PROMPT_DISABLED=1" >> $BASH_ENV
