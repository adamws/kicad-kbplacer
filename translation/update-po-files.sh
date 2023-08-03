#!/bin/sh

set -o nounset
set -o errexit

CUR_DIR="$(dirname $(readlink -f "$0"))"
SOURCE_DIR=${CUR_DIR}/../kbplacer

GETTEXT_MODULE=$(python -c "import gettext as m; print(m.__file__)")
PY_TOOLS="$(dirname ${GETTEXT_MODULE})/Tools"
GETTEXT="${PY_TOOLS}/i18n/pygettext.py"

find $SOURCE_DIR -name '*.py' |
  xargs python $GETTEXT -kself._ --no-location \
    --default-domain=kbplacer -o $CUR_DIR/kbplacer.pot

sed -i '/^#/d' $CUR_DIR/kbplacer.pot

#Read file without comment and empty lines
LANGUAGES=$(cat $CUR_DIR/pofiles/LINGUAS | grep -v '^#' | grep -v '^\s*$')

update_po() {
  if [ "$1" = "en" ] ; then
    msgmerge --no-location --no-fuzzy-matching --force-po $CUR_DIR/pofiles/$1.po $CUR_DIR/kbplacer.pot \
      -o $CUR_DIR/pofiles/$1.po 2> /dev/null
    msgen $CUR_DIR/pofiles/$1.po -o $CUR_DIR/pofiles/$1.po.tmp &&
      mv $CUR_DIR/pofiles/$1.po.tmp $CUR_DIR/pofiles/$1.po
  else
    msgmerge --force-po $CUR_DIR/pofiles/$1.po $CUR_DIR/kbplacer.pot \
      -o $CUR_DIR/pofiles/$1.po 2> /dev/null
  fi
  sed -i '/^#/d' $CUR_DIR/pofiles/$1.po
}

for i in $LANGUAGES
do
  {
    update_po $i
  } &
done
