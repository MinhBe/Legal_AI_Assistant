"""GenAI soạn văn bản: biến, kiểm khi khoá, phiên bản khoá bất biến, soạn và kiểm kiểu dữ liệu."""

import pytest

from app.docgen import service as dg

BODY = ("HỢP ĐỒNG LAO ĐỘNG\nNgười lao động: {{ho_ten}}\nNgày bắt đầu: {{ngay_bat_dau}}\n"
        "Mức lương: {{muc_luong}}\nCông việc: {{mo_ta_cong_viec}}")


def test_fields_from_placeholders_and_types():
    f = {x["name"]: x["type"] for x in dg.default_fields(BODY)}
    assert f == {"ho_ten": "text", "ngay_bat_dau": "date", "muc_luong": "money", "mo_ta_cong_viec": "long_text"}


def test_check_value_formats_and_rejects():
    money = {"name": "muc_luong", "label": "Mức lương", "type": "money", "required": True}
    date = {"name": "ngay", "label": "Ngày", "type": "date", "required": True}
    assert dg._check_value(money, "12500000") == ("12.500.000 đồng", None)
    assert dg._check_value(money, "mười triệu")[1]
    assert dg._check_value(date, "2026-01-05") == ("05/01/2026", None)
    assert dg._check_value(date, "31/02/2026")[1]
    assert dg._check_value(money, "")[1] == "Thiếu Mức lương"


@pytest.mark.db
def test_workflow_propose_edit_lock_generate(db):
    from app.db.models import DocTemplate

    node = db.execute(dg.select(dg.LegalNode.node_id).where(dg.LegalNode.doc_id == "blld2019").limit(1)).scalar()
    t = dg.propose(db, name="HĐLĐ mẫu (test)", kind="hop_dong", body=BODY + " TODO", basis=[node],
                   note="đề xuất", author="ls-test")
    try:
        assert t.status == "proposed"
        v, issues = dg.lock(db, t, by="admin-test")  # còn TODO -> không khoá
        assert v is None and any(i["code"] == "unresolved" for i in issues)
        dg.save_version(db, t, body=BODY, fields=None, basis=[node], note="sửa", author="admin-test")
        v, _ = dg.lock(db, t, by="admin-test")
        assert v is not None and v.locked and t.status == "locked" and t.locked_version == 1
        # sửa sau khi khoá: tạo phiên bản 2, bản 1 vẫn khoá và vẫn dùng để soạn
        dg.save_version(db, t, body=BODY + "\nGhi chú: {{ghi_chu}}", fields=None, basis=[node], note="v2",
                        author="admin-test")
        out = dg.generate(db, t, {"ho_ten": "Nguyễn Văn B", "ngay_bat_dau": "05/01/2026",
                                  "muc_luong": "12500000", "mo_ta_cong_viec": "Kế toán"})
        assert out["ok"] and out["version"] == 1 and "12.500.000 đồng" in out["text"]
        assert out["basis"] and out["basis"][0]["node_id"] == node
        bad = dg.generate(db, t, {"ho_ten": "B"})
        assert not bad["ok"] and len(bad["errors"]) == 3
    finally:
        db.query(DocTemplate).filter_by(id=t.id).delete()
        db.commit()


@pytest.mark.db
def test_lint_flags_missing_and_expired_basis(db):
    old = db.execute(dg.select(dg.LegalNode.node_id).where(dg.LegalNode.doc_id == "blld2012").limit(1)).scalar()
    issues = dg.lint(db, "{{a}}", dg.default_fields("{{a}}"), ["khong-co", old])
    codes = {i["code"] for i in issues}
    assert {"basis_missing", "basis_expired"} <= codes


def test_document_numbers_are_text_not_numbers():
    f = {x["name"]: x["type"] for x in dg.default_fields("{{so_hop_dong}} {{so_ngay_nghi}}")}
    assert f == {"so_hop_dong": "text", "so_ngay_nghi": "number"}


def test_money_guess_skips_payment_method_and_period():
    f = {x["name"]: x["type"] for x in dg.default_fields("{{muc_luong}} {{hinh_thuc_tra_luong}} {{ky_han_tra_luong}} {{tien_thuong}}")}
    assert f == {"muc_luong": "money", "hinh_thuc_tra_luong": "text", "ky_han_tra_luong": "text", "tien_thuong": "money"}
