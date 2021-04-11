FROM admwscki/kicad-kbplacer-primary:0.0.1

RUN useradd --create-home --shell /bin/bash kicad \
  && usermod -m -d /kicad kicad

USER kicad
WORKDIR /kicad

COPY keyautoplace.py /kicad/.kicad/scripting/plugins/keyautoplace.py

ENV KICAD_SYMBOL_DIR=/usr/share/kicad/library
ENV KISYSMOD=/usr/share/kicad/modules
