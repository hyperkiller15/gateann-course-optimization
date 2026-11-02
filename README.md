# GateANN 隧穿候选池维护优化

基于 GateANN 固定提交 `71e87cbf0e25c0400c0109dd25a64a7c4dccc9dd`，保留上游 MIT 许可证和 [原始说明](README.upstream.md)。实验使用 [fvs-course-lab](https://gitee.com/wei-fangyu/fvs-course-lab) 的 YFCC 数据和预构建索引；数据和大型索引不包含在本仓库。

## 实现范围

- `src/search/pipe_search.cpp`：隧穿邻居的去重改为一次 `visited.insert(...).second`，代替 `find` 后再 `insert`。
- `include/utils/tunnel_pool_merge.h`：同一过滤失败节点的邻居计算完 PQ 距离后，排序并一次归并到有序候选池，减少重复搬移同一数组后缀。它不跨多个节点延迟探索，不修改 L、图结构、过滤谓词或 PQ 距离。
- 少于 4 个有效候选或出现距离相同时，回退上游逐个插入。归并先写临时缓冲，确认不需要回退后才更新候选池；保留 flag、visited 和 marker 语义。
- 临时归并数组在查询开始时分配一次，空间为 O(L+R)。这是设计代价，不声称零内存开销。
- 同时包含课程要求的 `cb.data` → `cb[j].data` AIO 编译修复；该修复在两个变体中完全相同，不计入性能优化。

CMake 开关 `GATEANN_TUNNEL_BATCH_MERGE=OFF/ON` 分别生成原路径和优化路径。两个变体使用相同编译器、Release/AIO 和测试入口。额外精确计时输出及结果 ID 保存发生在查询计时结束后。

## 编译与正确性测试

在课程 Ubuntu 22.04 环境中安装 `build-essential cmake libaio-dev libgoogle-perftools-dev libopenblas-dev libeigen3-dev python3 time` 后执行：

```bash
bash study/build.sh
```

测试程序将批量归并与上游逐个插入作差分对比，覆盖候选池容量 1/2/3/8/20/40/160/320/640、部分填充/已满、距离相同、被拒绝候选和状态位。不能仅依据编译成功推断正确性。

## 性能对照测试

```bash
python3 study/benchmark.py \
  --dataset-root /lab/datasets/yfcc_course_v1 \
  --index-root /lab/course_runs/indices/gateann \
  --output /lab/optimization/experiment-YYYYMMDD-HHMMSS
```

程序先运行两变体的 100k Debug 验证，再各做一次不计分的正式预热。正式测试采用 1M 数据；High L=160/320/640，Medium/Low L=320；线程=1、beamwidth=8、K=10、mem_L=0、缓存预算=0、FullAdj=32、AIO。每个配置每变体独立执行 3 个查询进程，每次 200 条查询，共 30 行正式结果。

每对配置连续运行两个变体，第 2 轮反转先后顺序。记录三轮中位数、范围和配对变化，保留全部慢轮；不清空客体或宿主缓存。Mean Latency 来自精确查询阶段 QPS 的倒数，不能使用含初始化的总进程时间替代。峰值 RSS 使用每个查询子进程的 `/usr/bin/time -v` 记录。逻辑 I/O 不等同物理磁盘 I/O。

`results.csv` 保存逐轮数据，`summary.csv` 保存中位数和范围，`pairs.csv` 保存同轮配对变化及返回 ID 是否完全相同。`command.json`、`run.log`、`resource.txt` 和二进制 ID 文件保留在各运行目录，供复查。实际测量结果在测试完成后添加到 `study/results/`。

性能受 Mac Docker 的 x86 兼容层、虚拟磁盘和后台负载影响。本实验只用于同一环境的受控对比，不能外推为原生 SSD 性能；优化是否有效以真实结果为准。
