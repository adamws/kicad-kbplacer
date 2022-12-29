FROM admwscki/kicad-kbplacer-primary:6.0-lunar

RUN useradd --create-home --shell /bin/bash kicad \
  && usermod -m -d /kicad kicad

USER kicad
WORKDIR /kicad

COPY keyautoplace.py /usr/share/kicad/scripting/plugins/keyautoplace.py

