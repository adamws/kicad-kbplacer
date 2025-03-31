#!/bin/sh

cd /kicad-kbplacer
if hatch run tools:layout2openscad --help; then
  echo "Running plate generation tool"
  hatch run tools:layout2openscad \
    -in $WORK_PATH/$PROJECT_NAME-kle.json \
    -out $WORK_PATH/$PROJECT_NAME-plate.scad \
    -shape convex_hull --align-origin
  cd -
  openscad $PROJECT_NAME-plate.scad \
    -o $PROJECT_NAME-plate.png --viewall --view axes
  zip -rv $PROJECT_NAME.zip $PROJECT_NAME-plate.png $PROJECT_NAME-plate.scad
else
  echo "Plate generation tool not available"
  cd -
fi

