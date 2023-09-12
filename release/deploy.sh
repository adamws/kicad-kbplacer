#!/bin/sh

set -o nounset
set -o errexit

CUR_DIR="$(dirname $(readlink -f "$0"))"
cd ${CUR_DIR}/../dist/repository

echo "==> Prepare to deploy\n"
git init
git config --global user.name "CircleCI"
git config --global user.email "${CIRCLE_PROJECT_USERNAME}@users.noreply.github.com"

if [ -z "$(git status --porcelain)" ]; then
    echo "Something went wrong" && \
    echo "Exiting..."
    exit 0
fi

mkdir .circleci
wget https://raw.githubusercontent.com/adamws/kicad-kbplacer/master/.circleci/ghpages-config.yml -O .circleci/config.yml
touch .nojekyll

echo "==> Start deploying"
git add -A
git commit -m "Deploy plugin repository: ${CIRCLE_SHA1}"

git push --force $CIRCLE_REPOSITORY_URL master:gh-pages

rm -fr .git

echo "==> Deploy succeeded"
