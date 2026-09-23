# Changelog

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
