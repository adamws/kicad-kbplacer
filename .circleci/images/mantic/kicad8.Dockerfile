FROM ubuntu:mantic

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

RUN add-apt-repository --yes ppa:kicad/kicad-8.0-releases \
  && apt-get update \
  && apt-get install -y --no-install-recommends \
     kicad=8.0.2-0~ubuntu23.10.1 \
     kicad-footprints=8.0.2~ubuntu23.10.1 \
     kicad-symbols=8.0.2~ubuntu23.10.1 \
  && rm -rf /var/lib/apt/lists/*

ENV PYTHONPATH "${PYTHONPATH}:/usr/lib/python3/dist-packages"
