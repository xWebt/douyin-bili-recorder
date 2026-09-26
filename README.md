# DouyinBiliRecorder

抖音直播自动录制并上传 B站。应用会在稿件标题最前面写入主播名，并使用检测到的开播时间生成时间戳。

## 主要功能

- 监视一个或多个抖音直播间或主播主页。
- 多个主播并发录制，每个主播独立保存会话状态、排班、权限和 B站合集。
- 一场直播按一小时一个 P 录制和上传，第一个 P 创建稿件，后续 P 追加到同一 BVID。
- 默认原画直传，不额外复制 MP4；可选 1080P、720P、480P 和 60/30 FPS 转码。
- 全局录制质量会显示一小时预计占用和转码瞬时峰值。
- 当前段上传时继续录制下一段，并在主界面显示上传百分比、速度、剩余时间和 BVID。
- 支持录制视频或仅监控数据，不录制时仍会保存开播、时长和迟到统计。
- 支持按主播开启弹幕录制；系统会保存 XML，并将慢速、错开的右到左滚动弹幕烧录进投稿视频。
- 应用内置 Noto Emoji 回退字体，中文和常用 emoji 会在烧录视频中正常显示，不要求用户手动安装字体。
- 每个主播可分别选择公开投稿或仅自己可见。
- 全局可选择确认 BVID 后删除本地录制文件。
- 本地缓存默认限制为 10 GB，可手动调整。
- 一键开始、停止、重启，并在异常退出后自动拉起。
- 暂停或停止前会询问上传还是保留当前内容，不会静默结束。
- 视频按 `视频目录/主播/日期/录像` 保存，并提供视频库入口。
- 主播详情页提供月度直播天数、场次、迟到日、迟到场次和图表。
- 内置 B站扫码登录、运行状态、缓存占用和历史日志。
- 最终 macOS 成品不要求梯子；网络请求默认直连，直连失败时才尝试系统代理。

## macOS 安装

从 GitHub Release 下载 `DouyinBiliRecorder-macos-arm64.zip`，解压后将 `DouyinBiliRecorder.app` 放入“应用程序”目录。应用要求 Apple Silicon 和 macOS 12 或更高版本。

首次打开如果被 Gatekeeper 拦截，可在 Finder 中右键应用并选择“打开”。公开分发若要去掉该提示，需要 Apple Developer ID 签名和公证。

用户数据保存在：

```text
~/Library/Application Support/DouyinBiliRecorder
```

## 使用流程

1. 打开应用。
2. 如果未登录，点击 `B站登录` 并使用 B站手机客户端扫码。
3. 添加抖音直播间或主播主页链接。
4. 选择公开或仅自己可见。
5. 设置缓存上限以及投稿成功后是否删除本地文件。
6. 点击 `一键开始`。

## 开发与构建

```bash
./scripts/install-tools.sh
./scripts/build-macos-app.sh
```

构建产物位于：

```text
dist/DouyinBiliRecorder.app
dist/DouyinBiliRecorder-macos-arm64.zip
```

详细说明见 `docs/DESKTOP.md`、`docs/PRODUCT.md` 和 `docs/VALIDATION.md`。
