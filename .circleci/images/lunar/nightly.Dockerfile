FROM ubuntu:lunar

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
  && apt-get install -y \
      ca-certificates \
      git \
      gzip \
      imagemagick \
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
ENV PYTHONPATH "${PYTHONPATH}:/usr/lib/kicad-nightly/local/lib/python3.11/dist-packages"
