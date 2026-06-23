FROM python:3.11-alpine as builder

RUN apk --no-cache add gettext git
RUN python -m pip install --upgrade hatch

COPY . /work
RUN cd /work \
  && python -m hatch build --target kicad-package

FROM admwscki/kicad-kbplacer-primary:10.0.4-noble as main

RUN ln -s /usr/bin/python3 /usr/bin/python

USER ubuntu
WORKDIR /home/ubuntu

ARG PLUGINS_PATH=/home/ubuntu/.local/share/kicad/10.0/3rdparty/plugins
ARG PLUGIN_NAME=com_github_adamws_kicad-kbplacer

COPY --from=builder --chown=ubuntu /work/dist/kbplacer*.zip /tmp

RUN cd /tmp && unzip *.zip
RUN mkdir -p $PLUGINS_PATH/$PLUGIN_NAME \
  && cp -r /tmp/plugins/* $PLUGINS_PATH/$PLUGIN_NAME \
  && rm -rf /tmp/*

ENV PYTHONPATH "${PYTHONPATH}:${PLUGINS_PATH}"
RUN ln -s $PLUGINS_PATH/$PLUGIN_NAME $PLUGINS_PATH/kbplacer
