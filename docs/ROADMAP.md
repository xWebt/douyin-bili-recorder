# 实施路线图（基于 PROJECT_HANDOFF 建议优先级）

本文件把 `docs/PROJECT_HANDOFF.md` 第三、四部分的建议转成可执行的里程碑，并跟踪落地状态。
状态标记：`[ ]` 未开始，`[~]` 进行中，`[x]` 已完成并验证。

## 总原则

- 每个里程碑独立可验证，完成后运行全量测试并提交 Git。
- 状态变更以事务为单位，禁止“只修当前一条数据”的一次性补丁。
- 恢复流程必须是通用流程：任何会话、任何分 P、任何驱动都走同一条路径。
- 保持现有删除规则不变：B站与（开启的）网盘都成功后才允许删除本地。

## M1 SQLite 状态源 + 统一状态机 + append 幂等

- [x] 新增 `db.py`：SQLite（WAL）存 `anchors / sessions / parts / upload_jobs / stats / meta`。
- [x] 新增 `part_state.py`：分 P 统一状态机与合法迁移表。
- [x] `SessionStore` 改为 SQLite 唯一真相源，`session.json` 降级为调试快照。
- [x] 首次打开自动从既有 `*/session.json` 导入历史数据（无需人工迁移）。
- [x] 新增事务化 `SessionStore.update()` / `set_part_state()`，UI 与 worker 并发写不再丢更新。
- [x] B站 append 幂等：投稿前校验分 P 是否已存在，成功后落 `upload_jobs` 幂等键。
- [x] 网盘任务同样落 `upload_jobs`，崩溃恢复后不重复上传已完成的 P。
- [x] 测试：`tests/test_db.py`、`tests/test_part_state.py`、`tests/test_idempotent_upload.py`。

## M2 QuarkPan 分片并发基准测试

- [x] 新增 `scripts/quark_benchmark.py`：分片大小 × 并发数 × 文件大小矩阵，输出吞吐与风控观察。
- [x] 支持 `--dry-run`：无凭据时用本地回环目标验证分片/并发/合并逻辑。
- [x] 输出 JSON + Markdown 报告到 `data/benchmarks/`。
- [ ] 用真实夸克 Cookie 实测并记录拐点（需要用户提供凭据与网络授权）。

## M3 CloudUploadDriver 抽象

- [x] 新增 `cloud/driver.py`：统一驱动协议（`ensure_dir / upload / probe / capabilities`）。
- [x] `openlist` 驱动封装现有 OpenList 原生 API 与 rclone 回退。
- [x] `quark` 驱动：私有 API 分片并发上传（默认关闭，需显式启用）。
- [x] `baidu` 驱动：bypy-next/CLI 分片并发。
- [x] `RcloneCloudUploader` 委托驱动，保持既有调用方与删除规则不变。
- [x] 驱动选择、能力上报、失败回退统一在一个注册表。

## M4 退出子进程回收 + 单实例加固

- [x] 子进程统一登记：FFmpeg、biliup、rclone、OpenList 走同一回收器。
- [x] 退出/强退时按 SIGINT → SIGTERM → SIGKILL 清理进程组，并校验残留。
- [x] 单实例锁记录 pid/启动时间，陈旧锁自动回收，活锁拒绝启动。
- [x] 启动时通用 stale 进程清理（含 OpenList / rclone / ffmpeg）。
- [x] 测试：进程回收顺序、陈旧锁回收、活锁拒绝。

## M5 GUI 分区与状态展示

- [x] 固定窗口布局：侧栏 + 内容区，各区域内部滚动，页面不无限变长。
- [x] 侧栏拆分：总览 / 主播监控 / 录制状态 / B站上传队列 / B站稿件状态 / 网盘上传 / 视频库 / 日志 / 统计报告。
- [x] 主播卡片：检测、开播、录制、上传、等待空间、异常状态与占用空间分开显示。
- [x] 上行/下行状态轮询改为差量渲染，刷新不打断输入、不闪烁。
- [x] 浅色主题，上传列表操作按钮（暂停/重试/停止/删除），全局暂停三选项。

## M6 统计报告与 PDF 导出

- [x] 周报/月报按期生成，月度未结束不生成完整月报（标注“截至 X 日”）。
- [x] 图表：开播天数、场次、时长、迟到分钟、按时率。
- [x] 每主播独立报告入口与导出 PDF。
- [x] 报告文件按主播归档到 `视频根目录/主播/数据报告/`。

## M7 带宽调度

- [x] 新增 `bandwidth.py`：全局调度器，B站上传优先，网盘限速/降优先级。
- [x] 网盘并发可在设置中限制（默认 1，避免抢占 B站带宽）。
- [x] 支持 rclone `--bwlimit` 与 OpenList 驱动的等效限速。
- [x] 运行时设置可热更新，无需重启 worker。

## 验证记录

- 基线：`124 passed, 1 failed`（失败项为沙箱禁止 socket bind，非代码缺陷）。
- M1–M7 完成后：`171 passed, 1 failed`，失败项同上（`tests/test_recorder.py` 需要真实监听端口）。
- 提交记录：
  - `feat(state): SQLite source of truth, part state machine and idempotent uploads`
  - `feat(process): shared child registry, escalating reaping and auditable single-instance lock`
  - `feat(cloud): driver abstraction (quark/baidu/openlist/rclone), bandwidth scheduler and quark benchmark`

## 仍需真实环境确认

- 夸克分片并发实测：`scripts/quark_benchmark.py --dry-run` 已验证分片/并发/报告链路；真实吞吐需在装有 Quark CLI 或 OpenList 的机器上跑矩阵。
- GUI 视觉走查：布局/结构与静态服务已通过测试，仍需在 macOS 窗口内确认滚动、间距和报告按钮。
- 打包：`APP_VERSION=2.3.0 scripts/build-macos-app.sh` 与签名校验需在带网络/证书的环境执行。
