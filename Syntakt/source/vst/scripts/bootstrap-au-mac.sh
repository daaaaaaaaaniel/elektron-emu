#!/usr/bin/env bash
# Prepare a dedicated arm64 AU dependency cache; no firmware is downloaded.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/au-common.sh"
au_require_mac
au_set_work "${1:-$HOME/Library/Caches/ElektronEmu/Syntakt-AU/arm64}"

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
export CMAKE_OSX_ARCHITECTURES=arm64 CMAKE_OSX_DEPLOYMENT_TARGET=12.0
export CMAKE_BUILD_PARALLEL_LEVEL=${CMAKE_BUILD_PARALLEL_LEVEL:-4}
bash "$au_root/core/scripts/build-unicorn.sh" "$au_work/unicorn" "$au_work/unicorn-work"
echo "AU dependencies prepared in $au_work"
