# Validation

## v2.2.34 cloud backup validation

- Full Python test suite: `83 passed`.
- `node --check src/douyin_bili_recorder/web/app.js` passes.
- Python bytecode compilation passes for `src` and `tests`.
- The control deck was loaded from the source tree with `PYTHONPATH=src`; the page fetched `styles.css?v=2.2.34` and `app.js?v=2.2.34`.
- The rendered UI includes the global rclone executable field, per-anchor cloud backup switch, Baidu/Quark/custom provider selector, remote path input, test button, and cloud status line.
- `POST /api/cloud/test` returns a clear `rclone 不存在：rclone` message when the executable is unavailable, rather than failing silently.
- Unit tests cover rclone remote path construction, independent upload command construction, cloud status persistence, local deletion waiting for cloud completion, cache cleanup preservation, and retry-safe cleanup behavior.
- Live Baidu/Quark upload cannot be exercised on this machine without a configured OpenList/rclone remote and user cloud credentials. The code path is deterministic and covered with a fake runner; the actual provider setup is documented in `docs/CLOUD_UPLOAD.md`.
