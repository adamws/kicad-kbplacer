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

RUN add-apt-repository --yes ppa:kicad/kicad-6.0-releases \
  && apt-get update \
  && apt-get install -y --no-install-recommends \
     kicad \
     kicad-footprints \
     kicad-libraries \
     kicad-symbols \
  && rm -rf /var/lib/apt/lists/*

