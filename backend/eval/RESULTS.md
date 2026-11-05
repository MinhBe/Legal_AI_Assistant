# Kết quả đo trên gold set (eval/gold_v1.jsonl)

Mỗi dòng do `scripts/eval_gold.py` tự nối thêm. Chi tiết từng lượt chạy nằm trong `eval/results/<file>.json`, trỏ tới bằng cột `ngày` + `tag`. Chỉ các lượt dùng gold set đã được Minh duyệt (`reviewed: true` toàn bộ) mới được coi là số chính thức trong `docs/ket-qua-do-luong.md`; lượt nào chạy trước khi duyệt phải ghi rõ "chưa duyệt" khi nhắc tới.

| ngày | tag | mode | search | rerank | prompt | hit@1 | hit@8 | MRR | đúng | từ chối đúng | p95 | commit |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 20261104-1939 | v1-base-retrieval | retrieval | vector | False | v1 | 0.72 | 0.98 | 0.825 | — | — | 494.5 | 4b965a0 |
| 20261104-1940 | v1-base-e2e | e2e | — | — | v1 | — | — | — | 0.94 | 1.0 | — | 4b965a0 |
| 20261104-2034 | v5-base | inject | ASR=0.000 | P1..P5={'P1': 0.0, 'P2': 0.0, 'P3': 0.0, 'P4': 0.0, 'P5': 0.0} | án lệ P1=0.0 | control=0 |
| 20261104-2040 | v5-d3 | inject | ASR=0.000 | P1..P5={'P1': 0.0, 'P2': 0.0, 'P3': 0.0, 'P4': 0.0, 'P5': 0.0} | án lệ P1=0.0 | control=0 |
| 20261104-2043 | v5-d1d2 | inject | ASR=0.000 | P1..P5={'P1': 0.0, 'P2': 0.0, 'P3': 0.0, 'P4': 0.0, 'P5': 0.0} | án lệ P1=0.0 | control=0 |
| 20261104-2046 | v2-vector | retrieval | vector | False | v1 | 0.72 | 0.98 | 0.825 | — | — | 418.8 | 4b965a0 |
| 20261104-2047 | v2-bm25-syl | retrieval | bm25 | False | v1 | 0.6 | 0.88 | 0.693 | — | — | 25.7 | 4b965a0 |
| 20261104-2047 | v2-bm25-ut | retrieval | bm25 | False | v1 | 0.56 | 0.88 | 0.659 | — | — | 17.4 | 4b965a0 |
| 20261104-2047 | v2-hybrid | retrieval | hybrid | False | v1 | 0.62 | 0.96 | 0.745 | — | — | 443.1 | 4b965a0 |
| 20261104-2048 | v2-vector-rr | retrieval | vector | True | v1 | 0.82 | 1.0 | 0.896 | — | — | 21873.4 | 4b965a0 |
| 20261104-2055 | v2-hybrid-rr | retrieval | hybrid | True | v1 | 0.82 | 1.0 | 0.895 | — | — | 16714.9 | 4b965a0 |
| 20261104-2140 | v2-hybrid-tuned-k8 | retrieval | hybrid | False | v1 | 0.72 | 0.98 | 0.814 | — | — | 439.0 | 4b965a0 |
| 20261104-2144 | v3-metrics | e2e | — | — | v1 | — | — | — | 0.88 | 0.8 | — | 2efd667 |
| 20261104-2215 | v3-hedge5 | e2e | — | — | v1 | — | — | — | 0.88 | None | — | 2efd667 |
| 20261104-2222 | v3-hedge10 | e2e | — | — | v1 | — | — | — | 0.88 | None | — | 2efd667 |
| 20261104-2234 | v3-hedge15 | e2e | — | — | v1 | — | — | — | 0.84 | None | — | 2efd667 |
| 20261105-0040 | v4-v1 | e2e | — | — | v1 | — | — | — | 0.88 | 0.6 | — | 2efd667 |
| 20261105-0127 | v4-v2 | e2e | — | — | v2 | — | — | — | 0.88 | 0.6 | — | 2efd667 |
| 20261105-0236 | v5-all | inject | ASR=0.000 | P1..P5={'P1': 0.0, 'P2': 0.0, 'P3': 0.0, 'P4': 0.0, 'P5': 0.0} | án lệ P1=0.0 | control=0 |
