# Desktop application

`DouyinBiliRecorder.app` is the distributable macOS application. It embeds the local control deck and opens it in a native WebKit window, so users do not need a terminal.

## User workflow

1. Open the app.
2. Click `B站登录` and scan the QR code with the Bilibili mobile client.
3. Add one or more Douyin live-room or profile URLs.
4. Choose `仅自己` or `公开`.
5. Choose whether uploaded local media should be deleted.
6. Set the recording cache limit. The default is `10 GB`.
7. Click `一键开始`.

The application displays process PID, uptime, cache usage, current sessions, and live logs.

## Background behavior

The recorder is started as a detached process. The control deck supervises it every few seconds and automatically restarts it after an unexpected exit when `异常自动拉起` is enabled. A stop request is written to disk before a signal is sent, so the worker can exit cleanly even if process signaling is restricted.

Multiple enabled targets run concurrently. Each target gets its own session directory and recorder process. The cache limit is shared across all targets.

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
