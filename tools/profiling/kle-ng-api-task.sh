#!/usr/bin/env bash
#
# kle-ng-api-task.sh
#
# Reproduces a *complete* kle-ng-api generation task (schematic builder + PCB
# builder in a single `kbplacer` invocation) so its memory usage can be
# profiled with memray.
#
# kle-ng-api runs exactly one `python3 -m kbplacer` process per request with
# both `--create-sch-file` and `--create-pcb-file` enabled (see
# kle-ng-api/backend/internal/kicad/kicad.go: RunKBPlacer). That single process
# loads KiCad's `pcbnew` SWIG bindings, which have historically leaked memory,
# so the whole task is what we want to measure for OOM sizing.
#
# This script mirrors those CLI arguments. The expensive kbplacer step is run
# through $RUNNER, which defaults to plain `python3` but is set to
# `python3 -m memray run ...` by the `just profile-memray` recipe.
#
# Env knobs (all optional):
#   VIA_LAYOUT   VIA layout to feed in, relative to repo root.
#                Converted to matrix-annotated KLE_RAW, the same shape kle-ng-api
#                receives from the frontend. Default: a full 60% board.
#   OUTDIR       Where generated artifacts go. Default: ./output_memray
#   ROUTING      none | switch-diode | full  (default: full -> worst case)
#   KEYSWITCH_LIB  Directory holding the perigoso keyswitch library
#                  (installed by the `just profile-memray` recipe)
#   SWITCH_FP    Switch footprint identifier (lib.pretty:name with {} size slot)
#   DIODE_FP     Diode footprint identifier
#   RUNNER       Command prefix for the kbplacer process (memray injects here)
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

VIA_LAYOUT="${VIA_LAYOUT:-tests/data/via-layouts/wt60_a.json}"
OUTDIR="${OUTDIR:-$REPO_ROOT/output_memray}"
ROUTING="${ROUTING:-full}"
RUNNER="${RUNNER:-python3}"

# Switch footprint comes from the perigoso/kiswitch keyswitch library, the same
# one kle-ng-api uses (its name is `SW_Cherry_MX_PCB_<size>u`). The
# `profile-memray` recipe installs that library into
# $HOME/.local/share/kicad/3rdparty/footprints, mirroring kle-ng-api's
# Dockerfile, so this default resolves. The diode uses KiCad's built-in library.
KEYSWITCH_LIB="${KEYSWITCH_LIB:-${HOME}/.local/share/kicad/3rdparty/footprints/com_github_perigoso_keyswitch-kicad-library}"
# The footprint name carries a `{:.2f}` size template. It must NOT live inside a
# ${VAR:-default} expansion: the `}` in `{:.2f}` would close the expansion early
# and corrupt the value (e.g. `..._PCB_{:.2fu}`). Assign it plainly instead.
if [ -z "${SWITCH_FP:-}" ]; then
  SWITCH_FP="${KEYSWITCH_LIB}/Switch_Keyboard_Cherry_MX.pretty:SW_Cherry_MX_PCB_{:.2f}u"
fi
DIODE_FP="${DIODE_FP:-/usr/share/kicad/footprints/Diode_SMD.pretty:D_SOD-123F}"
ENCODER_FP="/usr/share/kicad/footprints/Rotary_Encoder.pretty:RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm"

mkdir -p "$OUTDIR"
PROJECT_NAME="kle-ng-api-task"
KLE_LAYOUT="$OUTDIR/$PROJECT_NAME-kle.json"
KICAD_PCB="$OUTDIR/$PROJECT_NAME.kicad_pcb"
KICAD_SCH="$OUTDIR/$PROJECT_NAME.kicad_sch"

# kbplacer aborts rather than overwrite existing files; clear artifacts from a
# previous run so profiling is repeatable.
rm -f "$KICAD_PCB" "$KICAD_SCH" "$KLE_LAYOUT"

echo ">>> Repo:        $REPO_ROOT"
echo ">>> VIA layout:  $VIA_LAYOUT"
echo ">>> Routing:     $ROUTING"
echo ">>> Runner:      $RUNNER"
echo ">>> Output dir:  $OUTDIR"

# 1. Prep: convert the VIA layout into the matrix-annotated KLE_RAW layout that
#    kle-ng-api would have written to disk before calling kbplacer. This step is
#    cheap and is intentionally NOT profiled.
echo ">>> Converting VIA layout -> KLE_RAW (kle-ng-api input shape)"
python3 -m kbplacer.kle_serial \
  --in "$VIA_LAYOUT" --inform KLE_VIA --convert-via-encoders \
  --outform KLE_RAW --out "$KLE_LAYOUT"

# 2. Routing flags, matching kle-ng-api's `routing` setting mapping.
ROUTE_ARGS=()
case "$ROUTING" in
  none) ;;
  switch-diode) ROUTE_ARGS+=(--route-switches-with-diodes) ;;
  full)         ROUTE_ARGS+=(--route-switches-with-diodes --route-rows-and-columns) ;;
  *) echo "!!! unknown ROUTING='$ROUTING' (use none|switch-diode|full)" >&2; exit 2 ;;
esac

# 3. The complete task: one kbplacer process doing schematic + PCB, exactly the
#    argument set kle-ng-api builds in RunKBPlacer. This is what $RUNNER wraps.
echo ">>> Running complete kbplacer task (schematic builder + PCB builder)"
# shellcheck disable=SC2086
$RUNNER -m kbplacer \
  --pcb-file "$KICAD_PCB" \
  --create-sch-file \
  --sch-file "$KICAD_SCH" \
  --create-pcb-file \
  --switch-footprint "$SWITCH_FP" \
  --diode-footprint "$DIODE_FP" \
  --encoder-footprint "$ENCODER_FP" \
  --encoder-adjustment "-7.5 -2.5" \
  --layout "$KLE_LAYOUT" \
  --layout-offset "0 0" \
  --switch "SW{} 0 FRONT" \
  --diode "D{} CUSTOM 0 0 0 BACK" \
  --no-stabilizers \
  --log-level "INFO" \
  --max-keys 150 \
  "${ROUTE_ARGS[@]}"

echo ">>> Done. Artifacts in $OUTDIR"
