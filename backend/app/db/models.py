"""Lược đồ dữ liệu — thay cho Neo4j, lưu luật + hiệu lực + sửa đổi trong Postgres.

Mã node theo kiểu LAWGIC: `blld2019-d35-k2-a`
  d = Điều, k = Khoản, chữ cái cuối = Điểm.
"""

from __future__ import annotations

from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import get_settings
from app.db.base import Base

EMBED_DIM = get_settings().embed_dim


class LegalDocument(Base):
    __tablename__ = "legal_document"

    doc_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    doc_type: Mapped[str | None] = mapped_column(String(32))  # luat|nghi_dinh|thong_tu|...
    number: Mapped[str | None] = mapped_column(String(64))
    issued_date: Mapped[date | None] = mapped_column(Date)
    effective_date: Mapped[date | None] = mapped_column(Date)
    expired_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str | None] = mapped_column(String(32), default="active")
    source_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    nodes: Mapped[list[LegalNode]] = relationship(back_populates="document")


class LegalNode(Base):
    __tablename__ = "legal_node"

    node_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    doc_id: Mapped[str] = mapped_column(ForeignKey("legal_document.doc_id", ondelete="CASCADE"))
    level: Mapped[str] = mapped_column(String(16))  # article|clause|point
    article_no: Mapped[int | None] = mapped_column(Integer)
    clause_no: Mapped[int | None] = mapped_column(Integer)
    point_letter: Mapped[str | None] = mapped_column(String(4))
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("legal_node.node_id", ondelete="CASCADE")
    )
    heading: Mapped[str | None] = mapped_column(Text)  # tiêu đề Điều
    chapter_no: Mapped[int | None] = mapped_column(Integer)  # Chương (số thứ tự)
    chapter_title: Mapped[str | None] = mapped_column(Text)  # tiêu đề Chương
    text: Mapped[str] = mapped_column(Text)
    text_hash: Mapped[str | None] = mapped_column(String(64))
    seq: Mapped[int | None] = mapped_column(Integer)  # thứ tự trong văn bản
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))

    document: Mapped[LegalDocument] = relationship(back_populates="nodes")


class NodeSupersession(Base):
    """Quan hệ SUPERSEDED_BY: node cũ bị node mới thay thế."""

    __tablename__ = "node_supersession"

    old_id: Mapped[str] = mapped_column(
        ForeignKey("legal_node.node_id", ondelete="CASCADE"), primary_key=True
    )
    new_id: Mapped[str] = mapped_column(
        ForeignKey("legal_node.node_id", ondelete="CASCADE"), primary_key=True
    )
    change_type: Mapped[str | None] = mapped_column(String(32))  # amended|replaced|removed|added
    similarity: Mapped[float | None] = mapped_column(Float)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class NodeReference(Base):
    """Quan hệ REFERENCES: node dẫn chiếu tới node khác ("khoản 2 Điều 35")."""

    __tablename__ = "node_reference"

    from_id: Mapped[str] = mapped_column(
        ForeignKey("legal_node.node_id", ondelete="CASCADE"), primary_key=True
    )
    to_id: Mapped[str] = mapped_column(
        ForeignKey("legal_node.node_id", ondelete="CASCADE"), primary_key=True
    )
    ref_text: Mapped[str | None] = mapped_column(Text)  # đoạn trích đã khớp


class DocumentRelation(Base):
    """Quan hệ cấp văn bản: AMENDS / REPLACES / GUIDES."""

    __tablename__ = "document_relation"

    from_doc: Mapped[str] = mapped_column(
        ForeignKey("legal_document.doc_id", ondelete="CASCADE"), primary_key=True
    )
    to_doc: Mapped[str] = mapped_column(
        ForeignKey("legal_document.doc_id", ondelete="CASCADE"), primary_key=True
    )
    rel: Mapped[str] = mapped_column(String(16), primary_key=True)


class Precedent(Base):
    """Án lệ / bản án (tòa án) — nguồn cho nhánh tổng hợp án lệ (M6b)."""

    __tablename__ = "precedent"

    doc_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str | None] = mapped_column(Text)
    court: Mapped[str | None] = mapped_column(Text)
    court_level: Mapped[str | None] = mapped_column(String(64))
    precedent_number: Mapped[str | None] = mapped_column(String(64))
    is_precedent: Mapped[bool | None] = mapped_column()
    category: Mapped[str | None] = mapped_column(String(128))
    issued_date: Mapped[date | None] = mapped_column(Date)
    citations_law: Mapped[str | None] = mapped_column(Text)  # JSON/text các luật được viện dẫn
    source_url: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)  # markdown bản án
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))


class PvChunk(Base):
    """Đoạn câu hỏi phỏng vấn (app/pv/data) đã embedding, cho chế độ ẩn /pv.

    Mỗi câu tách 3 đoạn (câu hỏi + chốt kỹ thuật / ví dụ tư vấn / ví dụ đàm phán),
    xem app/pv/library.embedding_chunks. Tách khỏi legal_node để dữ liệu luật
    không bị lẫn khi tra cứu.
    """

    __tablename__ = "pv_chunk"

    chunk_id: Mapped[str] = mapped_column(String(64), primary_key=True)  # G06-A01#technical
    item_id: Mapped[str] = mapped_column(String(32), index=True)
    group_id: Mapped[str] = mapped_column(String(8))
    section: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM))


class Thread(Base):
    __tablename__ = "thread"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Message(Base):
    __tablename__ = "message"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey("thread.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))  # human|ai|tool
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[str | None] = mapped_column(Text)  # JSON (citations, tool calls)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UploadedFile(Base):
    """Tệp người dùng tải lên (upload-ocr-kg-plan, U4). Mức A: không ra ngoài.

    `doc_id` trỏ tới `legal_document` (`doc_type='upload'`); node và dẫn chiếu của tệp
    do U3 sinh ra. Duyệt ở đây là duyệt luôn văn bản đã nạp.
    """

    __tablename__ = "uploaded_file"

    upload_id: Mapped[str] = mapped_column(String(32), primary_key=True)  # uuid4 hex
    doc_id: Mapped[str | None] = mapped_column(
        ForeignKey("legal_document.doc_id", ondelete="CASCADE")
    )
    filename: Mapped[str] = mapped_column(Text)
    mime: Mapped[str | None] = mapped_column(String(128))
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    pages: Mapped[int | None] = mapped_column(Integer)
    ocr_pages: Mapped[int | None] = mapped_column(Integer)
    chars: Mapped[int | None] = mapped_column(Integer)
    mean_ocr_conf: Mapped[float | None] = mapped_column(Float)
    parse_mode: Mapped[str | None] = mapped_column(String(16))  # articles | sections
    n_nodes: Mapped[int | None] = mapped_column(Integer)
    n_refs: Mapped[int | None] = mapped_column(Integer)
    data_class: Mapped[str] = mapped_column(String(1), default="A")
    # pending_review | approved | rejected | failed
    status: Mapped[str] = mapped_column(String(16), default="pending_review")
    error: Mapped[str | None] = mapped_column(Text)
    preview: Mapped[str | None] = mapped_column(Text)  # 2000 ký tự đầu
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProvisionVersion(Base):
    """Phiên bản của một điều khoản theo thời gian (T1, design §5.1).

    `valid_to` là mốc độc quyền: node còn hiệu lực khi valid_from <= ngày < valid_to.
    `known_from`/`known_to` là khoảng thời gian hệ thống *biết* phiên bản này.
    """

    __tablename__ = "provision_version"
    __table_args__ = (UniqueConstraint("provision_key", "valid_from"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provision_key: Mapped[str] = mapped_column(
        String(96), ForeignKey("legal_node.node_id", ondelete="CASCADE"), index=True
    )
    doc_id: Mapped[str] = mapped_column(String(64), index=True)
    text_hash: Mapped[str | None] = mapped_column(String(64))
    source_url: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    # in_force|partly_in_force|pending_amendment|not_yet_in_force|repealed
    status: Mapped[str] = mapped_column(String(24))
    adopted_on: Mapped[date | None] = mapped_column(Date)
    amended_by: Mapped[str | None] = mapped_column(String(64))  # doc_id văn bản sửa đổi
    known_from: Mapped[date] = mapped_column(Date)
    known_to: Mapped[date | None] = mapped_column(Date)


class TransitionRule(Base):
    """Quy tắc chuyển tiếp — điều khoản chuyển tiếp của văn bản mới (T1)."""

    __tablename__ = "transition_rule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_key: Mapped[str] = mapped_column(String(64))  # văn bản chứa quy tắc
    condition: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(String(16))  # old_law|new_law|mixed
    provision_ref: Mapped[str | None] = mapped_column(String(96))
    note: Mapped[str | None] = mapped_column(Text)


class LegalLink(Base):
    """Cạnh liên kết điều khoản/văn bản kèm hiệu lực — gộp 3 bảng quan hệ cũ (T1)."""

    __tablename__ = "legal_link"
    __table_args__ = (UniqueConstraint("from_key", "to_key", "link_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_key: Mapped[str] = mapped_column(String(96))
    to_key: Mapped[str] = mapped_column(String(96))  # node_id hoặc doc_id
    # guides|amends|replaces|cites|based_on
    link_type: Mapped[str] = mapped_column(String(16))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    # node_reference|node_supersession|document_relation|seed
    source: Mapped[str] = mapped_column(String(32))


class AnswerRecord(Base):
    """Hồ sơ một câu trả lời pháp lý (T7, design §5.3): câu hỏi/câu trả lời đã che PII,
    căn cứ đã trích kèm phiên bản tại `as_of`, khung thời gian, verifier, ảnh chụp kho."""

    __tablename__ = "answer_record"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # uuid4 hex[:12]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    thread_id: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(16))  # request id của metrics
    data_class: Mapped[str] = mapped_column(String(1))
    question: Mapped[str] = mapped_column(Text)  # đã che PII
    answer: Mapped[str] = mapped_column(Text)  # đã che PII
    advice_date: Mapped[date] = mapped_column(Date)
    event_date: Mapped[date | None] = mapped_column(Date)
    as_of: Mapped[date] = mapped_column(Date)
    provisions: Mapped[str] = mapped_column(Text)  # JSON list
    timeframe: Mapped[str] = mapped_column(Text)  # JSON
    verifier: Mapped[str | None] = mapped_column(Text)  # JSON
    corpus_snapshot: Mapped[str] = mapped_column(Text)  # JSON
    prompt_version: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(128))
    category: Mapped[str | None] = mapped_column(String(32))


class ReviewCase(Base):
    """Ca chuyển luật sư xem lại (R1, design §9.1): điểm rủi ro và lý do vào hàng đợi.
    Câu hỏi đã che PII; các cột hành động của luật sư để R2 dùng."""

    __tablename__ = "review_case"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # uuid4 hex[:16]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    answer_id: Mapped[str | None] = mapped_column(
        String(16), ForeignKey("answer_record.id", ondelete="SET NULL")
    )
    question: Mapped[str] = mapped_column(Text)  # đã che PII
    risk_score: Mapped[str] = mapped_column(String(8))
    reasons: Mapped[str] = mapped_column(Text)  # JSON list
    # pending|approved|light_edit|heavy_edit|rejected
    status: Mapped[str] = mapped_column(String(16), default="pending")
    source: Mapped[str] = mapped_column(String(16))  # auto|user
    reviewer_text: Mapped[str | None] = mapped_column(Text)
    diff: Mapped[str | None] = mapped_column(Text)
    error_labels: Mapped[str | None] = mapped_column(Text)  # JSON list
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reply: Mapped[str | None] = mapped_column(Text)
    thread_id: Mapped[str | None] = mapped_column(String(64))
    case_type: Mapped[str | None] = mapped_column(String(32))


class AutonomyLevel(Base):
    """Mức tự chủ theo loại ca (R4, design §9.4): thiếu dòng = mức 0."""

    __tablename__ = "autonomy_level"

    case_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    level: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DutyStatus(Base):
    """Lịch luật sư trực (R7, design §15.5) — một dòng duy nhất id=1."""

    __tablename__ = "duty_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    on_duty: Mapped[bool] = mapped_column(default=True)
    lawyer: Mapped[str] = mapped_column(String(64), default="Luật sư chính")
    backup: Mapped[str] = mapped_column(String(64), default="Luật sư dự phòng")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AppUser(Base):
    """Tài khoản demo (AUTH1): chỉ lưu băm PBKDF2 + muối, không lưu mật khẩu gốc."""

    __tablename__ = "app_user"

    username: Mapped[str] = mapped_column(String(32), primary_key=True)
    role: Mapped[str] = mapped_column(String(16))
    salt: Mapped[str] = mapped_column(String(32))
    pw_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UsageCount(Base):
    """Số câu hỏi đã dùng trong ngày của một khoá (user:<tên> hoặc anon:<mã trình duyệt>)."""

    __tablename__ = "usage_count"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    n: Mapped[int] = mapped_column(Integer, default=0)


class IntelItem(Base):
    """Một văn bản/án lệ mới thấy trên trang nguồn (LI1). URL là khoá tự nhiên: đã có
    thì không tải lại, không phân tích lại. `analysis` là JSON của analyze.Analysis."""

    __tablename__ = "intel_item"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    url: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(Text)
    number: Mapped[str] = mapped_column(String(64), default="")
    kind: Mapped[str] = mapped_column(String(32), default="")
    category: Mapped[str] = mapped_column(String(64), default="")
    listed_date: Mapped[date | None] = mapped_column(Date)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    labor_hint: Mapped[bool] = mapped_column(default=False)
    in_corpus: Mapped[bool] = mapped_column(default=False)  # số hiệu đã có trong legal_document
    # new | analysed | skipped | approved | ignored | blocked
    status: Mapped[str] = mapped_column(String(16), default="new")
    analysis: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(String(32))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IntelRun(Base):
    """Một lượt quét tin mới (LI1). `per_source` = JSON {source: {status, found, new}}."""

    __tablename__ = "intel_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trigger: Mapped[str] = mapped_column(String(16))  # schedule | manual
    per_source: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)


class IntelDoc(Base):
    """Toàn văn công khai đã tải cho một tin (LI2).

    `status` `fetched` = đã tải nhưng chưa vào kho, `ingested` = đã qua
    `upload.service.save_upload` (văn bản nằm chờ luật sư duyệt ở `/upload`), `failed` /
    `blocked` = không lấy được (403/429: không thử lại trong cùng lượt quét).
    """

    __tablename__ = "intel_doc"

    item_id: Mapped[str] = mapped_column(
        ForeignKey("intel_item.id", ondelete="CASCADE"), primary_key=True
    )
    source_url: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    bytes: Mapped[int] = mapped_column(Integer, default=0)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    upload_id: Mapped[str | None] = mapped_column(String(32))
    # fetched | ingested | failed | blocked
    status: Mapped[str] = mapped_column(String(16), default="fetched")
    error: Mapped[str | None] = mapped_column(Text)


class IntelImpact(Base):
    """Ảnh hưởng của một tin mới ra ngoài văn bản (LI2b): điều khoản liên quan, máy tính,
    ca golden, hồ sơ tra cứu đã trích điều đó. Các cột JSON là list; `case_id` là ca luật sư
    đã tạo cho tin này (mỗi tin tối đa một ca)."""

    __tablename__ = "intel_impact"

    item_id: Mapped[str] = mapped_column(
        ForeignKey("intel_item.id", ondelete="CASCADE"), primary_key=True
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    articles: Mapped[str] = mapped_column(Text, default="[]")
    calculators: Mapped[str] = mapped_column(Text, default="[]")
    golden: Mapped[str] = mapped_column(Text, default="[]")
    answers: Mapped[str] = mapped_column(Text, default="[]")
    summary: Mapped[str] = mapped_column(Text, default="")
    case_id: Mapped[str | None] = mapped_column(String(16))


class PrecedentCatalog(Base):
    """Danh mục án lệ công khai của anle.toaan.gov.vn (LI3).

    `doc_key` = `dDocName` — khoá tự nhiên dùng chung cho link số hiệu và link tiêu đề.
    `status`: `dang_ap_dung` | `bi_huy_bo` | `chua_ro`; `upload_id` là tệp toàn văn đã nạp
    vào luồng chờ duyệt (null = chưa lấy được).
    """

    __tablename__ = "precedent_catalog"

    doc_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    number: Mapped[str] = mapped_column(String(32), default="")
    title: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text, default="")
    file_url: Mapped[str] = mapped_column(Text, default="")
    # dang_ap_dung | bi_huy_bo | chua_ro
    status: Mapped[str] = mapped_column(String(16), default="chua_ro")
    status_note: Mapped[str | None] = mapped_column(Text)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_checked: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    upload_id: Mapped[str | None] = mapped_column(String(32))


class UploadJob(Base):
    """Tiến trình chép lời một tệp ghi âm/ghi hình (AU1, design §7B.3).

    Một dòng cho mỗi tệp; `consent` là lời xác nhận của người tải lên rằng người được
    ghi âm đã đồng ý. Xoá tệp thì job xoá theo (khoá ngoại CASCADE).
    """

    __tablename__ = "upload_job"

    upload_id: Mapped[str] = mapped_column(
        ForeignKey("uploaded_file.upload_id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String(16), default="audio")
    # converting | transcribing | masking | extracting | done | failed
    stage: Mapped[str] = mapped_column(String(16), default="converting")
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1
    message: Mapped[str | None] = mapped_column(Text)
    duration_s: Mapped[float | None] = mapped_column(Float)
    consent: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Template(Base):
    """Biểu mẫu người dùng tải lên (TPL1): tệp để tái sử dụng, KHÔNG phải văn bản luật.

    Không bao giờ vào `legal_node`, `search_nodes` hay knowledge graph; `legal_basis` là
    danh sách node_id (JSON) người tải khai, đã kiểm tra tồn tại trước khi lưu.
    """

    __tablename__ = "template"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # uuid4 hex[:16]
    name: Mapped[str] = mapped_column(Text)
    # hop_dong | quyet_dinh | don | bien_ban | thong_bao | quy_che | khac
    kind: Mapped[str] = mapped_column(String(24))
    description: Mapped[str | None] = mapped_column(Text)
    legal_basis: Mapped[str] = mapped_column(Text, default="[]")  # JSON list node_id
    filename: Mapped[str] = mapped_column(Text)
    mime: Mapped[str | None] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    text_preview: Mapped[str] = mapped_column(Text, default="")  # 1500 ký tự đầu
    placeholders: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | archived
    created_by: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
