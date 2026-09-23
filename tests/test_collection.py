from __future__ import annotations

import json
from pathlib import Path

from douyin_bili_recorder.collection import BilibiliCollectionManager


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return FakeResponse(self.responses.pop(0))


def make_manager(tmp_path: Path) -> BilibiliCollectionManager:
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text(
        json.dumps(
            {
                "cookie_info": {
                    "cookies": [
                        {"name": "SESSDATA", "value": "session"},
                        {"name": "bili_jct", "value": "csrf"},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    return BilibiliCollectionManager(cookie_file)


def test_find_collection_uses_new_season_endpoint(tmp_path: Path) -> None:
    manager = make_manager(tmp_path)
    manager.session = FakeSession(
        [
            {
                "code": 0,
                "data": {
                    "seasons": [
                        {
                            "season": {"id": 12, "title": "anchor"},
                            "sections": {"sections": [{"id": 34, "title": "正片"}]},
                        }
                    ]
                },
            }
        ]
    )

    result = manager.find_collection("anchor")

    assert result is not None
    assert result.id == 12
    assert result.section_id == 34
    assert "/x2/creative/web/seasons" in manager.session.calls[0][1]


def test_add_video_submits_aid_and_cid(tmp_path: Path) -> None:
    manager = make_manager(tmp_path)
    manager.session = FakeSession(
        [
            {
                "code": 0,
                "data": {
                    "aid": 123,
                    "pages": [{"cid": 456}],
                    "title": "video",
                },
            },
            {"code": 0, "data": {}},
        ]
    )
    from douyin_bili_recorder.collection import CollectionInfo

    manager.add_video(CollectionInfo(12, "anchor", 34, "正片"), "BV0000000001", "part")

    method, url, kwargs = manager.session.calls[1]
    assert method == "POST"
    assert url.endswith("/season/section/episodes/add")
    assert kwargs["json"]["episodes"][0]["aid"] == 123
    assert kwargs["json"]["episodes"][0]["cid"] == 456
