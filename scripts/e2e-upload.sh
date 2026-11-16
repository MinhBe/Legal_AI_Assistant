#!/usr/bin/env bash
# Kiểm thử đầu-cuối tính năng tải tài liệu lên -> OCR -> knowledge graph (không gọi LLM).
# Dùng: bash scripts/e2e-upload.sh [API]   (mặc định http://localhost:8000)
# Tải 4 file mẫu, kiểm số liệu, kiểm graph, kiểm tài liệu chưa duyệt không lọt vào tìm kiếm,
# duyệt, rồi xoá sạch. Thoát mã 1 nếu có bước sai.
set -uo pipefail
export PYTHONIOENCODING=utf-8
API="${1:-http://localhost:8000}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/data/samples/upload"
PY="$(command -v python3 || command -v python)"
fail=0; ids=()
ok()  { printf '  OK   %s\n' "$1"; }
bad() { printf '  SAI  %s\n' "$1"; fail=1; }
j()   { "$PY" -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

echo "== API: $API"
curl -sf "$API/health" >/dev/null && ok "API sống" || { bad "API không trả lời /health"; exit 1; }

for f in noi-quy-lao-dong.pdf hop-dong-lao-dong-mau.docx quyet-dinh-ky-luat-scan.jpg quyet-dinh-ky-luat-scan.pdf; do
  echo "== Tải lên $f"
  r=$(curl -s -F "file=@$DIR/$f" "$API/api/uploads")
  id=$(echo "$r" | j "d.get('upload_id','')")
  [ -n "$id" ] || { bad "không có upload_id: ${r:0:200}"; continue; }
  ids+=("$id")
  # xử lý chạy ở nền: chờ tới khi row rời trạng thái "processing"
  for _ in $(seq 1 90); do
    [ "$(echo "$r" | j "d.get('status')")" = "processing" ] || break
    sleep 2
    r=$(curl -s "$API/api/uploads/$id")
  done
  doc=$(echo "$r" | j "d.get('doc_id') or ''")
  echo "$r" | j "f\"  trang={d['pages']} ocr={d['ocr_pages']} conf={d['mean_ocr_conf']} kiểu={d['parse_mode']} node={d['n_nodes']} dẫn_chiếu={d['n_refs']} mức={d['data_class']} trạng_thái={d['status']}\""
  [ "$(echo "$r" | j "d['status']")" = "pending_review" ] && ok "chờ duyệt, mức $(echo "$r" | j "d['data_class']")" || bad "trạng thái không phải pending_review"
  [ "$(echo "$r" | j "int((d['n_refs'] or 0) >= 1)")" = "1" ] && ok "có dẫn chiếu tới điều luật" || bad "không có dẫn chiếu"
  case "$f" in *scan*) [ "$(echo "$r" | j "int((d['ocr_pages'] or 0) >= 1)")" = "1" ] && ok "đã OCR" || bad "bản scan mà không OCR";; esac
  g=$(curl -s "$API/api/graph?doc_id=$doc&uploads=1&top_k=150")
  [ "$(echo "$g" | j "int(any(e['type']=='references' for e in d['edges']))")" = "1" ] && ok "graph có cạnh dẫn chiếu" || bad "graph thiếu cạnh dẫn chiếu"
  [ "$(echo "$g" | j "int(any(n['id'].startswith('blld2019') for n in d['nodes']))")" = "1" ] && ok "graph nối sang BLLĐ 2019" || bad "graph không có node BLLĐ 2019"
done

echo "== Tải lại cùng file: phải trả bản cũ"
r=$(curl -s -F "file=@$DIR/noi-quy-lao-dong.pdf" "$API/api/uploads")
[ "$(echo "$r" | j "int(d.get('duplicate') is True)")" = "1" ] && ok "nhận ra file trùng" || bad "không nhận ra file trùng"

echo "== Định dạng lạ phải bị từ chối"
code=$(printf 'MZ\x90\x00' | curl -s -o /dev/null -w "%{http_code}" -F "file=@-;filename=x.exe" "$API/api/uploads")
[ "$code" = "415" ] && ok "x.exe -> 415" || bad "x.exe -> $code (mong 415)"

echo "== Tài liệu chưa duyệt không lọt vào tìm kiếm của chat"
s=$(curl -s -X POST "$API/api/search" -H 'Content-Type: application/json' -d '{"query": "Công ty TNHH Mẫu An Bình nội quy kỷ luật", "top_k": 20}')
[ "$(echo "$s" | j "int(not any(str(h.get('doc_id','')).startswith('up_') for h in (d if isinstance(d, list) else d.get('results', d.get('hits', [])))))")" = "1" ] \
  && ok "search không trả node tải lên" || bad "search trả về node tải lên chưa duyệt"

echo "== Duyệt rồi xoá"
first="${ids[0]:-}"
if [ -n "$first" ]; then
  st=$(curl -s -X PATCH "$API/api/uploads/$first" -H 'Content-Type: application/json' -d '{"status":"approved"}' | j "d['status']")
  [ "$st" = "approved" ] && ok "duyệt được" || bad "duyệt lỗi: $st"
fi
if [ "${KEEP:-0}" != "1" ]; then
  for id in "${ids[@]}"; do curl -s -o /dev/null -X DELETE "$API/api/uploads/$id"; done
  left=$(curl -s "$API/api/uploads" | j "sum(1 for r in d if r['upload_id'] in '${ids[*]}'.split())")
  [ "$left" = "0" ] && ok "đã xoá sạch ${#ids[@]} file" || bad "còn $left file chưa xoá"
else
  echo "  (KEEP=1: giữ lại file để xem trên giao diện)"
fi

[ $fail -eq 0 ] && echo "== KẾT QUẢ: ĐẠT" || echo "== KẾT QUẢ: CÓ BƯỚC SAI"
exit $fail
