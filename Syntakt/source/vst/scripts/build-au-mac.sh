#!/usr/bin/env bash
# Build each CPU slice with DPF, then merge a universal AUv2 bundle.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/au-common.sh"
au_require_mac
au_set_work "${1:-$HOME/Library/Caches/ElektronEmu/Syntakt-AU/universal}"
for arch in x86_64 arm64; do
  prefix=$au_work/$arch/unicorn
  if [[ ! -f $prefix/lib/libunicorn.a || ! -f $prefix/DTCORE-UNICORN.txt || ! -d $au_work/dpf/.git ]]; then
    echo "error: run bash source/vst/scripts/bootstrap-au-mac.sh '$au_work' first (from Syntakt/)." >&2
    exit 1
  fi
  lipo -verify_arch "$arch" "$prefix/lib/libunicorn.a"
done
au_check_dpf
dtcore=$(bash "$au_root/vst/scripts/dtcore.sh" "$au_work")
export CMAKE_BUILD_PARALLEL_LEVEL=${CMAKE_BUILD_PARALLEL_LEVEL:-4}
native_arch=$(uname -m)
other_arch=arm64
[[ $native_arch != arm64 ]] || other_arch=x86_64
native_exporter=$au_work/$native_arch/build/bin/syntakt-export
# DPF's AU POST_BUILD runs the export executable to write Info.plist. Route the
# foreign build's invocation to the native helper; no foreign code is executed.
export_launcher=$au_work/native-au-export
{
  printf '#!/bin/bash\nset -euo pipefail\n'
  printf 'native_exporter=%q\n' "$native_exporter"
  cat <<'EOF'
if [[ $# -lt 2 || ! -x $native_exporter ]]; then
  echo "error: AU metadata requires the native export helper and a plug-in name." >&2
  exit 1
fi
shift # Discard DPF's foreign export executable path; preserve its arguments.
exec "$native_exporter" "$@"
EOF
} > "$export_launcher"
chmod +x "$export_launcher"
for arch in "$native_arch" "$other_arch"; do
  echo "Building Syntakt AU for $arch"
  au_prepare_compilers "$arch"
  build=$au_work/$arch/build
  export_runner=
  [[ $arch == "$native_arch" ]] || export_runner=$export_launcher
  ARCHFLAGS="-arch $arch" cmake -S "$au_root/vst" -B "$build" -G Ninja \
    -DCMAKE_BUILD_TYPE="${CONFIGURATION:-Release}" \
    -DCMAKE_C_COMPILER="$au_toolchain/clang" -DCMAKE_CXX_COMPILER="$au_toolchain/clang++" \
    -DCMAKE_OSX_SYSROOT="$au_sdk" \
    -DZLIB_LIBRARY="$au_sdk/usr/lib/libz.tbd" -DZLIB_INCLUDE_DIR="$au_sdk/usr/include" \
    -DCMAKE_OSX_ARCHITECTURES="$arch" -DCMAKE_OSX_DEPLOYMENT_TARGET=12.0 \
    -DCMAKE_CROSSCOMPILING_EMULATOR="$export_runner" \
    -DSYNTAKT_PLUGIN_FORMATS=au -DDPF_ROOT="$au_work/dpf" \
    -DDTCORE_DIR="$dtcore" -DDTCORE_UNICORN_PREFIX="$au_work/$arch/unicorn"
  cmake --build "$build" --target syntakt-au
  lipo -verify_arch "$arch" "$build/bin/syntakt.component/Contents/MacOS/syntakt"
  if [[ $arch == "$native_arch" ]]; then
    [[ -x $native_exporter ]]
    lipo -verify_arch "$native_arch" "$native_exporter"
  fi
done

intel=$au_work/x86_64/build/bin/syntakt.component
arm=$au_work/arm64/build/bin/syntakt.component
if ! cmp -s "$intel/Contents/Info.plist" "$arm/Contents/Info.plist"; then
  echo "error: Intel and ARM AU metadata differ; cannot merge the bundles." >&2
  exit 1
fi
bundle=$au_work/build/bin/syntakt.component
mkdir -p "$(dirname "$bundle")"
ditto "$intel" "$bundle"
lipo -create "$intel/Contents/MacOS/syntakt" "$arm/Contents/MacOS/syntakt" \
  -output "$bundle/Contents/MacOS/syntakt"
lipo -verify_arch x86_64 arm64 "$bundle/Contents/MacOS/syntakt"
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
echo "Built universal (x86_64 + arm64) $bundle"

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
