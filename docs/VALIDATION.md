# Local validation report

Date: 2026-09-23

## Environment

- macOS 26.6.2, arm64
- FFmpeg 9.0.2
- FFprobe 9.0.2
- Streamlink 8.6.1
- biliup 1.2.7

## Record test

Reference live room:

```text
https://live.douyin.com/694562812381
```

The Streamlink Douyin plugin resolved these qualities:

- `sd1`
- `sd2`
- `hd1`
- `full_hd1` (`best`)

The selected stream was recorded for 45 seconds:

- Video: H.264, 1920x1080, 60 fps
- Audio: AAC, 48 kHz, stereo
- TS size: approximately 44 MB
- TS duration: 45.099667 seconds
- Measured bitrate: approximately 8.25 Mbps

A no-transcode MP4 remux preserved the codecs and produced a valid 45.049 second file.

## Segmentation test

A 45 second TS file was split into nine MPEG-TS segments with a five second target. Actual segment durations varied from approximately 4 to 6 seconds because splitting follows keyframes. Concatenating the segments produced a valid 45.294 second TS file.

## Target profile test

Streamlink does not handle this Douyin profile URL directly:

```text
https://www.douyin.com/user/MS4wLjABAAAA2ey9DwV0eYSPdzOcDWjZ74iadAqMW75FINb5lbi5m257exzJwDZgZy9PSPg2Upzn
```

biliup resolved the same profile URL and correctly reported the stream as offline at validation time. This means biliup can own the profile watcher responsibility.

## Bilibili upload test

The test recording was uploaded as a private Bilibili submission:

- BVID: `BV1Xhh86HEuP`
- Title: `【录制验证】抖音直播测试｜2026-09-23 20:14 开播`
- Visibility: only self
- Copyright type: repost
- Source: `https://live.douyin.com/694562812381`
- Parts: two
- Upload state at verification time: under review

A second recording was appended as another part to verify the multi-part path. Both parts were processed by Bilibili and had non-zero durations.

## Operational findings

- Upload line `bda2` worked during validation.
- The default upload line probe encountered an expired TLS certificate for one CDN endpoint and was skipped.
- biliup emitted a checkpoint warning when the sandbox blocked its user data directory. Upload and submission still completed successfully.
- Production runs should give biliup a writable user data directory.

## v2.0.2 desktop and end-to-end validation

The final macOS package was rebuilt on 2026-09-23 and verified against the installed application at:

```text
/Users/webt/Applications/DouyinBiliRecorder.app
```

Validated behavior:

- The standard native launcher opened the desktop window successfully.
- The embedded Python runtime reported version `2.0.2`.
- The embedded biliup runtime reported version `1.2.7`.
- The control deck loaded with the default cache limit of `10 GB`, private upload selected, and delete-after-upload disabled.
- `一键开始` launched the recorder from the installed app and `停止` returned it to the stopped state.
- QR login produced a valid PNG without any proxy environment variables.
- A real Douyin live stream was recorded with the packaged biliup runtime for approximately 36 seconds.
- The packaged FFmpeg remuxed the recording to a valid 36.0 second MP4.
- The packaged biliup CLI uploaded the MP4 as a private Bilibili submission.
- The title included the anchor name and live start time.
- The resulting BVID was `BV1JBhb6ZEPZ` and was found by the title lookup path.

The test also confirmed that a direct network connection is attempted before the optional system-proxy fallback.
