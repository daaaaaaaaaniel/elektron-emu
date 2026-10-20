#!/usr/bin/env bash
# Build an arm64 AUv2 bundle using DPF; suitable for an Xcode aggregate target.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/au-common.sh"
au_require_mac
au_set_work "${1:-$HOME/Library/Caches/ElektronEmu/Syntakt-AU/arm64}"
if [[ ! -f $au_work/unicorn/lib/libunicorn.a || ! -f $au_work/unicorn/DTCORE-UNICORN.txt || ! -d $au_work/dpf/.git ]]; then
  echo "error: run bash source/vst/scripts/bootstrap-au-mac.sh '$au_work' first (from Syntakt/)." >&2
  exit 1
fi
au_check_dpf
dtcore=$(bash "$au_root/vst/scripts/dtcore.sh" "$au_work")
build=$au_work/build
export CMAKE_BUILD_PARALLEL_LEVEL=${CMAKE_BUILD_PARALLEL_LEVEL:-4}
cmake -S "$au_root/vst" -B "$build" -G Ninja \
  -DCMAKE_BUILD_TYPE="${CONFIGURATION:-Release}" \
  -DCMAKE_OSX_ARCHITECTURES=arm64 -DCMAKE_OSX_DEPLOYMENT_TARGET=12.0 \
  -DSYNTAKT_PLUGIN_FORMATS=au -DDPF_ROOT="$au_work/dpf" \
  -DDTCORE_DIR="$dtcore" -DDTCORE_UNICORN_PREFIX="$au_work/unicorn"
cmake --build "$build" --target syntakt-au

bundle=$build/bin/syntakt.component
[[ -f $bundle/Contents/MacOS/syntakt && -f $bundle/Contents/Info.plist ]]
res=$bundle/Contents/Resources
mkdir -p "$res"
img=${DT_PANEL_IMAGE:-$au_root/vst/resources/syntakt_panel.png}
[[ -f $img || -n ${DT_PANEL_IMAGE:-} ]] || img=$au_root/out/gui/syntakt_panel.png
if [[ -f $img ]]; then
  cp "$img" "$res/syntakt_panel.png"
else
  rm -f "$res/syntakt_panel.png"
  echo "Panel photo absent; using the schematic panel."
fi
python3 "$au_root/vst/scripts/check-bundle.py" "$bundle"
codesign --force --sign - "$bundle"
codesign --verify --strict "$bundle"
echo "Built $bundle"

if [[ ${INSTALL:-0} == 1 ]]; then
  destination=$HOME/Library/Audio/Plug-Ins/Components/syntakt.component
  mkdir -p "$(dirname "$destination")"
  if [[ -e $destination || -L $destination ]]; then
    echo "error: $destination already exists; move your old component aside before installing." >&2
    exit 1
  fi
  ditto "$bundle" "$destination"
  echo "Installed $destination (restart Logic before rescanning)."
fi
