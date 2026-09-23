# DouyinBiliRecorder

抖音直播自动录制并上传 B站。应用会在稿件标题最前面写入主播名，并使用检测到的开播时间生成时间戳。

## 主要功能

- 监视一个或多个抖音直播间或主播主页。
- 多个主播并发录制，每个主播独立保存会话状态。
- 直播结束后无损转 MP4，不上传时保留本地文件。
- 可选择公开投稿或仅自己可见。
- 可选择确认 BVID 后删除本地录制文件。
- 本地缓存默认限制为 10 GB，可手动调整。
- 一键开始、停止、重启，并在异常退出后自动拉起。
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
