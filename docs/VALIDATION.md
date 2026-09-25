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

## v2.1.0 multipart, schedule, and analytics validation

- Unit and integration tests cover configuration migration, five-minute late detection, overnight schedules, late-day and late-session aggregation, active partial-file preservation, multipart P1/P2 uploads, and collection API request construction.
- The final macOS bundle reports version `2.1.0` and biliup version `1.2.7`.
- The installed application passed ad-hoc signature verification and opened through the macOS application launcher.
- The control deck displayed cache usage as `0.00 / 30 GB` while separately showing the active process allocation.
- The pause confirmation dialog exposed upload, keep-local, and continue-recording choices.
- The video library, per-anchor detail view, schedule editor, per-anchor visibility, record/monitor mode, and collection fields were present and functional.
- A real authenticated request to the current Bilibili collection list endpoint succeeded.
- No live Douyin room was available at the final packaging moment, so the final packaged run did not repeat a real live download. The multipart state machine was validated with deterministic recorder/media/uploader test doubles.

## v2.1.5 live multipart and watch-mode validation

The source build was validated on 2026-09-24 against a real Douyin live room at `https://live.douyin.com/385030864044`.

- Four consecutive segments were recorded and remuxed without transcoding to MP4.
- P1 created Bilibili submission `BV1xJhf6pELR`; P2, P3, and P4 were appended successfully to the same BVID.
- The final session state was `UPLOADED`, and all four part states were `UPLOADED`.
- The title retained the anchor name and detected live-start timestamp: `安琪拉大王｜2026-09-24 00:50 开播｜全流程验证`.
- Monthly and aggregate analytics JSON files were written under the anchor video directory.
- Real browser interaction confirmed that fixed schedules save and remain selected after later status refreshes.
- Real browser interaction confirmed that all-day polling and manual-start modes hide the schedule editor, including after the periodic refresh.
- DOM geometry checks confirmed the anchor-name, link, resolver, and add buttons share one aligned form row.

The successful end-to-end fixture was left at `/private/tmp/dbr-e2e-success.5sRBS9` during validation.

## v2.2.1 encoding, space, queue, progress, and continuous-capture validation

- Unit tests cover the new quality/frame-rate estimates, direct-source media path, optional transcode path, and progress store.
- Pipeline tests verify that recording continues while the previous part is blocked in the upload queue.
- Regression coverage verifies a continuous process can finalize multiple full parts without an intermediate restart and that the final real partial is preserved.
- Recording is now driven by one continuous pull process; completed hourly files are detected and queued while the same process keeps receiving the next segment.
- A private 3-second FLV was uploaded directly to Bilibili without MP4 remuxing and verified as `BV1nPhZ6yEwT`.
- The control deck was exercised in a browser with a synthetic active upload and displayed 42% progress, speed, ETA, and part metadata.
- Changing quality to `720P` and frame rate to `30 FPS` updated the estimate to `1.75 GB / 小时` and showed a roughly `11 GB` transient peak warning including the original segment.

## v2.2.2 analytics cleanup validation

- Regression coverage verifies offline polling attempts with zero parts and no BVID are excluded from monthly analytics.
- Existing `00:21` and `00:37` offline-poll ghost sessions for 凡晨 were removed from local monthly and summary JSON files.

## v2.2.3 scheduling, status, parallel upload, and report validation

- Regression coverage verifies a fixed `00:30` schedule begins prechecking at `00:20`.
- Regression coverage verifies an offline probe without media exits immediately, while a real recorded session still enters reconnect grace after a drop.
- Upload progress storage now supports multiple concurrent entries keyed by session and part.
- Bilibili status parsing is covered for `审核中` and `已发布`; no numeric transcode percentage is fabricated because the current API does not provide one.
- PDF generation is covered for monthly reports and week ranges that cross a month boundary.
