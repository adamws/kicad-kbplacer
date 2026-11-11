image_prefix := "admwscki/kicad-kbplacer-primary"
default_version := "10.0.8-noble"

# list available recipes
default:
    @just --list

# === Tests ===

# run tests inside docker against a specific KiCad version (default: {{default_version}})
test version=default_version *args="":
    docker run --rm \
        -v "{{justfile_directory()}}:/workspace" -w /workspace \
        "{{image_prefix}}:{{version}}" \
        bash -c "pip3 install --no-cache-dir hatch && hatch run test:test tests/ {{args}}"

# run tests for all supported KiCad versions, reporting failures at the end
test-all:
    #!/usr/bin/env bash
    overall=0
    for version in 6.0.11-lunar 7.0.6-lunar 7.0.11-mantic 8.0.9-jammy 9.0.9-noble 10.0.8-noble; do
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
tools-test version=default_version:
    docker run --rm \
        -v "{{justfile_directory()}}:/workspace" -w /workspace \
        "{{image_prefix}}:{{version}}" \
        bash -c "pip3 install --no-cache-dir hatch && hatch run tools-pcbnew:test"

# run layout2image tool and write SVG outputs to ./output_svgs/
tools-layout2image version=default_version:
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
tools-kle2kle version=default_version *args="--help":
    docker run --rm \
        -v "{{justfile_directory()}}:/workspace" -w /workspace \
        "{{image_prefix}}:{{version}}" \
        bash -c "pip3 install --no-cache-dir hatch && hatch run tools:kle2kle {{args}}"

# Downloads .kicad_pcb from URL (GitHub 'blob' links are converted to raw), recovers
# its layout with pcb2layout, renders it with layout2image and creates kle-ng link,
# for manual verification.
# Outputs <name>.kicad_pcb, <name>.json, <name>.svg and <name>.url to ./output_pcb2layout/.
# ARGS are passed to pcb2layout (default: --verify), for example:
#   just tools-pcb2layout https://github.com/foostan/crkbd/blob/main/pcbs/corne-cherry/hotswap/corne-cherry.kicad_pcb
#   just tools-pcb2layout <url> 10.0.6-noble --verify --matrix-labels --switch-pattern "SW{}"
# reverse-engineer layout of PCB downloaded from URL, render it to SVG and print kle-ng link
[positional-arguments]
tools-pcb2layout url version=default_version *args="--verify":
    #!/usr/bin/env bash
    set -euo pipefail
    outdir="{{justfile_directory()}}/output_pcb2layout"
    mkdir -p "$outdir"
    url={{quote(url)}}
    # remaining positional arguments are passed to pcb2layout, preserving quoting
    shift 2
    # https://github.com/<owner>/<repo>/blob/<ref>/<path> -> raw.githubusercontent.com
    url=$(echo "$url" | sed -E 's#^https?://github\.com/([^/]+)/([^/]+)/(blob|raw)/#https://raw.githubusercontent.com/\1/\2/#')
    name=$(basename "${url%%\?*}" .kicad_pcb)
    echo ">>> Downloading $url"
    curl -fsSL "$url" -o "$outdir/$name.kicad_pcb"
    if ! head -c 100 "$outdir/$name.kicad_pcb" | grep -q "(kicad_pcb"; then
        echo "Downloaded file is not a KiCad PCB (Git LFS pointer or HTML page?)" >&2
        exit 1
    fi
    docker run --rm \
        -v "{{justfile_directory()}}:/workspace" -w /workspace \
        -e NAME="$name" \
        "{{image_prefix}}:{{version}}" \
        bash -c 'set -euo pipefail
            pip3 install -q --no-cache-dir hatch
            out="output_pcb2layout/$NAME"
            hatch run tools-pcbnew:pcb2layout --in "$out.kicad_pcb" --out "$out.json" \
                --force --log-level INFO "$@"
            hatch run tools-pcbnew:layout2image --in "$out.json" --out "$out.svg" --force
            python3 -m kbplacer.kle_serial --in "$out.json" --inform KLE_RAW \
                --outform KLE_RAW --print-url > "$out.url"
        ' _ "$@"
    echo ">>> Layout: output_pcb2layout/$name.json"
    echo ">>> Image:  output_pcb2layout/$name.svg"
    echo ">>> kle-ng: $(cat "$outdir/$name.url")"

# Exports schematic and PCB of every design block in kbplacer/presets/ to SVG images
# (kbplacer/presets/images/) and regenerates presets overview in kbplacer/presets/README.md.
# Requires KiCad >= 10.0. Run after adding or editing a design block.
# generate design block (preset) preview images and overview
tools-block2image version=default_version:
    docker run --rm \
        -v "{{justfile_directory()}}:/workspace" -w /workspace \
        "{{image_prefix}}:{{version}}" \
        bash -c "pip3 install --no-cache-dir hatch && \
            hatch run tools:block2image \
                --in kbplacer/presets/kbplacer.kicad_blocks \
                --out kbplacer/presets/images \
                --readme kbplacer/presets/README.md \
                --log-level INFO"

# run layout2openscad tool (pass extra args after --)
tools-layout2openscad version=default_version *args="--help":
    docker run --rm \
        -v "{{justfile_directory()}}:/workspace" -w /workspace \
        "{{image_prefix}}:{{version}}" \
        bash -c "pip3 install --no-cache-dir hatch && hatch run tools-openscad:layout2openscad {{args}}"

# === Schematic ===

# Writes <layout>.kicad_sch (+ a .kicad_pro, and any other bundled sheet e.g. from
# `schematic-with-leds`) to ./output_schematic/, then exports a PDF for every
# .kicad_sch found there. LAYOUT names a file in tests/data/via-layouts/.
# Requires KiCad >= 9.0 (the default image satisfies this).
#
# Params are positional: `just schematic [VERSION] [LAYOUT] [-- EXTRA_KBPLACER_ARGS...]`.
# To pass extra kbplacer args you MUST spell out VERSION and LAYOUT before the `--`
# (`--` only lets the following dash-prefixed tokens bind positionally, it does NOT skip
# earlier params). Examples:
#   just schematic                                        # defaults: 10.0.6-noble, wt60_a
#   just schematic 10.0.6-noble 0_sixty                   # pick version + layout
#   just schematic 10.0.6-noble wt60_a --start-index 5    # append args to kbplacer
# build a schematic from a representative layout and export each sheet to PDF for inspection
schematic version=default_version layout="wt60_a" *args="":
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p "{{justfile_directory()}}/output_schematic"
    docker run --rm \
        -v "{{justfile_directory()}}:/workspace" -w /workspace \
        "{{image_prefix}}:{{version}}" \
        bash -c '
            set -euo pipefail
            # schematic builder dependency (kicad-skip);
            # No keyswitch footprint library is needed: the schematic path only writes the
            # footprint identifiers as symbol metadata strings, it never loads the
            # .pretty dirs (that is a PCB-builder concern, see the profile-memray recipe).
            pip3 install --no-cache-dir .[schematic]

            outdir="output_schematic"
            name="{{layout}}"
            via_layout="tests/data/via-layouts/$name.json"
            kle_layout="$outdir/$name-kle.json"
            pro_file="$outdir/$name.kicad_pro"
            sch_file="$outdir/$name.kicad_sch"

            # kbplacer and kicad-cli abort rather than overwrite; clear stale artifacts
            rm -rf "$outdir"/*

            # 1. Prep: convert the VIA layout into the matrix-annotated KLE_RAW shape
            #    that kle-ng-api feeds to kbplacer (also expands VIA encoders).
            python3 -m kbplacer.kle_serial \
                --in "$via_layout" --inform KLE_VIA --convert-via-encoders \
                --outform KLE_RAW --out "$kle_layout"

            # 2. Schematic-only kbplacer run (no --pcb-file / --create-pcb-file). The
            #    templated switch footprint is a plain literal: the `}` in `{:.2f}` would
            #    corrupt a ${VAR:-default} expansion, so it must not live inside one.
            python3 -m kbplacer \
                --create-sch-file \
                --sch-file "$sch_file" \
                --layout "$kle_layout" \
                --switch-footprint "Switch_Keyboard_Cherry_MX.pretty:SW_Cherry_MX_PCB_{:.2f}u" \
                --diode-footprint "/usr/share/kicad/footprints/Diode_SMD.pretty:D_SOD-123F" \
                --encoder-footprint "/usr/share/kicad/footprints/Rotary_Encoder.pretty:RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm" \
                --log-level "INFO" \
                {{args}}

            # 3. Export every generated schematic sheet (the key-matrix/LED-chain
            #    bundling above can write more than one .kicad_sch into $outdir)
            #    to PDF for easy visual inspection.
            for sch in "$outdir"/*.kicad_sch; do
                pdf="${sch%.kicad_sch}.pdf"
                kicad-cli sch export pdf --output "$pdf" "$sch"
                echo ">>> Schematic: $sch"
                echo ">>> PDF:       $pdf"
            done
        '

schematic-with-leds version=default_version layout="wt60_a" *args="":
    just schematic {{version}} {{layout}} --create-led-sch-file {{args}}

# Writes PCB and schematic project of LAYOUT (file in tests/data/via-layouts/) with
# BLOCK design block from kbplacer/presets/kbplacer.kicad_blocks added as `--preset`
# to ./output_presets/, then reports ERC and schematic parity DRC results and exports
# schematic PDFs and PCB SVG. POSITION is `[X Y [ROTATION]] [FRONT|BACK]`: block origin
# on the board (empty places it below the keyboard) and side of its components (empty
# keeps the block's own side). STRATEGY is flat|hierarchical.
# Requires KiCad >= 10.0 (design blocks with PCB layout). Examples:
#   just presets
#   just presets 10.0.8-noble crkbd mcu_atmega32u4_v2 "196 85 90"  # between halves
#   just presets 10.0.8-noble crkbd mcu_atmega32u4_v2 "196 85 0 FRONT"
#   just presets 10.0.8-noble crkbd mcu_atmega32u4_v1 "" flat \
#       --matrix-pin-order GPIO24,GPIO23,GPIO22,GPIO21,GPIO20,GPIO19,GPIO18,GPIO17,GPIO16,GPIO15,GPIO14,GPIO13,GPIO12,GPIO11
# build keyboard with design block preset (e.g. MCU circuit) for inspection
presets version=default_version layout="crkbd" block="mcu_atmega32u4_v1" position="" strategy="hierarchical" *args="":
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p "{{justfile_directory()}}/output_presets"
    docker run --rm \
        -v "{{justfile_directory()}}:/workspace" -w /workspace \
        "{{image_prefix}}:{{version}}" \
        bash -c '
            set -euo pipefail
            pip3 install -q --no-cache-dir .[schematic]

            outdir="output_presets"
            fp="/usr/share/kicad/footprints"
            pcb_file="$outdir/{{layout}}.kicad_pcb"

            # kbplacer aborts rather than overwrite; clear stale artifacts
            rm -rf "$outdir"/*

            python3 -m kbplacer \
                --layout "tests/data/via-layouts/{{layout}}.json" \
                --pcb-file "$pcb_file" \
                --create-pcb-file \
                --create-sch-file \
                --bundle-strategy "{{strategy}}" \
                --switch-footprint "$fp/Button_Switch_Keyboard.pretty:SW_Cherry_MX_1.00u_PCB" \
                --diode-footprint "$fp/Diode_SMD.pretty:D_SOD-123F" \
                --preset "{{block}} {{position}}" \
                --log-level "INFO" \
                {{args}}

            # kicad-cli loads only the first top-level sheet of a flat bundle,
            # complete ERC and parity results require `hierarchical` strategy
            kicad-cli sch erc --format json --output "$outdir/erc.json" \
                "$outdir/{{layout}}.kicad_sch" > /dev/null
            kicad-cli pcb drc --schematic-parity --format json \
                --output "$outdir/drc.json" "$pcb_file" > /dev/null
            python3 - "$outdir" <<"EOF"
    import collections, json, sys
    erc = json.load(open(f"{sys.argv[1]}/erc.json"))
    drc = json.load(open(f"{sys.argv[1]}/drc.json"))
    count = lambda items: dict(collections.Counter(i["type"] for i in items))
    print(">>> ERC:   ", count(v for s in erc["sheets"] for v in s["violations"]))
    print(">>> DRC:   ", count(drc["violations"]))
    print(">>> Parity:", count(drc["schematic_parity"]) or "OK")
    EOF

            for sch in "$outdir"/*.kicad_sch; do
                kicad-cli sch export pdf --output "${sch%.kicad_sch}.pdf" "$sch" > /dev/null
                echo ">>> Schematic: $sch"
            done
            kicad-cli pcb export svg --mode-single --fit-page-to-board \
                --layers F.Cu,B.Cu,F.SilkS,Edge.Cuts \
                --output "${pcb_file%.kicad_pcb}.svg" "$pcb_file" > /dev/null
            echo ">>> PCB:       $pcb_file"
            echo ">>> PCB image: ${pcb_file%.kicad_pcb}.svg"
        '

# === Placement ===

# dump pad geometry of switch-diode pair (kbplacer.pair_pads) placed with the bundled
# test footprints, JSON to stdout (POSITION is 'X Y ORIENTATION FRONT|BACK', pass extra
# args after it, e.g. --switch-rotation 90)
pair-pads version=default_version position="5.08 4 90 BACK" *args="":
    docker run --rm \
        -v "{{justfile_directory()}}:/workspace" -w /workspace \
        "{{image_prefix}}:{{version}}" \
        bash -c "pip3 install -q --no-cache-dir . && \
            python3 -m kbplacer.pair_pads \
                --switch-footprint tests/data/footprints/tests.pretty:SW_Cherry_MX_PCB_1.00u \
                --diode-footprint tests/data/footprints/tests.pretty:D_SOD-323F \
                --diode-position '{{position}}' {{args}}"

# === Profiling ===

# profile memory of a complete kle-ng-api task (schematic + pcb + LED chain) with memray
# Outputs profile.bin + flamegraphs to ./output_memray/. ROUTING: none|switch-diode|full
profile-memray version=default_version routing="full":
    #!/usr/bin/env bash
    set -euo pipefail
    outdir="{{justfile_directory()}}/output_memray"
    mkdir -p "$outdir"
    docker run --rm \
        -v "{{justfile_directory()}}:/workspace" -w /workspace \
        -e OUTDIR=/workspace/output_memray \
        -e ROUTING="{{routing}}" \
        "{{image_prefix}}:{{version}}" \
        bash -c '
            set -euo pipefail
            # memray + kbplacer with the schematic builder dependency (kicad-skip);
            pip3 install --no-cache-dir .[schematic] memray
            # Install the perigoso/kiswitch keyswitch footprints the same way
            # kle-ng-api worker Dockerfile does (the base image does not ship
            # keyboard switch footprints). Idempotent across re-runs.
            lib="$HOME/.local/share/kicad/3rdparty/footprints/com_github_perigoso_keyswitch-kicad-library"
            if [ ! -d "$lib" ]; then
                mkdir -p "$(dirname "$lib")"
                tmp="$(mktemp -d)"
                ( cd "$tmp" \
                  && wget -q https://github.com/kiswitch/keyswitch-kicad-library/releases/download/v2.4/keyswitch-kicad-library.zip \
                  && echo "b38d56323acb91ad660567340ca938c5b4a83a27eea52308ef14aa7857b0071b  keyswitch-kicad-library.zip" | sha256sum -c \
                  && unzip -q keyswitch-kicad-library.zip \
                  && mv footprints "$lib" )
                rm -rf "$tmp"
            fi
            bin="$OUTDIR/profile.bin"
            # Run the complete task under memray (RUNNER injects the tracker
            # around the single kbplacer process).
            RUNNER="python3 -m memray run --force -o $bin" \
                tools/profiling/kle-ng-api-task.sh
            echo "=== memray summary (peak / high-water-mark) ==="
            python3 -m memray summary "$bin"
            echo "=== memray stats ==="
            python3 -m memray stats "$bin"
            python3 -m memray flamegraph --force -o "$OUTDIR/flamegraph.html" "$bin"
            # --leaks highlights memory still allocated at exit, e.g. pcbnew SWIG leaks
            python3 -m memray flamegraph --leaks --force -o "$OUTDIR/flamegraph-leaks.html" "$bin"
            echo ">>> Reports: output_memray/flamegraph.html, output_memray/flamegraph-leaks.html"
        '

# === GUI ===

# launch KiCad GUI from docker with X11 forwarding
gui version=default_version:
    x11docker --hostdisplay --gpu=virgl \
        --share {{justfile_directory()}} \
        --home=$HOME \
        "{{image_prefix}}:{{version}}" \
        kicad

# launch pcbnew with a specific .kicad_pcb file (relative to repo root)
pcbnew version=default_version pcb="demo/demo.kicad_pcb":
    x11docker --hostdisplay --gpu=virgl \
        --share {{justfile_directory()}} \
        --home=$HOME \
        "{{image_prefix}}:{{version}}" \
        pcbnew {{justfile_directory()}}/{{pcb}}

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


# === Cleanup ===

cleanup:
  rm -rf output_schematic output_memray output_pcb2layout output_presets
  rm -rf .benchmarks
  rm -f examples/absolem-ergogen/absolem.zip
