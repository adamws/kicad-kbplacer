FROM admwscki/kicad-kbplacer-primary:8.0.0-mantic

RUN userdel -r ubuntu

ARG UID=1000
ARG GID=1000
RUN groupadd -g $GID -o kicad \
  && useradd -u $UID -g $GID --create-home --shell /bin/bash kicad \
  && usermod -m -d /kicad kicad

USER kicad
WORKDIR /kicad

ARG PLUGINS_PATH=/kicad/.local/share/kicad/8.0/3rdparty/plugins
RUN mkdir -p $PLUGINS_PATH
COPY --chown=kicad:kicad kbplacer/ $PLUGINS_PATH/com_github_adamws_kicad-kbplacer/

ENV PYTHONPATH "${PYTHONPATH}:${PLUGINS_PATH}"
