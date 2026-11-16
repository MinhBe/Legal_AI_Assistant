"""Ngôn ngữ của câu hỏi và chỉ dẫn trả lời (contract ML1).

Câu hỏi có thể viết bằng tiếng Anh/Nhật/Trung; câu trả lời viết bằng đúng ngôn ngữ
đó, còn số điều/khoản và tên văn bản luật giữ nguyên tiếng Việt.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from loguru import logger

from app.agent.guard import vi_diacritic_ratio

_KANA = re.compile(r"[\u3040-\u30ff]")  # hiragana + katakana
_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_ASCII = re.compile(r"[A-Za-z]")

NAMES = {"vi": "tiếng Việt", "en": "tiếng Anh", "ja": "tiếng Nhật", "zh": "tiếng Trung"}


def detect(text: str) -> str:
    """Đoán ngôn ngữ câu hỏi bằng quy tắc, không cần gói nào: "vi" | "en" | "ja" | "zh"."""
    if _KANA.search(text):
        return "ja"
    letters = [c for c in text if c.isalpha()]
    if letters and len(_HAN.findall(text)) / len(letters) >= 0.2:
        return "zh"
    if vi_diacritic_ratio(text) >= 0.03:
        return "vi"
    if letters and len(_ASCII.findall(text)) / len(letters) >= 0.6:
        return "en"
    return "vi"



def is_unaccented(text: str) -> bool:
    """Câu tiếng Việt gõ không dấu (hoặc tiếng Anh): toàn chữ ASCII và từ 3 từ trở lên."""
    # bỏ placeholder PII của gateway ([SĐT_1], [TÊN_2]…): chúng có chữ "Đ/Ê" nhưng không phải lời người dùng
    text = re.sub(r"\[[^\[\]]+_\d+\]", " ", text)
    if len(_WORDS.findall(text)) < 3:
        return False
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and all(c.isascii() for c in letters)


# ~330 âm tiết tiếng Việt không dấu thường gặp trong câu hỏi luật lao động.
VI_SYLLABLES = frozenset(
    """
    toi ban la cua va cho khong co duoc nguoi lao dong hop luong viec ngay thang nam
    bao nhieu thoi gian thu nghi phep cong ty sa thai cham dut tro cap hiem xa hoi
    ky luat quyen nghia vu anh chi em ong ba ho ten tuoi gioi tinh que quan dia chi
    gio phut tuan buoi sang chieu dem som muon truoc sau trong ngoai dai ngan han
    dinh muc do thuong phat boi thuong thiet hai tai nan benh nghe nghiep bao hiem
    y te hop dong xac lap thuc hien don phuong hai ben mot phia chu su dung dai dien
    quan ly thu lao tien phu lam them ca nghi giua hang le viec rieng luong om dau
    thai san nuoi con nho gia suc khoe kham vien chua duong giam sat an toan ve sinh
    nguy hiem phong chong chay no ho trang bi phuong tien thiet may moc van hanh
    ky thuat tieu chuan quy chat luong moi truong dieu kien nang nhoc doc tham gia
    bat buoc tu nguyen dong huong che do huu tri phi quy that nha nuoc su nghiep
    don vi hoc nghe tap dao tao boi duong nang cao trinh tay chuyen mon nghiep vu
    kinh nghiem tuyen phong van nhan so ung vien tri chuc danh mo ta yeu cau trach
    nhiem thoi han gia chuyen tiep khong xac dinh thoa thuan tap the doi thoai
    tai noi hoi nguoi dai hoi doan to chuc dien tranh chap ca nhan hoa giai trong
    toa xu ly yeu kien khoi nghi loi ich hai hoa thien chi luat su giup phap ly tu
    van chinh sach xa chu viet bo nghe thong tu quyet dinh huong dan thi ap hieu luc
    sua bo sung thay bai quy dinh dieu khoan diem muc chuong phan noi dung pham vi
    doi tuong nguyen tac dam bao quan he phat trien on binh dang khong biet xu yeu
    the nu chua thanh nien cao khuyet tat giai dinh cu tru hoat kinh doanh cuoc
    song an o di lai sinh de nuoi con nuoi gia dinh nguoi giup viec
    """.split()
)

_WORDS = re.compile(r"[^\W\d_]+", re.UNICODE)


def vi_ratio(text: str) -> float:
    """Tỉ lệ từ (chữ thường) có trong VI_SYLLABLES — bằng chứng câu này là tiếng Việt không dấu."""
    words = _WORDS.findall(text.lower())
    if not words:
        return 0.0
    return sum(1 for w in words if w in VI_SYLLABLES) / len(words)


DIACRITIC_PROMPT = (
    "Thêm dấu tiếng Việt cho câu hỏi về luật lao động sau. Không đổi, thêm hay bớt từ; không trả "
    "lời câu hỏi; giữ nguyên các ký hiệu trong ngoặc vuông như [SĐT_1]; chỉ trả về câu đã thêm dấu.\n"
    "Ví dụ: thu viec → thử việc; sa thai → sa thải; tro cap thoi viec → trợ cấp thôi việc; "
    "hop dong lao dong → hợp đồng lao động; nghi phep nam → nghỉ phép năm; tien luong → tiền lương; "
    "bao hiem xa hoi → bảo hiểm xã hội; lam them gio → làm thêm giờ; bao truoc → báo trước; "
    "cao dang → cao đẳng; nguoi su dung lao dong → người sử dụng lao động; ky luat → kỷ luật."
)


def restore_diacritics(router: Any, text: str) -> str | None:
    """Một lượt LLM thêm dấu; trả None khi kết quả rỗng, thiếu dấu hoặc lệch số từ > 20 %."""
    try:
        out = router.chat(
            [{"role": "user", "content": f"{DIACRITIC_PROMPT}\n\n{text}"}], task="route"
        ).text.strip()
    except Exception:  # noqa: BLE001 — không thêm dấu được thì giữ nguyên câu gốc
        logger.warning("Thêm dấu tiếng Việt thất bại", exc_info=True)
        return None
    if not out or vi_diacritic_ratio(out) < 0.03:
        return None
    n_in = len(text.split())
    if n_in and abs(len(out.split()) - n_in) / n_in > 0.2:
        return None
    return out


def _reading_score(hits: list[dict]) -> float:
    if not hits:
        return 0.0
    scores = [h.get("score") for h in hits]
    if all(isinstance(s, (int, float)) for s in scores):
        top = sorted(scores, reverse=True)[:3]
        return sum(top) / len(top)
    return float(len(hits))


def choose_reading(router: Any, search: Callable[..., list[dict]], text: str) -> dict:
    """Chọn cách đọc câu không dấu: tiếng Việt (thêm dấu) hay tiếng Anh, theo điểm truy hồi."""
    ratio = vi_ratio(text)
    vi_text = restore_diacritics(router, text) or text
    vi_score = _reading_score(search(vi_text, top_k=5) or []) + (0.15 if ratio >= 0.5 else 0.0)
    en_score = _reading_score(search(text, top_k=5) or []) + (0.15 if ratio < 0.2 else 0.0)
    scores = {"vi": vi_score, "en": en_score}
    if abs(vi_score - en_score) < 0.02 and 0.2 <= ratio < 0.5:
        lang = "tie"
    elif vi_score > en_score:
        lang = "vi"
    else:
        lang = "en"
    return {
        "lang": lang,
        "text": vi_text if lang == "vi" else text,
        "vi_text": vi_text,
        "scores": scores,
        "vi_ratio": ratio,
    }


def answer_instruction(lang: str) -> str:
    """Một dòng thêm vào prompt trả lời; rỗng khi câu hỏi bằng tiếng Việt."""
    if lang == "vi":
        return ""
    name = NAMES.get(lang, NAMES["vi"])
    return (
        f"Viết `summary` và `detail` của mọi mục bằng {name}. Giữ nguyên số điều/khoản và tên "
        "văn bản tiếng Việt (ví dụ «Điều 25 Bộ luật Lao động 2019») rồi dịch ngắn trong ngoặc."
    )
