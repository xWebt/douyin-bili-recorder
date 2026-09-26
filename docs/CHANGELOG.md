# Changelog


## v2.2.8

- Bundled Noto Emoji and added per-glyph emoji font overrides so characters such as `🥚` render instead of appearing as tofu boxes.
- The application no longer depends on a user manually installing an emoji font; the bundled font is copied into the macOS application runtime alongside the web assets.


## v2.2.7

- Fixed sparse burned-in danmaku caused by holding a lane for the full 13-22 second scroll duration and enforcing a 0.65 second global launch gap.
- Lanes are now reusable after 0.35 seconds and launches remain globally staggered by 0.20 seconds, so a 16.68 second validation segment now schedules all 64 recorded comments inside the segment instead of only 10.


## v2.2.6

- Moved danmaku rendering into the application pipeline: when an anchor has `record_danmaku` enabled, the XML is converted to ASS and burned into an MP4 before the normal Bilibili upload queue.
- Danmaku now scrolls from right to left with ten lanes, slower travel time, and at least 0.65 seconds of launch staggering.
- Live checks now fall back to a short stream-gears probe when Douyin's room API reports a resolved room as offline, avoiding skipped broadcasts without starting a long-lived server for truly offline rooms.
- Added burn-in peak-space accounting so origin/source recordings reserve room for both the original segment and the rendered MP4.
- Added regression coverage for ASS motion, staggered timing, temporary ASS cleanup, and pipeline handoff to the rendered MP4.



## v2.2.5


- The app uses `uploader = Noop` plus a no-op postprocessor in danmaku mode so biliup only captures media/XML and the existing recorder uploader still owns Bilibili submission.
- Added a per-anchor `录制弹幕` option; enabled anchors now use biliup's documented `server --config` mode with `douyin_danmaku = true` and keep the generated XML beside each video part.
- Added XML cleanup to the existing `投稿成功后删除本地` behavior.
- Made the Bilibili submission list a bounded scrollable window so the control page no longer grows indefinitely.
- Confirmed from biliup docs that the simple `download` command exposes only URL/output/split options; danmaku recording is a server config feature.

## v2.2.4

- Fixed the PDF summary layout so metric cards, chart titles, charts, and the statistics note no longer overlap.
- Added a per-anchor report button with explicit choices for the current week through today, the previous complete week, and the previous complete month.
- Monthly reports are no longer generated for an incomplete current month; the report API rejects incomplete months and incomplete weeks unless current-week partial generation is explicitly requested.
- Corrected凡晨's local September analytics to two real sessions: `2026-09-24 00:48` and `2026-09-25 00:52`, removing the `00:52` offline ghost record.

## v2.2.3

- Fixed scheduled prechecks being delayed by offline probes. A probe with no media now terminates immediately instead of entering the full reconnect grace period; real recordings still keep reconnect behavior.
- Added per-upload progress records keyed by anchor session and part, with parallel upload workers for multiple enabled anchors.
- Added a Bilibili submission status list for locally submitted BVIDs, showing the actual API stage such as `审核中` or `已发布` without inventing a transcode percentage.
- Added weekly and monthly PDF reports with live days, sessions, total and average duration, on-time rate, late counts, reconnect counts, delay chart, duration chart, and session details.

## v2.2.2

- Prevented offline poll attempts with no media and no BVID from being counted as live sessions.
- Cleaned existing ghost analytics entries when analytics are refreshed.
- Added regression coverage for offline-poll filtering.

## v2.2.1

- Fixed hourly boundaries being split into 10-second P2/P4 fragments by keeping the upstream pull process alive across splits.
- Changed normal recording to keep one continuous upstream pull process across hourly splits, eliminating the old stop/restart recording gap.
- Preserved the final partial segment when a stream truly ends, so tail content is not discarded.
- Added regression coverage for continuous capture and final-part preservation.

## v2.2.0

- Added global recording quality and frame-rate selection with one-hour storage estimates.
- Added direct original-FLV upload for the default origin/source profile, avoiding the previous FLV plus MP4 double-space peak.
- Added configured-allocation and physical free-space guards before each segment; recording pauses rather than overrunning the budget.
- Added a serialized background upload queue so the next hour records while the previous part uploads.
- Added live upload progress to the main control deck with part, bytes, percent, speed, ETA, stage, and BVID.
- Validated direct FLV submission with a private Bilibili test upload (`BV1nPhZ6yEwT`).

## v2.1.5

- Fixed unsaved anchor settings being replaced by the three-second service status refresh.
- Fixed fixed-schedule mode jumping back to all-day polling after saving.
- Hid the schedule editor completely in all-day polling and manual-start modes.
- Fixed the link resolver and add-anchor buttons being placed on a second, poorly aligned form row.
- Validated a real multipart Douyin recording and Bilibili upload through P04 with the live-start title preserved.

## v2.1.4

- Added a native macOS app icon combining an eye outline with a red recording dot.
- Added the icon source, reproducible icon build script, PNG preview, and ICNS bundle asset.

## v2.1.3

- Added explicit per-anchor watch modes: fixed schedule, all-day polling, and manual start.
- Removed the automatic `1,3,5` schedule row when no schedule was configured.
- Added a configurable global polling interval, defaulting to 30 seconds.
- Added a per-anchor manual-start action that asks the running service to check immediately.
- Migrated existing anchors without a schedule to all-day polling compatibility.

## v2.1.2

- Fixed schedule polling when the current time includes a timezone and the schedule time did not.
- Added regression coverage for timezone-aware weekly schedules.

## v2.1.1

- Added a per-anchor save button so schedule, visibility, monitor mode, and collection settings can be saved directly from the anchor card.
- Profile-link resolution now adds or updates the anchor and persists it automatically.
- Adding an anchor through the form now saves immediately instead of requiring a separate global save.

## v2.1.0

- Added per-anchor public/private submissions, record-only or monitor-only mode, independent Bilibili collections, and weekly schedules.
- Added one-hour multipart uploads with a new BVID for P1 and append operations for later parts.
- Added safe pause/stop handling that finalizes the active partial file and asks whether to upload or keep it locally.
- Added reconnect grace handling so brief stream drops continue the same session and do not count as another late arrival.
- Added five-minute late detection, late-day and late-session analytics, monthly JSON records, and anchor detail charts.
- Added configurable video storage rooted at `video root / anchor / date / recording`.
- Added profile-link resolution for stable anchor names and fallback live probing when a fixed web room id is not exposed.
- Fixed cache display to show current usage versus saved allocation and added next-segment hot reload.

## v2.0.2

- Replaced the fragile PyInstaller macOS app wrapper with a standard native launcher and relocatable runtime directory.
- Fixed the desktop entrypoint so double-clicking the app opens the control deck instead of exiting through an internal argument error.
- Changed Bilibili login to try a direct connection first and use the system proxy only as an automatic fallback.
- Added standard macOS platform metadata and lowered the launcher deployment target to macOS 12.
- Cleared legacy application bundles, launchd files, logs, locks, and temporary build artifacts from the local installation.
- Revalidated QR login, packaged recording, FFmpeg remuxing, private Bilibili upload, and BVID lookup.

## v0.1.0

- Captured the validated local PoC.
- Recorded the tested FFmpeg, FFprobe, Streamlink, and biliup versions.
- Documented stream codec, bitrate, segmentation, and Bilibili upload results.

## v0.2.0

- Added the production Python project.
- Added session state and recovery.
- Added the Biliup recorder adapter.
- Added no-transcode MP4 remuxing.
- Added Bilibili first-part upload and additional-part append.
- Added the anchor-first title template.
- Added launchd generation and dependency checks.
- Added unit tests and local validation of the offline target path.

## v2.0.0

- Added a local control deck with target management and one-click service control.
- Added Bilibili QR login in the interface.
- Added public/private upload selection.
- Added a configurable 10 GB default local recording cache limit.
- Added the option to delete local media after a verified BVID is returned.
- Added multi-target concurrent recording support.
- Added a packaged macOS desktop application and ZIP distribution artifact.

## v2.0.1

- Fixed packaged-app recorder startup by routing internal worker execution through the app entrypoint.
- Fixed Bilibili QR generation by using browser-compatible request headers.
- Added automatic macOS system proxy detection for Bilibili login.

## v1.0.1

- Include the anchor name and live start time in every additional Bilibili part title.

## v1.0.0

- Finalized documentation and operational workflow.
- Added the title correction record for the validated Bilibili submission.
- Prepared the repository for GitHub versioning and tagged releases.
