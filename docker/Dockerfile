FROM admwscki/kicad-kbplacer-primary:6.0-lunar

RUN useradd --create-home --shell /bin/bash kicad \
  && usermod -m -d /kicad kicad

USER kicad
WORKDIR /kicad

RUN mkdir -p /kicad/.local/share/kicad/6.0/3rdparty/plugins/
COPY --chown=kicad:kicad kbplacer/ /kicad/.local/share/kicad/6.0/3rdparty/plugins/com_github_adamws_kicad-kbplacer/
