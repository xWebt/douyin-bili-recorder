# Desktop application

`DouyinBiliRecorder.app` is the distributable Apple Silicon macOS application. It embeds the local control deck and opens it in a native WebKit window, so users do not need a terminal. macOS 12 or later is required.

## User workflow

1. Open the app.
2. Click `B站登录` and scan the QR code with the Bilibili mobile client.
3. Add one or more Douyin live-room or profile URLs.
4. For each anchor, choose `仅自己` or `公开`, recording or monitor-only mode, a collection name, and one or more weekly schedule rows.
5. Choose whether uploaded local media should be deleted. This remains a global setting.
6. Set the recording cache limit. The display shows current usage divided by the saved allocation.
7. Open the video library to view the root and per-anchor folders.
8. Click `一键开始`. Pause or stop asks whether the active segment should be uploaded or kept locally.

The application displays process PID, uptime, cache usage, current sessions, and live logs.

## Background behavior

The recorder is started as a detached process. The control deck supervises it every few seconds and automatically restarts it after an unexpected exit when `异常自动拉起` is enabled. A stop request is written to disk before a signal is sent, so the worker can exit cleanly even if process signaling is restricted.

Multiple enabled targets run concurrently. Each target gets its own session directory and recorder process. The cache limit is shared across all targets.

One live event is uploaded as one BVID. Every completed hour becomes a part: P1 creates the BVID and later parts are appended. A brief disconnect inside the reconnect grace period continues the same session and part sequence. A longer disconnect starts a new live event. Monitor-only mode records analytics without downloading video. Analytics are mirrored to `video root / anchor / 直播数据`.

## macOS build

Run:

```bash
./scripts/build-macos-app.sh
```

The script produces:

```text
dist/DouyinBiliRecorder.app
dist/DouyinBiliRecorder-macos-arm64.zip
```

The app is ad-hoc signed. Public distribution to users outside your own Mac requires an Apple Developer ID signature and notarization to avoid Gatekeeper warnings.

The build assembles a standard app bundle from a native launcher and a relocatable PyInstaller onedir runtime. It does not depend on the PyInstaller `.app` wrapper.

## Network behavior

Bilibili QR login tries a direct connection first. If the direct network request fails and macOS has an active system proxy, the login code retries through that proxy automatically. The application does not require a VPN or a hard-coded proxy.

## Bundled components

- Python runtime
- FastAPI and Uvicorn control server
- PyWebView desktop window
- biliup CLI
- FFmpeg and FFprobe

User data is stored under:

```text
~/Library/Application Support/DouyinBiliRecorder
```

The folder contains `config.toml`, the login cookie, UI settings, logs, and recorded sessions. Removing the application bundle does not remove this user data.
