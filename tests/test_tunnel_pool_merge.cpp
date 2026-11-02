#include "utils/tunnel_pool_merge.h"
#include <random>
#include <vector>
#include <iostream>

// Differential testing against upstream insertion, including tie fallback,
// capacity boundaries, candidate rejection and both state bits on old nodes.
int main() {
  std::mt19937 rng(20261102);
  unsigned cases = 0;
  for (unsigned limit : {1u, 2u, 3u, 8u, 20u, 40u, 160u, 320u, 640u}) {
    for (unsigned trial = 0; trial < 2400; ++trial) {
      unsigned initial = 1 + rng() % limit;
      unsigned count = rng() % 33;
      unsigned scalar_size = initial, batch_size = initial;
      unsigned scalar_marker = rng() % (initial + 1), batch_marker = scalar_marker;
      std::vector<pipeann::Neighbor> scalar(limit + 1), batch(limit + 1), scratch(limit), incoming(33);
      std::vector<uint32_t> ids(count);
      std::vector<float> dists(count);
      std::vector<float> unique(initial + count);
      for (unsigned i = 0; i < unique.size(); ++i) unique[i] = float(i) * 0.25f;
      std::shuffle(unique.begin(), unique.end(), rng);
      bool ties = trial % 3 == 0;
      // Binary-exact distances and shuffled candidates exercise insertions
      // before, within or beyond a partially/full populated pool.
      for (unsigned i = 0; i < initial; ++i) {
        scalar[i] = pipeann::Neighbor(i, ties ? float(i / 3) : unique[i], bool(rng() % 2));
        scalar[i].visited = rng() % 2;
      }
      std::sort(scalar.begin(), scalar.begin() + initial);
      batch = scalar;
      for (unsigned i = 0; i < count; ++i) {
        ids[i] = limit + 1 + i;
        dists[i] = ties ? float(rng() % (limit + 5)) : unique[initial + i];
      }
      std::shuffle(dists.begin(), dists.end(), rng);
      pipeann::insert_tunnel_scalar(scalar.data(), scalar_size, limit, ids.data(), dists.data(), count, scalar_marker);
      pipeann::insert_tunnel_batch(batch.data(), batch_size, limit, ids.data(), dists.data(), count, batch_marker,
                                   scratch.data(), incoming.data());
      bool equal = scalar_size == batch_size && scalar_marker == batch_marker;
      for (unsigned i = 0; i < scalar_size && equal; ++i) {
        const auto &a = scalar[i], &b = batch[i];
        equal = a.id == b.id && a.distance == b.distance && a.flag == b.flag && a.visited == b.visited;
      }
      if (!equal) {
        std::cerr << "Mismatch limit=" << limit << " initial=" << initial << " count=" << count
                  << " trial=" << trial << " marker=" << scalar_marker << "/" << batch_marker << "\n";
        return 1;
      }
      ++cases;
    }
  }
  std::cout << "PASS " << cases << " differential candidate-pool cases\n";
}
