#pragma once

#include "utils.h"
#include <algorithm>

namespace pipeann {

// The scalar path deliberately uses the upstream insertion and admission rule.
inline void insert_tunnel_scalar(Neighbor *pool, unsigned &size, unsigned limit,
                                 const uint32_t *ids, const float *distances,
                                 unsigned count, unsigned &marker) {
  for (unsigned i = 0; i < count; ++i) {
    if (size < limit || distances[i] < pool[size - 1].distance) {
      const auto position = InsertIntoPool(pool, size, Neighbor(ids[i], distances[i], true));
      if (size < limit) ++size;
      if (position < marker) marker = position;
    }
  }
}

// IDs have already been deduplicated against the per-query visited set.
// scratch has at least limit entries; incoming has at least count entries.
// A single sorted merge replaces repeated movement of the same pool suffix.
// Preserve upstream tie ordering by falling back before writing to the pool.
inline void insert_tunnel_batch(Neighbor *pool, unsigned &size, unsigned limit,
                                const uint32_t *ids, const float *distances,
                                unsigned count, unsigned &marker,
                                Neighbor *scratch, Neighbor *incoming) {
  if (count < 4) {
    insert_tunnel_scalar(pool, size, limit, ids, distances, count, marker);
    return;
  }
  unsigned n = 0;
  for (unsigned i = 0; i < count; ++i) {
    if (size < limit || distances[i] < pool[size - 1].distance)
      incoming[n++] = Neighbor(ids[i], distances[i], true);
  }
  if (n == 0) return;
  if (n < 4) {
    insert_tunnel_scalar(pool, size, limit, ids, distances, count, marker);
    return;
  }
  std::sort(incoming, incoming + n);
  for (unsigned i = 1; i < n; ++i) {
    if (incoming[i - 1].distance == incoming[i].distance) {
      insert_tunnel_scalar(pool, size, limit, ids, distances, count, marker);
      return;
    }
  }
  const unsigned output_size = std::min(limit, size + n);
  unsigned old = 0, next = 0, first_new = output_size;
  for (unsigned out = 0; out < output_size; ++out) {
    if (old < size && next < n && pool[old].distance == incoming[next].distance) {
      insert_tunnel_scalar(pool, size, limit, ids, distances, count, marker);
      return;
    }
    if (next < n && (old == size || incoming[next].distance < pool[old].distance)) {
      scratch[out] = incoming[next++];
      first_new = std::min(first_new, out);
    } else {
      scratch[out] = pool[old++];
    }
  }
  std::copy(scratch, scratch + output_size, pool);
  size = output_size;
  marker = std::min(marker, first_new);
}

}  // namespace pipeann
