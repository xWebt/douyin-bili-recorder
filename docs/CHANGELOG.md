# Changelog

## v2.2.48
- Cloud-only retry now loads the UI runtime configuration instead of the packaged example configuration, so saved anchors and cloud remotes are included.

## v2.2.47
- Added a cloud-only retry task that processes only failed or pending cloud backups without creating any Bilibili upload task.
- Added per-anchor `补传网盘` and `停止网盘补传` controls.
- Cloud-only retry is blocked while the normal recorder service is running, preventing duplicate backup jobs.

## v2.2.46
- Bilibili duplicate-title checks now use one list request instead of three status-specific requests, with a 15 second cache shared by queued parts.
- The BVID cache is invalidated after each submission or append, so newly created submissions are still detected.

## v2.2.45
- Bilibili submissions are globally serialized with a 180 second minimum interval, preventing multi-anchor and multi-part bursts from triggering error `21566`.
- Cloud backups are serialized to avoid concurrent OpenList/WebDAV uploads, with longer rclone timeout and retry settings for large files.
- Cloud backup paths now use `anchor/date/file` instead of creating one `P01/P02/...` directory per part.
- Too-small or too-short segments are filtered before Bilibili upload, cloud backup, and startup recovery, including unknown-duration files that are re-probed.
- Origin-quality danmaku rendering now converts the probed bitrate from bit/s to kbit/s before passing it to FFmpeg, preventing oversized `maxrate` failures.

## v2.2.44
- Deleting an upload now removes its upload-progress record completely, so a deleted item cannot reappear as a phantom upload.
- Legacy deleted or unavailable upload-progress entries are purged when service status is read.
- Each anchor card now has separate recording and upload status badges, allowing recording state to remain visible while uploads are running, paused, stopped, or failed.
- The target-card renderer now tolerates old cached runtime shapes and includes the missing muted-state metadata, so the stopped-service state renders instead of crashing.

## v2.2.43
- App shutdown now stops the control server, recorder worker, biliup children, and app-owned OpenList instance, then clears the runtime PID.
- Stale OpenList processes left by older or interrupted runs are identified from their executable path and reclaimed on the next app launch or exit.
- Desktop shutdown handles SIGINT and SIGTERM in addition to normal window close, with a final `os._exit` after cleanup.

## v2.2.42
- Upload rows now provide `重试`, `暂停`, `停止`, and `删除`; deletion cancels the upload and removes the corresponding local video and danmaku files.
- Periodic service refresh now updates runtime text in place only and never rebuilds target cards, eliminating the three-second whole-page flicker.
- Historical `UPLOAD_FAILED` sessions no longer resurrect `CANCELED` or `DISCARDED` parts into the Bilibili upload queue.
- Startup recovery only schedules upload work when a session still has a retryable part.
- The SIGINT handler now reads the stop request file before choosing `upload`, `keep`, or `discard`; this fixes stop-and-delete racing back into upload mode.
- Discarding a session also removes danmaku runtime data and empty recording directories.

## v2.2.41
- The recorder now logs `no enabled targets configured` only once instead of repeating it every five seconds while all anchors are disabled.

## v2.2.40
- Cloud folder synchronization now lists the remote first and skips creation when the anchor folder already exists.
- Startup recovery no longer creates cloud folders for every historical session.
- Canceled and discarded parts are excluded from cloud backup recovery queues.

## v2.2.39
- Unsaved target and global-setting changes are now protected from the three-second service refresh, so toggles such as `录制并烧录` no longer flicker back to the saved value.
- Saving the anchor settings clears the dirty state and applies the server-returned configuration.

## v2.2.38
- Cloud anchor folders are now created whenever an anchor has a cloud remote configured, even when independent upload backup is disabled.
- The recorder checks and creates the anchor folder again immediately before starting a live recording, so folder creation no longer depends on clicking save with the backup switch enabled.
- The app now starts the installed OpenList helper automatically when the control deck opens and stops it on exit only if the app started it.

## v2.2.37
- Aligned the default Quark and Baidu remote paths with the existing OpenList `/dav` root layout: `quark:/quark/DouyinBiliRecorder` and `baidu:/baidu/DouyinBiliRecorder`.
- Existing enabled anchors will create their named folder under the same cloud root without duplicating or dropping the OpenList mount name.

## v2.2.36
- Fixed the per-anchor `单独暂停` button: its handler was nested inside another function, so the button could render but throw a `ReferenceError` when clicked.
- Fixed stale `运行中` status after a recorder child exited. The controller now keeps the `Popen` handle, calls `poll()` to reap the child, and clears the stale runtime PID.
- Clarified the two supported rclone layouts: a `/dav` root remote with a provider mount in the path (for example `openlist:/quark/DouyinBiliRecorder`), or a provider-specific remote with no repeated mount name.
- Saving an anchor with cloud backup enabled now creates `网盘根目录/主播名/` immediately, instead of waiting for the first video upload.
- Segmented controls now use standard click listeners; this fixes switches such as `独立备份`, `录制并烧录`, and visibility not changing in the packaged WebView.
- Revalidated the global pause dialog actions, per-anchor controls, upload pause/retry/stop controls, clear-cache confirmation, cloud remote test, and a real Quark upload.

## v2.2.35
- Added a global `停止并删除当前录像` option to the pause/stop confirmation dialog.
- Added a per-anchor `单独暂停` button. Pausing one anchor no longer requires disabling all recorder workers.
- The global discard action cancels pending Bilibili and cloud uploads, removes the current segment files, and records the session as canceled.

## v2.2.34
- Added per-anchor cloud backup through rclone, with independent upload workers so a Bilibili rate limit cannot block the backup.
- Baidu Netdisk and Quark are supported through OpenList WebDAV remotes; direct Baidu API and Quark API limitations are documented in `docs/CLOUD_UPLOAD.md`.
- Cloud backups are archived as `anchor/date/Pxx`, including retained source media and danmaku XML.
- When cloud backup is enabled, local deletion now requires both a verified BVID and a successful cloud upload. Cache cleanup and storage eviction also preserve pending cloud files.
- Added an rclone remote test action and cloud status on each anchor card.

## v2.2.33
- Each anchor now has an editable Bilibili collection ID. New submissions and appended parts pass this ID directly to Bilibili so every daily multi-P submission for that anchor lands in the same collection.
- Collection binding no longer relies only on creating a new collection after upload. Existing collection IDs are reused and persisted per anchor.

## v2.2.32
- Added a per-anchor start button. It enables that anchor, starts the service when needed, and bypasses the schedule for the immediate check.
- Replaced the dark green theme with a light slate and teal interface.
- Service polling now updates target status text in place instead of rebuilding the entire target list every three seconds, removing the visible refresh flicker.

## v2.2.31
- Automatic upload retries are capped at two after the original attempt, preventing runaway Bilibili `21566` rate-limit pressure. Manual retry starts a fresh two-retry cycle.

## v2.2.30
- Failed upload attempts now retry with a versioned title suffix such as `｜重试01`, replacing the previous retry suffix instead of stacking it.
- Retry titles are capped to 80 characters to stay within Bilibili title limits.

## v2.2.29
- Clicking retry now automatically starts the recorder worker when the service is stopped, so the queued retry request is consumed instead of appearing to do nothing.

## v2.2.28
- Bilibili `Failed to pre_upload ... request limited` responses are now treated as rate limits and use the five-minute backoff instead of rapid generic retries.

## v2.2.27
- Fixed a pause/retry race where the recovery worker could overwrite a `PAUSED` part with its stale `UPLOADING` state after the child process was canceled.
- Service status now merges persisted part state into upload progress so the UI reliably shows `已暂停`, `已停止`, or completed BVID state even if a progress sampler updates later.

## v2.2.26
- Upload rows now provide separate pause, retry, and stop controls. Pausing cancels only that P, keeps the local file, and waits for an explicit retry.
- Retrying a paused, stopped, or failed part uses a new upload generation so stale cancellation events cannot overwrite the new attempt.
- Each anchor card now has a clear-cache action. It deletes only uploaded, canceled, or discarded parts and never removes files from an active recording session or pending/uploads-in-progress parts.
- Bilibili upload rate-limit detection now also handles response code `601` (`上传视频过快`) in addition to `21566`.


## v2.2.25

- Each active upload row now has a stop button. Stopping a part cancels its current biliup child and prevents future retries for that part.
- Added a global minimum upload duration, defaulting to 60 seconds. Shorter final fragments are deleted and never enter the upload queue.
- Stopping an upload does not affect the live recorder, other parts, or other anchors.

## v2.2.24

- A live recorder session is now marked `RECORDING` as soon as the long-lived recorder process connects to the stream, not only when the first completed segment appears.
- Per-anchor UI status therefore keeps showing `录制中` even when a previous part is in upload failure/rate-limit state.

## v2.2.23

- Bilibili response code `21566` is now recognized as an explicit rate-limit condition instead of a generic upload failure.
- Rate-limited parts wait five minutes between retries, and the target card shows `限流等待` instead of repeatedly failing every 30 seconds.

## v2.2.22

- Startup recovery now dispatches each pending session upload to the upload thread pool in parallel instead of uploading sessions one by one.
- A large or slow orphan part can no longer block recovery of other pending anchors.


## v2.2.21

- Target cards now show recording and upload activity side by side. While a completed part uploads, the primary state remains `录制中 / 上传中` and a separate line shows upload P number, percentage, and ETA.
- The recording state is derived from active `RECORDING` sessions even if the latest upload progress event arrives first.

## v2.2.20

- Reopening the service now scans recent session output directories for completed `P02`/`P03` media that were never written into `session.json`, restores them as pending parts, and resumes upload automatically.
- Orphan recovery prefers MP4 output and keeps the matching FLV/MKV/TS source and XML danmaku path for upload or cleanup.

## v2.2.19

- The per-anchor status switches to `录制中` as soon as the recorder process connects to the live stream, instead of waiting for the first completed segment to appear on disk.

## v2.2.18

- Per-anchor usage now uses the current saved UI target list rather than the base config target list, so orphaned completed files in active anchor folders are counted correctly.
- Verified that reopening the app resumes `RECORDED`, `UPLOADING`, and `UPLOAD_FAILED` sessions; a pending 7JIA P01 upload resumed automatically and completed with a BVID.

## v2.2.17

- Uploaded sessions with `delete_after_upload` enabled now clean their final media, original media, danmaku files, and `.danmaku-runtime` temporary files while retaining `session.json` history.
- Per-anchor usage scanning now includes the complete anchor video directory, so orphaned final files not referenced by a session record are counted.
- This fixes stale hidden FLV files and completed uploads that previously continued to appear as several GB of per-anchor usage.

## v2.2.16

- Added a per-anchor live status indicator with distinct states for checking, offline, scheduled waiting, recording, reconnect monitoring, upload, completion, and errors.
- Added per-anchor managed space usage, including temporary session files and local/final media parts.
- Target cards now refresh their runtime status and usage every service-state poll instead of waiting for a full page reload.

## v2.2.15

- Stopping the service now exits the main recorder loop even when no target recording is active, preventing a paused worker from retaining the recorder lock.
- The desktop control process now stops its recorder worker when the app exits.
- Recorder workers also monitor the parent control process PID. If the UI is force-quit or crashes, the worker terminates active recording, upload, and FFmpeg children instead of remaining detached.
- Added regression coverage for interrupt-driven service shutdown without an active recording.

## v2.2.14

- Removed targets now interrupt a worker that is already waiting for cache space, so deleted anchors cannot keep logging or surviving as old threads.
- Upload success and BVID persistence now happen while holding the per-part filesystem lock. A second worker reloads the latest session state and skips the part if it has already completed.
- Bilibili append uploads now check for an existing exact part title before sending an append request, covering crashes or restarts after the remote submission succeeded but before local state was saved.
- Added regressions for removal during a capacity wait and two workers racing to upload the same P.


## v2.2.13

- Offline targets are now rejected before the cache-budget wait, preventing non-live anchors such as `7JIA九芊岁` from spamming `need space` while offline.
- Deleting an anchor now persists immediately instead of only removing the row from the browser; the dynamic service then stops that target worker.
- Added a cross-process filesystem lock per session part around Bilibili upload, preventing a restarted or manually stopped service from uploading the same P twice.


## v2.2.12

- Schedule windows now control when monitoring starts, not when an active live stream must stop. A recently seen live target continues polling after the scheduled end during the reconnect grace period.
- Danmaku burn-in in origin mode now probes the source video bitrate and preserves that bitrate instead of forcing `CRF 20 + veryfast`.
- x264 now uses the `medium` preset for better detail retention; the CRF fallback moved from 20 to 16, and audio increased from 128k to 256k.


## v2.2.11

- Fixed newly added anchors not being monitored until the whole recording service was restarted.
- The running service now watches the runtime target list and starts a dedicated target worker for every new enabled anchor, while existing recording workers keep running.
- Removed anchors are signalled to stop cleanly, and upload workers now scale independently of the initial target count.


## v2.2.10

- Accepts the full Douyin share copy text and Markdown link syntax, extracting the first URL instead of passing the surrounding Chinese text to HTTP.
- Offline profile shares now resolve to a stable room alias such as `https://live.douyin.com/223yuu`; live rooms still upgrade to the numeric `room.owner.web_rid`.
- Fixed alphanumeric room aliases being incorrectly truncated at the first non-digit character.


## v2.2.9

- Fixed Douyin profile and short-link resolution so it prefers the numeric `room.owner.web_rid` and live status returned by the reflow API instead of treating a user unique ID such as `XiaoXinFps` as a live room.
- This prevents live anchors linked by profile URL from being polled as `stream is offline`.


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



## v2.2.22

- Startup recovery now dispatches each pending session upload to the upload thread pool in parallel instead of uploading sessions one by one.
- A large or slow orphan part can no longer block recovery of other pending anchors.

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
