# Confirmed requirements

This document is the implementation baseline approved on 2026-09-23. Later code changes must preserve these behaviors unless the user explicitly changes them.

## Recording and upload

- Record Douyin live streams and upload them to Bilibili.
- The Bilibili title must start with the anchor name and include the detected live start time and room title.
- Upload success must be verified by finding the resulting BVID before local media is eligible for deletion.
- Failed or unverified uploads keep local media and remain retryable.
- Multiple anchors may record concurrently.
- The application must not require a VPN or a hard-coded proxy. It tries a direct connection first and may fall back to the active macOS system proxy.
- A QR-code login flow must remain available for Bilibili.

## Settings scope

Global settings:

- Auto-restart after unexpected process exit.
- Delete local media after a verified upload.
- Total local cache allocation.
- Bilibili account and cookie.
- Video root directory.
- Default upload line.
- Segment length, default one hour per part.
- Late threshold, fixed at five minutes.
- Reconnect grace period, default fifteen minutes and configurable.

Per-anchor settings:

- Anchor name and source URL.
- Enabled state.
- Public or private Bilibili submission.
- Record video or monitor data only.
- One or more weekly live-time slots.
- Independent Bilibili collection.
- Title template, tags, partition, copyright, and source metadata.
- Anchor detail page, statistics, and folder shortcuts.

## Link resolution and live detection

- Accept live-room URLs, profile URLs, `www.douyin.com/live/...` URLs, and `v.douyin.com` short links.
- A profile URL must resolve to stable anchor and room identifiers while the anchor is offline.
- The application must not require the user to wait until a live starts before obtaining a usable room identifier.
- Starting a live must trigger recording automatically.
- Ending a live must trigger segment finalization and upload.
- Invalid or blocked links must show a concrete error instead of silently skipping the anchor.

## One-hour multipart recordings

- A single live event maps to one Bilibili submission.
- The first completed hour becomes P1 and creates the BVID.
- Each later completed hour is appended to the same BVID as P2, P3, and so on.
- The final partial segment at stream end is appended as the last part.
- A later part may upload while the recorder continues producing the next part.
- Every part is independently remuxed, uploaded, verified, and optionally deleted.
- The segment prefix and part title include the anchor name and live start time.

## Pause, stop, and data protection

- Pause or stop must open a confirmation UI instead of silently ending the recording.
- The UI offers: continue recording, pause and upload current content, or pause and keep local media.
- Pause-and-upload must let the active process finalize its `.part` file, remux it, then upload or append it.
- Closing the application while recording uses the same confirmation flow.
- A failed pause upload leaves local media and shows a pending-upload state.
- A `.part` file containing real data must never be deleted merely because a small initialization `.flv` is below the minimum-size threshold.
- Regression tests must cover the previously observed data-loss scenario where stopping deleted the active recording.

## Video library

- The application provides a visible video-library entry.
- It can open the global video root, one anchor directory, or one live-session directory.
- The default root is `~/Movies/DouyinBiliRecorder` and is configurable.
- Directory layout is `video root / anchor name / date / recordings`.
- Same-day live events are distinguished by detected start time.
- File names include start time, room title, and part number.
- Original FLV or TS files live in the same dated directory when originals are retained.
- The library shows size, part count, upload status, and BVID.

## Live schedule and polling

- Every anchor starts with one editable live-time row.
- Users may add more rows for multiple weekly sessions.
- Rows include weekdays, expected start, expected end, and enabled state.
- Overnight ranges such as `23:30` to `02:00` are supported.
- Polling starts shortly before the expected start time.
- Polling continues at a low frequency during the live window.
- Polling is reduced outside scheduled windows.
- A manual immediate-check action ignores the schedule.
- Anchors without a schedule keep continuous-polling compatibility.

## Reconnection behavior

- A temporary stream interruption does not create a new live event.
- Reconnection inside the configured grace period continues the same session, BVID, and part sequence.
- Reconnection does not create another late event.
- The first detection after the scheduled start plus five minutes is late.
- A return after the reconnect grace period closes the old session and starts a new one.
- A new session caused by an expired reconnect gap is marked `断流超时重开`, not as a second late arrival.
- Polling frequency increases during a disconnect to detect a restart quickly.

## Analytics and charts

- Track per-month live days, live sessions, late days, and late sessions.
- A late day is counted once per date even if multiple sessions were late.
- Every late session is shown separately in the session detail table.
- Track expected start, actual start, end, duration, delay minutes, reconnect count, and reconnect duration.
- Store analytics under the anchor directory in a `直播数据` folder.
- Keep an internal copy to survive video-folder moves.
- Upload failure or local deletion does not remove analytics.
- The anchor detail page shows summary cards, a monthly calendar heatmap, start-delay chart, duration chart, and a session table.
- Charts must work without loading remote JavaScript.

## Per-anchor Bilibili collections

- Each anchor has an independent Bilibili collection.
- The first successful upload creates or binds the collection automatically when possible.
- All later recordings for that anchor are attached to the same collection.
- One live event remains one BVID with multiple parts.
- Collection failures do not block video upload and are retried later.
- The interface shows collection name, collection ID, and binding state.

## Monitor-only mode

- Monitor-only mode does not download video or create FLV, TS, or MP4 files.
- It does not upload to Bilibili.
- It still detects live start and end and records duration and late/reconnect data.
- Anchors may switch between monitor-only and recording modes without losing analytics.

## Cache display and hot reload

- The cache display format is `current local usage / total allocation`, for example `0.26 GB / 30 GB`.
- The total allocation comes from the saved global cache setting.
- A running recorder must not pretend a newly saved cache value is already active.
- If the active worker still uses an older value, the UI must show both the saved allocation and the active value.
- The new allocation should apply at the next hourly segment boundary without interrupting recording.

## Recording quality, peak space, and upload progress

- Global recording settings include quality (`原画`, `1080P`, `720P`, `480P`) and frame rate (`原始`, `60 FPS`, `30 FPS`).
- The UI recalculates the estimated one-hour storage after either setting changes.
- The default `原画 + 原始帧率` path uploads the original FLV segment directly and does not create a second MP4 copy.
- Selecting a lower quality or fixed frame rate explicitly enables FFmpeg transcoding and shows the estimated transient peak.
- Before starting each segment, the recorder checks both the configured allocation and physical free space against the selected transcode peak.
- When space is insufficient, the recorder pauses before the next segment and resumes after uploads release storage.
- Completed segments are uploaded through a serialized background queue so recording the next segment does not wait for the previous upload.
- Normal hourly splitting keeps the same upstream pull process running across boundaries so no content is omitted while a part is prepared or uploaded.
- The main control deck shows current part, uploaded bytes, total bytes, percent, speed, ETA, stage, and BVID.
- Upload failure is shown without stopping the active recording.
