FROM ubuntu:jammy

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
  && apt-get install -y \
      ca-certificates \
      git \
      gzip \
      imagemagick \
      librsvg2-2 \
      locales \
      python3-pip \
      software-properties-common \
      ssh \
      tar \
      unzip \
      wget \
      xvfb \
  && rm -rf /var/lib/apt/lists/*

RUN sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen \
  && locale-gen

ENV LANG en_US.UTF-8
ENV LANGUAGE en_US:en
ENV LC_ALL en_US.UTF-8

RUN find / -type f -name "EXTERNALLY-MANAGED" -exec rm {} \;

RUN add-apt-repository --yes ppa:kicad/kicad-dev-nightly \
  && apt-get update \
  && apt-get install -y --no-install-recommends \
     kicad-nightly \
  && rm -rf /var/lib/apt/lists/*

ENV LD_LIBRARY_PATH "/usr/lib/kicad-nightly/lib/x86_64-linux-gnu"
ENV PYTHONPATH "${PYTHONPATH}:/usr/lib/kicad-nightly/lib/python3/dist-packages"
ENV PATH "${PATH}:/usr/lib/kicad-nightly/bin"

# kicad-python for the IPC contract tests (tests/test_ipc_contract.py).
# Built from source, PyPI releases lag behind the nightly API.
# Needs the `kicad` submodule for .proto files; protoc comes from build-system requires.
ARG KICAD_PYTHON_REF=87b945a0d56b26a78bf547db9771ff9bf3a057ea
RUN pip3 install --no-cache-dir --upgrade pip \
  && git clone https://gitlab.com/kicad/code/kicad-python.git /tmp/kicad-python \
  && cd /tmp/kicad-python \
  && git checkout ${KICAD_PYTHON_REF} \
  && git submodule update --init --depth 1 \
  && pip3 install --no-cache-dir . \
  && cd / && rm -rf /tmp/kicad-python
