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

RUN add-apt-repository --yes ppa:kicad/kicad-7.0-releases \
  && apt-get update \
  && apt-get install -y --no-install-recommends \
     kicad=7.0.6~ubuntu23.04.1 \
     kicad-footprints=7.0.6-0-202307070230+5fca0686e~11~ubuntu23.04.1 \
     kicad-libraries=7.0.6-0-202307071724+9~ubuntu23.04.1  \
     kicad-symbols=7.0.6-0-202307070229+b591556d~7~ubuntu23.04.1 \
  && rm -rf /var/lib/apt/lists/*

ENV LD_LIBRARY_PATH "/usr/lib/kicad/lib/x86_64-linux-gnu"
ENV PYTHONPATH "${PYTHONPATH}:/usr/lib/kicad/lib/python3/dist-packages"
