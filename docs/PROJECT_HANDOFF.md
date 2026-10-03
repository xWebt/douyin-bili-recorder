# 抖音直播录制器项目交付说明

## 1. 项目地址

- GitHub 仓库：
  - https://github.com/xWebt/douyin-bili-recorder
- 当前主分支：
  - `main`
- 当前版本：
  - `v2.2.68`
- 当前源码提交：
  - `448e25a chore: release v2.2.68`
- 本地源码目录：
  - `/Users/webt/Documents/Codex/2026-09-23/files-mentioned-by-the-user-douyin`

## 2. 本地地址

- 本地应用：
  - `/Users/webt/Applications/DouyinBiliRecorder.app`
- 当前本地控制台：
  - http://127.0.0.1:63878/
- 控制台端口：
  - 每次重新打开应用可能变化。以应用启动后实际显示的地址或当前监听端口为准。
- 应用运行数据：
  - `/Users/webt/Library/Application Support/DouyinBiliRecorder`
- 运行配置：
  - `/Users/webt/Library/Application Support/DouyinBiliRecorder/data/ui/runtime-config.toml`
- 会话状态：
  - `/Users/webt/Library/Application Support/DouyinBiliRecorder/data/sessions`
- 日志目录：
  - `/Users/webt/Library/Application Support/DouyinBiliRecorder/data/logs`
- 主要日志：
  - `/Users/webt/Library/Application Support/DouyinBiliRecorder/data/logs/recorder.log`
  - `/Users/webt/Library/Application Support/DouyinBiliRecorder/data/logs/ui-worker.log`
- 视频目录：
  - `/Users/webt/Movies/DouyinBiliRecorder`
- OpenList 数据：
  - `/Users/webt/Library/Application Support/DouyinBiliRecorder/openlist-data`
- 本地 OpenList 服务：
  - http://127.0.0.1:5244/

## 3. 做好的成品是什么

这是一个 macOS 桌面应用加后台录制服务，主要能力如下：

- 多主播同时监控和录制。
- 支持抖音主页、直播间和分享短链解析。
- 支持固定排班、全天轮询、手动检测。
- 每 1 小时切一个 P。
- 同一场直播的 P1、P2、P3 共用一个 B站 BVID，后续 P 使用 append 追加。
- 录制和上传并行执行，不等待整场直播结束。
- 多主播、多 P 上传互不阻塞。
- 支持公开或仅自己可见投稿。
- 支持每个主播单独设置合集、弹幕、网盘和排班。
- 支持弹幕烧录，弹幕从右向左滚动并分轨错开。
- 支持 B站上传队列、进度、速度、ETA、BVID 和稿件状态。
- 支持夸克/百度等网盘备份。
- 支持 B站上传和网盘备份分别暂停、重试、停止和补传。
- 支持应用退出后结束进程，重新打开后恢复未完成上传。
- 支持主播排班和固定开播时间，避免全天过度轮询。
- 支持主播直播数据统计、图表、周报和月报导出。
- 本地目录按主播、日期、场次和 P 分目录保存。

## 4. 当前删除规则

- 如果主播没有开启网盘备份：
  - B站上传成功后可以删除本地。
- 如果主播开启了网盘备份：
  - B站和网盘都上传成功后，才删除本地。
- 正在录制、待上传、上传中、网盘未完成和等待重试的文件不能删除。
- 删除后不能残留 MP4、FLV、XML、弹幕工作目录和缓存。

## 5. 怎么做的

### 5.1 技术栈

- Python 3.14
- FastAPI：本地控制台和 API
- pywebview：macOS 桌面窗口
- PyInstaller：打包后台运行程序
- 原生 Objective-C 启动器：生成标准 macOS `.app`
- biliup / stream-gears：抖音直播流和弹幕下载
- FFmpeg：弹幕字幕渲染、视频重新封装
- Biliup CLI：B站投稿和分 P append
- OpenList：夸克、百度等网盘统一接入
- rclone：与 OpenList WebDAV/API 交互
- ThreadPoolExecutor：并行上传任务
- `flock` 文件锁：单实例和单 P 上传互斥
- JSON / TOML：会话、配置、上传状态和统计持久化

### 5.2 主要模块

- `src/douyin_bili_recorder/pipeline.py`
  - 录制、分段、恢复、上传、网盘、清理和统计主流程。
- `src/douyin_bili_recorder/uploader.py`
  - B站投稿和 append 上传。
- `src/douyin_bili_recorder/cloud_uploader.py`
  - 网盘上传。
- `src/douyin_bili_recorder/openlist_api.py`
  - OpenList 原生上传接口。
- `src/douyin_bili_recorder/service_control.py`
  - 服务启停、状态、进程管理和上传控制。
- `src/douyin_bili_recorder/runtime_cleanup.py`
  - 旧进程清理和应用单实例保护。
- `src/douyin_bili_recorder/webapp.py`
  - 本地控制台 API。
- `src/douyin_bili_recorder/web/`
  - 前端界面、样式和交互。

### 5.3 核心设计

- 一场直播一个 `session.json`。
- 每个小时一个 `SessionPart`。
- P1 创建 B站稿件，后续 P 通过 append 使用同一个 BVID。
- 上传队列、网盘队列和录制线程分离。
- 每个 P 使用独立文件锁，避免重复上传。
- 启动时扫描未完成会话、中断的 `.part`、孤儿 MP4，并自动恢复。
- 应用级控制锁和 worker 锁防止多开和重复录制。
- 应用关闭时只终止当前应用进程，不破坏已完成状态。
- 重新打开后自动恢复待上传和待备份任务。
- 清理逻辑按 B站状态和网盘状态共同判断，不能只依赖单一状态字段。
- 本地文件结构固定为：
  - `视频根目录 / 主播名 / 日期 / 场次目录 / P01、P02...`

## 6. 构建与测试

- 构建命令：
  - `APP_VERSION=2.2.68 scripts/build-macos-app.sh`
- 测试命令：
  - `PYTHONPYCACHEPREFIX=/private/tmp/douyin-pycache .venv/bin/pytest -q`
- 最近测试结果：
  - `125 passed`
- 应用签名校验：
  - `codesign --verify --deep --strict /Users/webt/Applications/DouyinBiliRecorder.app`
- 打包产物：
  - `dist/DouyinBiliRecorder.app`
  - `dist/DouyinBiliRecorder-macos-arm64.zip`

## 7. 当前运行状态

- 本地服务正在运行。
- 当前 worker 正在录制或处理上传任务。
- 当前控制台：
  - http://127.0.0.1:63878/
- 当前本地占用和限额以控制台显示为准。
- 如果重新启动应用，控制台端口可能变化，应以新窗口地址为准。

## 8. 已知问题

- 夸克网盘通过 OpenList 上传时速度较慢。
- 当前链路：
  - 录制程序
  - 本机 OpenList
  - 夸克私有 API
  - 夸克网盘
- rclone remote 当前是 WebDAV 类型，实际仍由 OpenList 转发上传。
- 夸克会员是否加速官方客户端，不等于第三方 OpenList API 会加速。
- 当前实测 P02 网盘上传约为 14.5 Mbps，B站上传约为 24.7 Mbps。
- 后续优先调研：
  - 夸克私有 API 分片并发上传。
  - 支持多分片并发的夸克 SDK 或 CLI。
  - 官方客户端上传目录与自动化的配合方案。
  - 其他支持并行上传且稳定的网盘后端。

## 9. 版本管理

- 重要版本：
  - `v2.2.60`
  - `v2.2.61`
  - `v2.2.62`
  - `v2.2.63`
  - `v2.2.64`
  - `v2.2.65`
  - `v2.2.66`
  - `v2.2.67`
  - `v2.2.68`
- 每次修改应提交到 Git，并在验证后打标签。
- 出现问题时可以回退到旧 tag 或旧 commit。
