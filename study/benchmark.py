#!/usr/bin/env python3
"""Paired GateANN benchmark. Run inside the Linux course container."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import statistics
import subprocess
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
METRICS = ['recall_percent', 'mean_latency_us', 'qps', 'mean_ios',
           'filter_skips', 'io_time_us', 'tunnel_time_us', 'process_time_us', 'peak_rss_kb']
CONFIGS = [('high', 160), ('high', 320), ('high', 640), ('medium', 320), ('low', 320)]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_one(args, tier, bucket, budget, variant, repeat, run_root):
    directory = run_root / tier / bucket / f'L{budget}' / f'r{repeat}-{variant}'
    directory.mkdir(parents=True, exist_ok=False)
    dataset = args.dataset_root / tier
    workload = dataset / 'workloads' / bucket
    prefix = args.index_root / tier / 'yfcc'
    binary = ROOT / f'build-{variant}/tests/search_disk_index_yfcc'
    command = [str(binary), 'uint8', str(prefix), '1', '8', str(workload / 'query.u8bin'),
               str(dataset / 'base.metadata.spmat'), str(workload / 'query.metadata.spmat'),
               str(workload / 'ground_truth.ids.ibin'), '10', 'l2', 'pq', '8', '0', '0', '32', str(budget)]
    env = os.environ.copy()
    env.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
               GATEANN_RESULT_DUMP_PREFIX=str(directory / 'results'))
    start = time.monotonic()
    with (directory / 'run.log').open('w') as log:
        completed = subprocess.run(['/usr/bin/time', '-v', '-o', str(directory / 'resource.txt'),
                                    *command], stdout=log, stderr=subprocess.STDOUT, env=env)
    metadata = {'command': command, 'exit_code': completed.returncode,
                'environment_overrides': {k: env[k] for k in ['OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS',
                                                          'GATEANN_RESULT_DUMP_PREFIX']},
                'elapsed_seconds': time.monotonic() - start}
    (directory / 'command.json').write_text(json.dumps(metadata, indent=2))
    if completed.returncode:
        raise RuntimeError(f'Query failed, see {directory}')
    lines = (directory / 'run.log').read_text().splitlines()
    measurements = [json.loads(line.split(' ', 1)[1]) for line in lines if line.startswith('COURSE_METRICS ')]
    assert len(measurements) == 1 and measurements[0]['L'] == budget
    row = measurements[0]
    row['mean_latency_us'] = 1_000_000 / row['qps']
    resource_text = (directory / 'resource.txt').read_text()
    row['peak_rss_kb'] = int(re.search(r'Maximum resident set size \(kbytes\):\s*(\d+)', resource_text)[1])
    ids = directory / f'results.L{budget}.ids.u32bin'
    assert ids.stat().st_size == 8 + 200 * 10 * 4
    row.update(tier=tier, bucket=bucket, variant=variant, repeat=repeat,
               result_sha256=sha(ids), elapsed_seconds=metadata['elapsed_seconds'],
               raw_directory=str(directory.relative_to(run_root)))
    print(f'{tier} {bucket} L={budget} r{repeat} {variant}: '
          f'Recall={row["recall_percent"]:.2f}% latency={row["mean_latency_us"]:.1f}us '
          f'tunnel={row["tunnel_time_us"]:.1f}us', flush=True)
    return row


def write_csv(path, rows):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset-root', type=Path, default=Path('/lab/datasets/yfcc_course_v1'))
    parser.add_argument('--index-root', type=Path, default=Path('/lab/course_runs/indices/gateann'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = {'started_utc': datetime.now(timezone.utc).isoformat(),
                'source_commit': subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
                'source_status': subprocess.check_output(['git', '-C', str(ROOT), 'status', '--porcelain'], text=True),
                'configs': CONFIGS, 'repeats': 3, 'queries_per_process': 200,
                'parameters': {'threads': 1, 'beamwidth': 8, 'K': 10, 'mem_L': 0,
                               'cache_budget': 0, 'full_adj_neighbors': 32, 'backend': 'aio'},
                'binary_sha256': {v: sha(ROOT / f'build-{v}/tests/search_disk_index_yfcc')
                                  for v in ['baseline', 'optimized']},
                'cache_policy': 'No cache purge; one warm-up per variant/config; opposite pair order in repeat 2.'}
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    for variant in ['baseline', 'optimized']:
        cache = (ROOT / f'build-{variant}/CMakeCache.txt').read_text()
        expected = 'ON' if variant == 'optimized' else 'OFF'
        assert f'GATEANN_TUNNEL_BATCH_MERGE:BOOL={expected}' in cache
        assert 'USE_AIO:BOOL=ON' in cache and 'CMAKE_BUILD_TYPE:STRING=Release' in cache
        (args.output / f'CMakeCache-{variant}.txt').write_text(cache)
    # Debug correctness is checked before starting timing comparisons.
    debug = [run_one(args, 'debug_100000', 'high', 320, v, 1, args.output) for v in ['baseline', 'optimized']]
    assert all(r['recall_percent'] >= 80 for r in debug)
    write_csv(args.output / 'debug.csv', debug)
    rows = []
    for bucket, budget in CONFIGS:
        for variant in ['baseline', 'optimized']:
            run_one(args, 'formal_1000000', bucket, budget, variant, 0, args.output)
    for repeat in [1, 2, 3]:
        order = ['optimized', 'baseline'] if repeat == 2 else ['baseline', 'optimized']
        for bucket, budget in CONFIGS:
            for variant in order:
                rows.append(run_one(args, 'formal_1000000', bucket, budget, variant, repeat, args.output))
                write_csv(args.output / 'results.csv', rows)
    assert len(rows) == 30
    summaries, pairs = [], []
    for bucket, budget in CONFIGS:
        for variant in ['baseline', 'optimized']:
            group = [r for r in rows if (r['bucket'], r['L'], r['variant']) == (bucket, budget, variant)]
            assert len(group) == 3
            summary = {'bucket': bucket, 'L': budget, 'variant': variant}
            for metric in METRICS:
                values = [r[metric] for r in group]
                for suffix, val in [('median', statistics.median(values)), ('min', min(values)), ('max', max(values))]:
                    summary[f'{metric}_{suffix}'] = val
            summaries.append(summary)
        for repeat in [1, 2, 3]:
            a = next(r for r in rows if (r['bucket'], r['L'], r['repeat'], r['variant']) == (bucket, budget, repeat, 'baseline'))
            b = next(r for r in rows if (r['bucket'], r['L'], r['repeat'], r['variant']) == (bucket, budget, repeat, 'optimized'))
            pairs.append({'bucket': bucket, 'L': budget, 'repeat': repeat,
                          'latency_reduction_percent': 100 * (1 - b['mean_latency_us'] / a['mean_latency_us']),
                          'tunnel_reduction_percent': 100 * (1 - b['tunnel_time_us'] / a['tunnel_time_us']),
                          'recall_delta_pp': b['recall_percent'] - a['recall_percent'],
                          'io_delta': b['mean_ios'] - a['mean_ios'],
                          'identical_returned_ids': a['result_sha256'] == b['result_sha256']})
    write_csv(args.output / 'summary.csv', summaries)
    write_csv(args.output / 'pairs.csv', pairs)
    (args.output / 'summary.json').write_text(json.dumps(summaries, indent=2))
    print('COMPLETE: 30 measured rows, 15 pairs, plus unscored warm-ups and Debug checks.', flush=True)


if __name__ == '__main__':
    main()
