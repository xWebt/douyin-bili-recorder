# Product

The production recorder is implemented under `src/douyin_bili_recorder`.

It watches configured Douyin profile or live-room URLs through biliup, records each session, remuxes media without re-encoding, uploads the first segment to Bilibili, appends later segments as additional parts, and persists state for recovery after failures or restarts.

The standard title starts with the anchor name:

```text
主播名｜YYYY-MM-DD HH:MM 开播｜直播间标题
```

Install and run:

```bash
./scripts/install-tools.sh
.venv/bin/douyin-recorder init-config --output config.toml
.venv/bin/douyin-recorder doctor --config config.toml
.venv/bin/douyin-recorder run --config config.toml
```

`cookies.json` and recorded media are intentionally ignored by Git.
