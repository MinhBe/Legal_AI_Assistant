"""Ghi sẵn câu trả lời cho trang /demo (bản dự phòng khi đám mây chậm quá 8 s).

    NO_LOCAL_FOR_C=true python -m scripts.demo_record

Chạy đúng pipeline chat thật (run_chat, mức C, đám mây trước) cho 3 tình huống mẫu; mọi sự kiện
SSE (step, token, citation, timeframe, verifier, done…) ghi ra data/demo/out/<id>.json để
trang demo phát lại. Câu hỏi mẫu không có dữ liệu cá nhân.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.agent.pipeline import run_chat

# container chỉ gắn backend/ và data/: đọc bản sao cases.json trong data/demo, ghi ra data/demo/out;
# máy chủ chép sang frontend/public/demo (tools: cp data/demo/out/*.json frontend/public/demo/)
OUT = Path("data/demo/out")
CASES = json.loads(Path("data/demo/cases.json").read_text(encoding="utf-8"))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for case in CASES:
        events = []
        for event, data in run_chat(case["question"], [], "law", cloud_first=True):
            if event == "record":  # mã bản ghi của lượt chat thật, không dùng cho bản phát lại
                continue
            events.append({"event": event, "data": data})
        text = "".join(e["data"].get("text", "") for e in events if e["event"] == "token")
        (OUT / f"{case['id']}.json").write_text(json.dumps(
            {"id": case["id"], "question": case["question"], "events": events},
            ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        cites = sum(e["event"] == "citation" for e in events)
        print(case["id"], len(text), "ký tự,", cites, "trích dẫn", flush=True)


if __name__ == "__main__":
    main()
