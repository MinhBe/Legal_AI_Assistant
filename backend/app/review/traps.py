"""Ca bẫy (R3, design §9.4, §15.6): cứ 20 ca tự động thì chèn một ca đã biết đáp án,
để đo xem luật sư có duyệt qua loa không.

    maybe_insert_trap(db)   # gọi sau mỗi ca tự động mới
    trap_stats(db)          # {"total", "reviewed", "caught", "catch_rate"}

Bản nháp cài lỗi nằm ở `reviewer_text` (ca bẫy không có `answer_record`); đáp án đúng
nằm ở `reply`. Dấu "(ca kiểm tra)" chỉ nằm trong `reasons`, không nằm ở câu hỏi —
hàng đợi trông giống hệt ca tự động.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import ReviewCase

TRAPS: tuple[dict[str, str], ...] = (
    {
        "type": "cham_dut",
        "label": "sai_phien_ban",
        "question": "Tháng 3/2023 công ty cho tôi thôi việc; hợp đồng không xác định thời hạn "
                    "thì phải báo trước bao nhiêu ngày?",
        "draft": "Theo Điều 38 Bộ luật Lao động 2012, người sử dụng lao động phải báo trước "
                 "45 ngày.",
        "note": "[cần đối chiếu] Sự kiện năm 2023 áp dụng BLLĐ 2019 (hiệu lực 1/1/2021): Điều 36 khoản 2 — "
                "báo trước ít nhất 45 ngày với hợp đồng không xác định thời hạn.",
    },
    {
        "type": "cham_dut",
        "label": "sai_tinh_toan",
        "question": "Hợp đồng lao động không xác định thời hạn; công ty muốn chấm dứt thì phải "
                    "báo trước bao nhiêu ngày?",
        "draft": "Cần báo trước 30 ngày làm việc theo Điều 36 BLLĐ 2019.",
        "note": "[cần đối chiếu] Điều 36 khoản 2 BLLĐ 2019: ít nhất 45 ngày với hợp đồng không xác định thời "
                "hạn; 30 ngày chỉ áp dụng cho hợp đồng 12–36 tháng.",
    },
    {
        "type": "cham_dut",
        "label": "sai_trich_dan",
        "question": "Trợ cấp thôi việc được quy định ở điều nào và tính thế nào?",
        "draft": "Điều 48 BLLĐ 2019 quy định trợ cấp thôi việc: mỗi năm làm việc được nửa "
                 "tháng lương.",
        "note": "[cần đối chiếu] Trợ cấp thôi việc là Điều 46 BLLĐ 2019 (Điều 48 là trách nhiệm khi chấm dứt "
                "hợp đồng lao động); mỗi năm làm việc bằng nửa tháng lương.",
    },
    {
        "type": "nghi_ngoi",
        "label": "sai_tinh_toan",
        "question": "Người làm việc đủ 12 tháng trong điều kiện bình thường được nghỉ phép năm "
                    "bao nhiêu ngày?",
        "draft": "Điều 113 BLLĐ 2019: 16 ngày làm việc cho mọi trường hợp.",
        "note": "[cần đối chiếu] Điều 113 BLLĐ 2019: 12 ngày làm việc với điều kiện bình thường; 14 ngày cho "
                "người chưa thành niên hoặc lao động là người khuyết tật; 16 ngày cho nghề "
                "nặng nhọc, độc hại.",
    },
    {
        "type": "tien_luong",
        "label": "sai_tinh_toan",
        "question": "Làm thêm giờ vào ngày thường được trả bao nhiêu phần trăm tiền lương?",
        "draft": "Làm thêm giờ ngày thường được trả 200% tiền lương giờ thực trả.",
        "note": "[cần đối chiếu] Điều 98 khoản 1 BLLĐ 2019: ngày thường ít nhất 150%; 200% là ngày nghỉ hằng "
                "tuần, 300% là ngày lễ, tết.",
    },
)


def _count(db: Session, source: str) -> int:
    return db.scalar(
        select(func.count()).select_from(ReviewCase).where(ReviewCase.source == source)
    ) or 0


def maybe_insert_trap(db: Session) -> str | None:
    """Sau mỗi 20 ca tự động (đếm % 20 == 0) chèn một ca bẫy; trả id ca bẫy hoặc None."""
    if _count(db, "auto") % 20:
        return None
    trap = TRAPS[_count(db, "trap") % len(TRAPS)]
    case_id = uuid.uuid4().hex[:16]
    db.add(ReviewCase(
        id=case_id,
        question=trap["question"],
        risk_score="3",
        reasons=json.dumps(
            [{"code": "trap", "weight": 3,
              "message": f"(ca kiểm tra) Lỗi cài sẵn: {trap['label']}"}],
            ensure_ascii=False,
        ),
        status="pending",
        source="trap",
        case_type=trap["type"],
        reviewer_text=trap["draft"],
        reply=trap["note"],
    ))
    db.commit()
    return case_id


def trap_stats(db: Session) -> dict:
    """Tỷ lệ bắt ca bẫy: bắt = hành động khác `approve` (§15.6)."""
    statuses = list(db.scalars(
        select(ReviewCase.status).where(ReviewCase.source == "trap")
    ))
    reviewed = [s for s in statuses if s != "pending"]
    caught = [s for s in reviewed if s != "approved"]
    return {
        "total": len(statuses),
        "reviewed": len(reviewed),
        "caught": len(caught),
        "catch_rate": round(len(caught) / len(reviewed), 4) if reviewed else None,
    }
