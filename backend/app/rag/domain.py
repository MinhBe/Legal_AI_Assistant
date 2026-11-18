"""Lĩnh vực của câu hỏi -> văn bản nào được truy hồi (mở rộng kho, 18/11/2026).

Kho gốc là lao động. Văn bản lĩnh vực khác (đất đai, hình sự, hôn nhân gia đình, thuế TNCN,
dân sự, xử phạt hành chính) nằm trong `doc_meta`, chỉ được truy hồi khi ĐÃ DUYỆT và câu hỏi
thuộc lĩnh vực đó. Câu hỏi lao động chỉ truy hồi kho lao động, nên bộ câu vàng lao động
không bị văn bản mới chen vào.

Phân loại bằng từ khoá (không gọi mô hình): đủ cho định tuyến; sai thì vẫn còn bước
phân loại/Verifier phía sau, và câu không khớp lĩnh vực nào được coi là lao động.
"""

from __future__ import annotations

import re

LABOUR = "lao_dong"
LABELS = {
    "lao_dong": "Lao động",
    "dat_dai": "Đất đai",
    "hinh_su": "Hình sự",
    "xu_phat_hc": "Xử phạt vi phạm hành chính",
    "hon_nhan_gia_dinh": "Hôn nhân và gia đình",
    "thue_tncn": "Thuế thu nhập cá nhân",
    "dan_su": "Dân sự",
}

_KEYWORDS: dict[str, tuple[str, ...]] = {
    "lao_dong": ("người lao động", "người sử dụng lao động", "hợp đồng lao động", "sa thải",
                 "nghỉ việc", "thôi việc", "tiền lương", "lương", "trợ cấp thôi việc",
                 "bảo hiểm xã hội", "thử việc", "kỷ luật lao động", "làm thêm giờ", "công ty",
                 "nghỉ phép", "thai sản", "đình công", "công đoàn", "nội quy lao động"),
    "dat_dai": ("đất", "sổ đỏ", "sổ hồng", "tách thửa", "thửa đất", "quyền sử dụng đất",
                "giấy chứng nhận quyền", "thu hồi đất", "bồi thường đất", "đất ở", "đất nông nghiệp",
                "chuyển mục đích sử dụng"),
    "hinh_su": ("tội", "hình sự", "khởi tố", "truy cứu", "đánh bạc", "đánh đề", "trộm cắp",
                "lừa đảo", "án tích", "tù", "bị can", "bị cáo", "cố ý gây thương tích"),
    "xu_phat_hc": ("xử phạt hành chính", "phạt hành chính", "vi phạm hành chính", "phạt tiền",
                   "an ninh trật tự"),
    "hon_nhan_gia_dinh": ("ly hôn", "kết hôn", "vợ chồng", "tài sản chung", "tài sản riêng",
                          "nuôi con", "cấp dưỡng", "quyền nuôi con", "hôn nhân"),
    "thue_tncn": ("thuế thu nhập cá nhân", "thuế tncn", "hoàn thuế", "quyết toán thuế",
                  "khấu trừ thuế", "giảm trừ gia cảnh", "người phụ thuộc", "etax"),
    "dan_su": ("tặng cho", "thừa kế", "di chúc", "hợp đồng dân sự", "vay tiền", "đặt cọc",
               "bồi thường thiệt hại", "hợp đồng mua bán"),
}
_PATTERNS = {d: re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, kws)) + r")(?!\w)",
                           re.IGNORECASE)
             for d, kws in _KEYWORDS.items()}


def classify(message: str) -> list[str]:
    """Các lĩnh vực của câu hỏi, lĩnh vực chính đứng đầu; không khớp gì = ["lao_dong"].

    Lương và thuế TNCN hay đi cùng nhau: câu có cả hai giữ cả hai lĩnh vực.
    """
    hits = {d: len(p.findall(message or "")) for d, p in _PATTERNS.items()}
    found = [d for d, n in sorted(hits.items(), key=lambda kv: -kv[1]) if n]
    if not found:
        return [LABOUR]
    # "công ty"/"lương" xuất hiện trong mọi câu chuyện: lao động không thắng chỉ nhờ từ chung
    if found[0] == LABOUR and len(found) > 1 and hits[LABOUR] <= hits[found[1]]:
        found[0], found[1] = found[1], found[0]
    return found


def label(domain: str) -> str:
    return LABELS.get(domain, domain)
