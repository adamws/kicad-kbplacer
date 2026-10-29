# Image for running tests against KiCad IPC API (kicad-python)
# Build from project root:
#   docker build -t kicad-kbplacer-ipc-tests:nightly-jammy -f docker/ipc-tests.Dockerfile .
ARG BASE_IMAGE=admwscki/kicad-kbplacer-primary:nightly-jammy
FROM ${BASE_IMAGE}

RUN pip3 install --no-cache-dir --upgrade pip hatch

# kicad-python from source, PyPI releases lag behind nightly API.
# Needs the `kicad` submodule for .proto files; protoc comes from build-system requires.
ARG KICAD_PYTHON_REF=87b945a0d56b26a78bf547db9771ff9bf3a057ea
RUN git clone https://gitlab.com/kicad/code/kicad-python.git /tmp/kicad-python \
  && cd /tmp/kicad-python \
  && git checkout ${KICAD_PYTHON_REF} \
  && git submodule update --init --depth 1 \
  && pip3 install --no-cache-dir . \
  && cd / && rm -rf /tmp/kicad-python
