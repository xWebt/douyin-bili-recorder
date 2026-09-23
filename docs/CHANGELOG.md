# Changelog

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
