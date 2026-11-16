"""Phiên bản điều khoản theo thời gian (T1, design §5.1).

Dựng `provision_version` / `legal_link` / `transition_rule` từ dữ liệu đã nạp
(`legal_node`, `node_reference`, `node_supersession`, `document_relation`).
Không suy đoán ngày hiệu lực: chỉ dùng effective_from/effective_to có sẵn.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Engine, delete, insert, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import (
    DocumentRelation,
    LegalDocument,
    LegalLink,
    LegalNode,
    NodeReference,
    NodeSupersession,
    ProvisionVersion,
    TransitionRule,
)

STATUSES = ("in_force", "partly_in_force", "pending_amendment", "not_yet_in_force", "repealed")

TABLES = (ProvisionVersion.__table__, TransitionRule.__table__, LegalLink.__table__)

# Quy tắc chuyển tiếp của BLLĐ 2019 (Điều 220) — [cần đối chiếu] với luật sư.
SEED_DOC = "blld2019"
SEED_CONDITION = "Hợp đồng lao động giao kết trước ngày 01/01/2021"
SEED_NOTE = (
    "Điều 220 BLLĐ 2019: hợp đồng còn thời hạn tiếp tục thực hiện, "
    "trừ nội dung trái luật mới — cần đối chiếu"
)


def status_at(valid_from: date | None, valid_to: date | None, day: date) -> str:
    """Trạng thái hiệu lực tại `day`; `valid_to` là mốc độc quyền."""
    if valid_from and valid_from > day:
        return "not_yet_in_force"
    if valid_to and valid_to <= day:
        return "repealed"
    return "in_force"


def create_tables(engine: Engine) -> None:
    Base.metadata.create_all(bind=engine, tables=list(TABLES))


def drop_tables(engine: Engine) -> None:
    Base.metadata.drop_all(bind=engine, tables=list(TABLES))


def backfill(db: Session, *, today: date | None = None) -> dict[str, int]:
    """Dựng lại ba bảng từ dữ liệu gốc; chạy lại nhiều lần vẫn ra cùng số dòng."""
    day = today or date.today()
    for model in (ProvisionVersion, TransitionRule, LegalLink):
        db.execute(delete(model))

    amended_by = dict(
        db.execute(
            select(NodeSupersession.old_id, LegalNode.doc_id).join(
                LegalNode, LegalNode.node_id == NodeSupersession.new_id
            )
        ).all()
    )

    versions: list[dict] = []
    rows = db.execute(
        select(
            LegalNode.node_id,
            LegalNode.doc_id,
            LegalNode.text_hash,
            LegalNode.effective_from,
            LegalNode.effective_to,
            LegalDocument.effective_date,
            LegalDocument.expired_date,
            LegalDocument.source_url,
        )
        .join(LegalDocument, LegalDocument.doc_id == LegalNode.doc_id)
        .where(LegalDocument.doc_type.is_distinct_from("upload"))
    )
    for r in rows:
        valid_from = r.effective_from or r.effective_date
        valid_to = r.effective_to or r.expired_date
        versions.append(
            {
                "provision_key": r.node_id,
                "doc_id": r.doc_id,
                "text_hash": r.text_hash,
                "source_url": r.source_url,
                "valid_from": valid_from,
                "valid_to": valid_to,
                "status": status_at(valid_from, valid_to, day),
                "amended_by": amended_by.get(r.node_id),
                "known_from": day,
            }
        )
    db.execute(insert(ProvisionVersion), versions)

    links: dict[tuple[str, str, str], dict] = {}

    def add(
        from_key: str, to_key: str, link_type: str, *, source: str, valid_from: date | None = None
    ) -> None:
        links.setdefault(
            (from_key, to_key, link_type),
            {
                "from_key": from_key,
                "to_key": to_key,
                "link_type": link_type,
                "valid_from": valid_from,
                "source": source,
            },
        )

    for r in db.execute(select(NodeReference.from_id, NodeReference.to_id)):
        add(r.from_id, r.to_id, "cites", source="node_reference")

    for s in db.execute(
        select(NodeSupersession.old_id, NodeSupersession.new_id, LegalNode.effective_from).join(
            LegalNode, LegalNode.node_id == NodeSupersession.new_id
        )
    ):
        add(s.new_id, s.old_id, "replaces", source="node_supersession", valid_from=s.effective_from)

    for d in db.execute(
        select(DocumentRelation.from_doc, DocumentRelation.to_doc).where(
            DocumentRelation.rel == "REPLACES"
        )
    ):
        add(d.from_doc, d.to_doc, "replaces", source="document_relation")

    add("nd145_2020", "blld2019", "guides", source="seed", valid_from=date(2021, 2, 1))
    db.execute(insert(LegalLink), list(links.values()))

    provision_ref = db.execute(
        select(LegalNode.node_id).where(
            LegalNode.doc_id == SEED_DOC,
            LegalNode.level == "article",
            LegalNode.article_no == 220,
        )
    ).scalar()
    db.execute(
        insert(TransitionRule),
        [
            {
                "doc_key": SEED_DOC,
                "condition": SEED_CONDITION,
                "outcome": "mixed",
                "provision_ref": provision_ref,
                "note": SEED_NOTE,
            }
        ],
    )
    db.flush()
    return {
        "provision_version": len(versions),
        "legal_link": len(links),
        "transition_rule": 1,
    }


def versions_for(db: Session, provision_key: str) -> list[dict]:
    rows = db.execute(
        select(ProvisionVersion)
        .where(ProvisionVersion.provision_key == provision_key)
        .order_by(ProvisionVersion.valid_from)
    ).scalars()
    cols = [c.name for c in ProvisionVersion.__table__.columns]
    return [{name: getattr(r, name) for name in cols} for r in rows]


def in_force_at(db: Session, day: date, doc_id: str | None = None) -> list[str]:
    """provision_key còn hiệu lực tại `day` (valid_to là mốc độc quyền)."""
    stmt = (
        select(ProvisionVersion.provision_key)
        .where(
            (ProvisionVersion.valid_from.is_(None)) | (ProvisionVersion.valid_from <= day),
            (ProvisionVersion.valid_to.is_(None)) | (ProvisionVersion.valid_to > day),
        )
        .order_by(ProvisionVersion.provision_key)
    )
    if doc_id:
        stmt = stmt.where(ProvisionVersion.doc_id == doc_id)
    return list(db.execute(stmt).scalars())
