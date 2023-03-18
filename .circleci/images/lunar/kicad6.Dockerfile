FROM ubuntu:lunar

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
  && apt-get install -y \
      ca-certificates \
      git \
      gzip \
      python3-pip \
      software-properties-common \
      ssh \
      tar \
      unzip \
      wget \
  && rm -rf /var/lib/apt/lists/*

RUN find / -type f -name "EXTERNALLY-MANAGED" -exec rm {} \;

RUN add-apt-repository --yes ppa:kicad/kicad-6.0-releases \
  && apt-get update \
  && apt-get install -y --no-install-recommends \
     kicad \
     kicad-footprints \
     kicad-libraries \
     kicad-symbols \
  && rm -rf /var/lib/apt/lists/*

