FROM python:3.11-alpine as builder

RUN apk --no-cache add gettext git
RUN python -m pip install --upgrade hatch

COPY . /work
RUN cd /work \
  && python -m hatch build --target kicad-package

FROM admwscki/kicad-kbplacer-primary:8.0.9-jammy as main

RUN ln -s /usr/bin/python3 /usr/bin/python

ARG UID=1000
ARG GID=1000
RUN groupadd -g $GID -o kicad \
  && useradd -u $UID -g $GID --create-home --shell /bin/bash kicad \
  && usermod -m -d /kicad kicad

USER kicad
WORKDIR /kicad

ARG PLUGINS_PATH=/kicad/.local/share/kicad/8.0/3rdparty/plugins
ARG PLUGIN_NAME=com_github_adamws_kicad-kbplacer

COPY --from=builder --chown=kicad /work/dist/kbplacer*.zip /tmp

RUN cd /tmp && unzip *.zip
RUN mkdir -p $PLUGINS_PATH/$PLUGIN_NAME \
  && cp -r /tmp/plugins/* $PLUGINS_PATH/$PLUGIN_NAME \
  && rm -rf /tmp/*

ENV PYTHONPATH "${PYTHONPATH}:${PLUGINS_PATH}"
RUN ln -s $PLUGINS_PATH/$PLUGIN_NAME $PLUGINS_PATH/kbplacer
