# Validation

## v2.2.40 control and cloud validation

- Full Python test suite: `94 passed`.
- `node --check src/douyin_bili_recorder/web/app.js` passes.
- Python bytecode compilation passes for `src` and `tests`.
- The control deck was loaded from the source tree with `PYTHONPATH=src`; the page fetched `styles.css?v=2.2.40` and `app.js?v=2.2.40`.
- The zip was extracted and the resulting `v2.2.38` app passed strict code-sign verification; the packaged runtime served the same `v2.2.38` assets and created the configured cloud anchor directory through the real Quark remote.
- The global pause dialog was exercised in the browser:
  - `继续录制` closed the dialog without stopping the worker.
  - `暂停并上传` stopped the isolated worker and returned the UI to `已停止`.
  - `暂停并保留本地` wrote `keep` to the stop request and stopped the worker.
  - `停止并删除当前录像` wrote `discard`, stopped the worker, and cleared the runtime PID.
- The per-anchor `单独开始` and `单独暂停` buttons were clicked in the browser; the paused anchor changed to `enabled = false` and the UI showed `已暂停`.
- The upload controls were exercised against isolated temporary sessions:
  - `暂停` changed the part and progress state to paused.
  - `重试` queued the part and started the service.
  - `停止` canceled the part and the UI showed `已停止`.
- The per-anchor `清除缓存` confirmation was accepted in the browser and deleted an isolated uploaded file.
- The per-anchor `测试网盘` button returned `远端可访问` with the final OpenList `/dav` root layout and `quark:/quark/DouyinBiliRecorder` path.
- The `独立备份` segmented control was clicked from `不备份` to `独立备份`; the active state changed reliably after switching the control to `addEventListener`.
- Saving an anchor with a configured cloud remote created the anchor directory immediately in Quark, regardless of the `独立备份` switch. The test folder was verified with rclone and then purged.
- A real application-level Quark upload succeeded through `RcloneCloudUploader`:
  - remote path: `quark:/quark/DouyinBiliRecorder/__codex_validation__/<id>/Codex验证/2026-09-30/P01/cloud-validation.bin`
  - the uploaded validation path was verified with rclone and then purged.
- The controller now keeps the recorder `Popen` handle and calls `poll()`, so an exited child no longer leaves the UI stuck at `运行中` because of a zombie PID.
- All five configured local anchors were used to create their missing Quark folders without enabling `独立备份`; the folders were verified under `quark:/quark/DouyinBiliRecorder/`.
- The control deck starts the installed OpenList helper on app startup and the helper serves the Quark WebDAV endpoint automatically.
- The `录制并烧录` toggle was clicked, then observed after 4.2 seconds and one automatic service refresh; it remained `on` until saved.
- Existing cloud anchor directories are detected with `rclone lsf --dirs-only` and are not recreated.
