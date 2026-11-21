"""Số liệu pháp lý dùng khi rà soát. Mỗi mục có căn cứ; đổi luật thì sửa ở đây.

node_id theo quy ước kho: <doc_id>-d<điều>-k<khoản>.
"""

from __future__ import annotations

from datetime import date

BLLD = "blld2019"
BLLD_NAME = "BLLĐ 2019"

# Lương tối thiểu tháng theo vùng (đồng). Mốc valid_from tăng dần.
MIN_WAGE = [
    {
        "valid_from": date(2024, 7, 1),
        "doc_id": "nd74_2024",
        "label": "Nghị định 74/2024/NĐ-CP Điều 3",
        "by_region": {"I": 4_960_000, "II": 4_410_000, "III": 3_860_000, "IV": 3_450_000},
    },
    {
        "valid_from": date(2026, 1, 1),
        "doc_id": "nd293_2025",
        "label": "Nghị định 293/2025/NĐ-CP Điều 3",
        "by_region": {"I": 5_310_000, "II": 4_730_000, "III": 4_140_000, "IV": 3_700_000},
    },
]

# Nội dung chủ yếu của HĐLĐ (Điều 21 khoản 1). Mỗi mục: nhãn, từ khoá (thường, có dấu).
REQUIRED = [
    ("a", "Tên, địa chỉ người sử dụng lao động và người giao kết",
     ["người sử dụng lao động", "bên a", "công ty", "địa chỉ"]),
    ("b", "Họ tên, ngày sinh, giới tính, nơi cư trú, giấy tờ của người lao động",
     ["người lao động", "bên b", "ngày sinh", "cccd", "căn cước", "cmnd"]),
    ("c", "Công việc và địa điểm làm việc", ["công việc", "địa điểm làm việc", "vị trí", "chức danh"]),
    ("d", "Thời hạn của hợp đồng", ["thời hạn", "không xác định thời hạn", "xác định thời hạn"]),
    ("đ", "Mức lương, hình thức và kỳ hạn trả lương, phụ cấp",
     ["mức lương", "tiền lương", "lương cơ bản", "hình thức trả lương", "kỳ hạn trả lương", "trả lương"]),
    ("e", "Chế độ nâng bậc, nâng lương", ["nâng bậc", "nâng lương", "xét tăng lương"]),
    ("g", "Thời giờ làm việc, thời giờ nghỉ ngơi", ["thời giờ làm việc", "giờ làm việc", "nghỉ ngơi", "nghỉ hằng năm", "nghỉ phép"]),
    ("h", "Trang bị bảo hộ lao động", ["bảo hộ lao động", "trang bị bảo hộ", "an toàn lao động"]),
    ("i", "Bảo hiểm xã hội, y tế, thất nghiệp", ["bảo hiểm xã hội", "bhxh", "bảo hiểm y tế", "bảo hiểm thất nghiệp"]),
    ("k", "Đào tạo, bồi dưỡng, nâng cao kỹ năng nghề", ["đào tạo", "bồi dưỡng", "nâng cao trình độ", "kỹ năng nghề"]),
]

# Thử việc tối đa (Điều 25) theo nhóm công việc.
PROBATION_MAX = [
    ("manager", 180, "công việc của người quản lý doanh nghiệp", ["quản lý doanh nghiệp", "giám đốc", "tổng giám đốc"]),
    ("college", 60, "chức danh cần trình độ cao đẳng trở lên", ["cao đẳng", "đại học", "kỹ sư", "cử nhân"]),
    ("vocational", 30, "chức danh cần trình độ trung cấp, công nhân kỹ thuật, nhân viên nghiệp vụ",
     ["trung cấp", "công nhân kỹ thuật", "nhân viên nghiệp vụ"]),
    ("other", 6, "công việc khác", []),
]

MAX_FIXED_TERM_MONTHS = 36          # Điều 20 k1 b
PROBATION_MIN_PAY_PCT = 85          # Điều 26
MAX_HOURS_DAY = 8                   # Điều 105 k1
MAX_HOURS_WEEK = 48                 # Điều 105 k1
MAX_OT_MONTH = 40                   # Điều 107 k2 b
MIN_ANNUAL_LEAVE = 12               # Điều 113 k1 a
EMPLOYEE_NOTICE_MAX = {"indefinite": 45, "fixed_12_36": 30, "fixed_lt12": 3}  # Điều 35 k1
