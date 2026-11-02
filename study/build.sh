#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for variant in baseline optimized; do
  merge=OFF
  if [[ "$variant" == optimized ]]; then merge=ON; fi
  cmake -S "$repo_root" -B "$repo_root/build-$variant" \
    -DCMAKE_BUILD_TYPE=Release -DUSE_AIO=ON -DGATEANN_TUNNEL_BATCH_MERGE="$merge"
  cmake --build "$repo_root/build-$variant" \
    --target search_disk_index_yfcc test_tunnel_pool_merge -j "${FVS_BUILD_JOBS:-2}"
  "$repo_root/build-$variant/tests/test_tunnel_pool_merge"
done
