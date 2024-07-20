FROM ubuntu:20.04

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
  && apt-get install -y \
      ca-certificates \
      git \
      gzip \
      imagemagick \
      libmagickwand-dev \
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

RUN add-apt-repository --yes ppa:kicad/kicad-8.0-releases \
  && apt-get update \
  && apt-get install -y --no-install-recommends \
     kicad=8.0.4-0~ubuntu20.04.1 \
     kicad-footprints=8.0.4~ubuntu20.04.1 \
     kicad-symbols=8.0.4~ubuntu20.04.1 \
  && rm -rf /var/lib/apt/lists/*

ENV PYTHONPATH "${PYTHONPATH}:/usr/lib/python3.8/site-packages"
