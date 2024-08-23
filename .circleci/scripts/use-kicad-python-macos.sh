#!/bin/sh

export KICAD_PYTHON=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin
export PATH=$KICAD_PYTHON:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin

ln -sf $KICAD_PYTHON/python3 $KICAD_PYTHON/python
ln -sf $KICAD_PYTHON/pip3 $KICAD_PYTHON/pip

python -c "import sys; print('Python version: ' + sys.version)"
python -c "import pcbnew; print('KiCad version: ' + pcbnew.Version())"
