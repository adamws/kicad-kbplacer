FROM ubuntu:20.04

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
  && apt-get install -y \
      ca-certificates \
      git \
      gzip \
      imagemagick \
      libmagickwand-dev \
      python3-pip \
      software-properties-common \
      ssh \
      tar \
      unzip \
      wget \
      xvfb \
  && rm -rf /var/lib/apt/lists/*

RUN add-apt-repository --yes ppa:kicad/kicad-7.0-releases \
  && apt-get update \
  && apt-get install -y --no-install-recommends \
     kicad=7.0.5~ubuntu20.04.1 \
     kicad-footprints=7.0.5-0-202305272309+208252e63~11~ubuntu20.04.1 \
     kicad-libraries=7.0.5-0-202305272323+9~ubuntu20.04.1 \
     kicad-symbols=7.0.5-0-202305272310+22b3e34e~7~ubuntu20.04.1 \
  && rm -rf /var/lib/apt/lists/*

