# Bilibili title format

Every production submission title starts with the anchor name.

```text
{name}｜{start_date} {start_time} 开播｜{room_title}
```

Example:

```text
imxiaoxin｜2026-09-23 20:14 开播｜【录制验证】抖音直播测试
```

The legacy validation submission `BV1Xhh86HEuP` was edited through the Bilibili app edit API to use this format. The edit was accepted and is awaiting review.

The implementation enforces this through the default `title_template` in both the code and `config.example.toml`. A target-specific template can be supplied, but the project documentation and examples always put `{name}` first.
