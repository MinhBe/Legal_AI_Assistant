# Kết quả đo trên gold set (eval/gold_v1.jsonl)

Mỗi dòng do `scripts/eval_gold.py` tự nối thêm. Chi tiết từng lượt chạy nằm trong `eval/results/<file>.json`, trỏ tới bằng cột `ngày` + `tag`. Chỉ các lượt dùng gold set đã được Minh duyệt (`reviewed: true` toàn bộ) mới được coi là số chính thức trong `docs/ket-qua-do-luong.md`; lượt nào chạy trước khi duyệt phải ghi rõ "chưa duyệt" khi nhắc tới.

| ngày | tag | mode | search | rerank | prompt | hit@1 | hit@8 | MRR | đúng | từ chối đúng | p95 | commit |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
