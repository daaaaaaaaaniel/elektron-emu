#!/usr/bin/env bash
# Prepare separate Intel and ARM dependencies; no firmware is downloaded.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/au-common.sh"
au_require_mac
au_set_work "${1:-$HOME/Library/Caches/ElektronEmu/Syntakt-AU/universal}"

if [[ ! -e $au_work/dpf ]]; then
  git clone --quiet --no-checkout https://github.com/DISTRHO/DPF.git "$au_work/dpf"
  git -C "$au_work/dpf" checkout --quiet --detach "$au_dpf_commit"
fi
[[ $(git -C "$au_work/dpf" rev-parse HEAD) == "$au_dpf_commit" ]] || {
  echo "error: DPF cache has a different revision; choose a fresh AU work directory." >&2
  exit 1
}
git -C "$au_work/dpf" submodule update --init --recursive
if ! git -C "$au_work/dpf" apply --reverse --check "$au_root/vst/patches/dpf-offline.patch" 2>/dev/null; then
  git -C "$au_work/dpf" apply --check "$au_root/vst/patches/dpf-offline.patch"
  git -C "$au_work/dpf" apply "$au_root/vst/patches/dpf-offline.patch"
fi
au_check_dpf

# The repository helper verifies the upstream revision and every patch checksum.
# unicorn-work is a disposable dependency source tree owned by this bootstrap.
export CMAKE_BUILD_PARALLEL_LEVEL=${CMAKE_BUILD_PARALLEL_LEVEL:-4}
for arch in x86_64 arm64; do
  echo "Preparing Unicorn for $arch"
  au_prepare_compilers "$arch"
  cpu=$arch
  [[ $arch != arm64 ]] || cpu=aarch64
  ARCHFLAGS="-arch $arch" CMAKE_OSX_ARCHITECTURES=$arch \
    CMAKE_OSX_DEPLOYMENT_TARGET=12.0 CMAKE_OSX_SYSROOT="$au_sdk" \
    CMAKE_C_COMPILER="$au_toolchain/clang" CMAKE_CXX_COMPILER="$au_toolchain/clang++" \
    UNICORN_QEMU_CPU=$cpu \
    bash "$au_root/core/scripts/build-unicorn.sh" "$au_work/$arch/unicorn" "$au_work/$arch/unicorn-work"
  lipo -verify_arch "$arch" "$au_work/$arch/unicorn/lib/libunicorn.a"
done
echo "AU dependencies prepared in $au_work"
