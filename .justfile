image_prefix := "admwscki/kicad-kbplacer-primary"
default_version := "10.0.3-noble"

# list available recipes
default:
    @just --list

# === Tests ===

# run tests inside docker against a specific KiCad version (default: {{default_version}})
test version=default_version:
    docker run --rm \
        -v "{{justfile_directory()}}:/workspace" -w /workspace \
        "{{image_prefix}}:{{version}}" \
        bash -c "pip3 install --no-cache-dir hatch && hatch run test:test tests/"

# run tests for all supported KiCad versions, reporting failures at the end
test-all:
    #!/usr/bin/env bash
    overall=0
    for version in 6.0.11-lunar 7.0.6-lunar 7.0.11-mantic 8.0.9-jammy 9.0.9-noble 10.0.3-noble; do
        echo "=== KiCad $version ==="
        docker run --rm \
            -v "{{justfile_directory()}}:/workspace" -w /workspace \
            "{{image_prefix}}:$version" \
            bash -c "pip3 install -q --no-cache-dir hatch && hatch run test:test -q --override-ini=log_cli=False tests/"
        if [ $? -ne 0 ]; then
            echo "FAILED: $version"
            overall=1
        fi
    done
    exit $overall

# run performance tests inside docker
test-perf version=default_version:
    docker run --rm \
        -v "{{justfile_directory()}}:/workspace" -w /workspace \
        "{{image_prefix}}:{{version}}" \
        bash -c "pip3 install --no-cache-dir hatch && \
            hatch run test:test --no-cov --profile \
                -k '2x3-rotations-custom-diode and RAW and PRESET' tests/ && \
            hatch run test:benchmark --benchmark-rounds 3"

# === Tools ===

# run tools test suite inside docker
tools-test version="9.0.9-noble":
    docker run --rm \
        -v "{{justfile_directory()}}:/workspace" -w /workspace \
        "{{image_prefix}}:{{version}}" \
        bash -c "pip3 install --no-cache-dir hatch && hatch run tools:test"

# run layout2image tool and write SVG outputs to ./output_svgs/
tools-layout2image version="9.0.9-noble":
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p "{{justfile_directory()}}/output_svgs"
    docker run --rm \
        -v "{{justfile_directory()}}:/workspace" -w /workspace \
        "{{image_prefix}}:{{version}}" \
        bash -c "pip3 install --no-cache-dir hatch && \
            for layout in 0_sixty arya; do \
                hatch run tools:layout2image \
                    --in tests/data/via-layouts/\$layout.json \
                    --out output_svgs/\$layout.svg; \
            done"

# run kle2kle tool (pass extra args after --)
tools-kle2kle version="9.0.9-noble" *args="--help":
    docker run --rm \
        -v "{{justfile_directory()}}:/workspace" -w /workspace \
        "{{image_prefix}}:{{version}}" \
        bash -c "pip3 install --no-cache-dir hatch && hatch run tools:kle2kle {{args}}"

# run layout2openscad tool (pass extra args after --)
tools-layout2openscad version="9.0.9-noble" *args="--help":
    docker run --rm \
        -v "{{justfile_directory()}}:/workspace" -w /workspace \
        "{{image_prefix}}:{{version}}" \
        bash -c "pip3 install --no-cache-dir hatch && hatch run tools-openscad:layout2openscad {{args}}"

# === GUI ===

# launch KiCad GUI from docker with X11 forwarding
gui version=default_version:
    xhost +local:docker
    docker run --rm -it \
        -e DISPLAY \
        -v /tmp/.X11-unix:/tmp/.X11-unix \
        -v "{{justfile_directory()}}:/workspace" -w /workspace \
        "{{image_prefix}}:{{version}}" \
        kicad

# launch pcbnew with a specific .kicad_pcb file (relative to repo root)
pcbnew version=default_version pcb="demo/demo.kicad_pcb":
    xhost +local:docker
    docker run --rm -it \
        -e DISPLAY \
        -v /tmp/.X11-unix:/tmp/.X11-unix \
        -v "{{justfile_directory()}}:/workspace" -w /workspace \
        "{{image_prefix}}:{{version}}" \
        pcbnew /workspace/{{pcb}}

# === Lint ===

# check code style (ruff + black --check)
lint:
    hatch run lint:style

# auto-format code (black + ruff --fix)
fmt:
    hatch run lint:fmt

# run type checking (mypy)
typing:
    hatch run lint:typing

# run all lint checks (style + typing)
lint-all:
    hatch run lint:all
