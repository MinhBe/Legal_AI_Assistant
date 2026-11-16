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
