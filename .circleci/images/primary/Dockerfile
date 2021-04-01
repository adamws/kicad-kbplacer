FROM ubuntu:20.04

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
  && apt-get install -y \
      ca-certificates \
      git \
      gzip \
      libmagickwand-dev \
      python3-pip \
      software-properties-common \
      ssh \
      tar \
      unzip \
      wget \
  && rm -rf /var/lib/apt/lists/*

RUN add-apt-repository --yes ppa:kicad/kicad-5.1-releases \
  && apt-get update \
  && apt-get install -y --no-install-recommends \
     kicad \
     kicad-footprints \
     kicad-libraries \
     kicad-symbols \
  && rm -rf /var/lib/apt/lists/*

