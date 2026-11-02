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

## 实际对照结果

实验标识：`gateann-opt-20261102-165820`；时间：2026-11-02。运行代码提交为 `e0f137ebbb97049f70addb4d4c3228ee9f18ce8c`。

环境：Apple M4、24 GiB 宿主内存；Docker Ubuntu 22.04 linux/amd64、10 vCPU、7.65 GiB RAM，GCC 11.4、Release、AIO。正式索引与数据校验通过。宿主前后 1 分钟负载为 3.45/3.50。

下表是各组 3 次独立进程的中位数，括号内是最小-最大范围。时延降低率按 `1 - 优化版中位数 / 原版中位数` 计算；它不同于配对降低率的中位数，后者保留在 `pairs.csv`。

|负载|L|原版时延 μs|优化版时延 μs|中位数时延降低率|Recall 原版/优化版 %|
|---|---:|---:|---:|---:|---:|
|high|160|553.7 [552.0, 563.1]|522.1 [517.8, 531.4]|+5.71%|81.25/81.25|
|high|320|1055.3 [1015.6, 1078.3]|1017.1 [976.9, 1021.0]|+3.62%|93.20/93.20|
|high|640|2178.2 [2062.7, 2211.4]|1917.8 [1884.4, 2028.0]|+11.96%|98.65/98.65|
|medium|320|767.2 [765.5, 1061.8]|778.0 [744.0, 798.2]|-1.41%|72.05/72.05|
|low|320|662.0 [642.0, 699.8]|639.3 [608.9, 809.0]|+3.43%|34.30/34.30|

四组的均值查询时延中位数下降，Medium 组上升 1.41%。High L=640 的三对逐轮降低率约 8.30%-11.96%，但不能据此宣称所有负载都加速。Tunnel_us 并非所有组都下降（如 High L=320、Medium 的中位数上升）；端到端变化也受到流水化 I/O、执行顺序和调度影响，尚无子阶段剖析证明收益全部来自候选归并。

15 个配对的 Recall 差值均为 0；其中 13 对返回的全部 200×10 个 ID 完全相同。另 2 对分别有 1/2 条查询的 ID 集合不同，但 Recall 不变；原版 High L=160 自身跨轮也出现不同 ID，说明异步搜索存在运行波动。差分测试只证明候选池局部操作等价，不构成全查询结果逐位确定性的证明。

逻辑 I/O 的最大配对绝对差为 0.08 次/查询；不将这类微小变化写成物理 I/O 优化。查询峰值 RSS 的中位数一般增加约 60-64 KiB，Low 增加约 248 KiB（含进程、栈、分配器等影响），不能全部归因于理论临时数组大小。Low 固定预算下 Recall 仍为 34.30%，本次优化不解决其质量不足。

两个 Release 变体均通过 21,600 个候选池差分用例；AddressSanitizer/UndefinedBehaviorSanitizer 也通过同一套用例。额外 sanitizer 编译须加 `-DNDEBUG`，与上游构建保持一致；未加该标志的第一次独立编译因上游断言引用缺少的 IS_ALIGNED 宏失败，该记录也保留在日志中。

原始数据与可复现证据：

- [逐轮结果](study/results/gateann-opt-20261102-165820/results.csv)、[三轮汇总](study/results/gateann-opt-20261102-165820/summary.csv)、[配对变化](study/results/gateann-opt-20261102-165820/pairs.csv)。
- [运行与二进制信息](study/results/gateann-opt-20261102-165820/manifest.json)，各运行目录包含实际命令、标准输出、进程资源记录和返回 ID 文件。
- [最终 sanitizer 结果](study/results/gateann-opt-20261102-165820/logs/sanitizer.log)、[编译记录](study/results/gateann-opt-20261102-165820/logs/build.log)、[数据及索引校验](study/results/gateann-opt-20261102-165820/logs/input-check.log)。

本轮没有混入 2026-10-19 的原课程对比数据，也没有修改原课程 PDF 或 Word 报告。
