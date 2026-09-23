# Douyin live recorder

Initial proof of concept for recording a Douyin live stream and uploading the result to Bilibili with the detected live start time written into the submission title.

## PoC

The first-stage script is located at `poc/run_local_poc.sh`.

```bash
./poc/run_local_poc.sh "https://live.douyin.com/694562812381" 45
```

It performs the following steps:

1. records the selected quality for the requested duration;
2. writes a `session.json` containing the detected start timestamp;
3. probes the TS file with `ffprobe`;
4. remuxes TS to MP4 without re-encoding.

See `docs/VALIDATION.md` for the completed local validation results.
