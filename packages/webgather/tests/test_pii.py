from __future__ import annotations

from webgather.pii import VietnamesePiiMasker


def test_masks_phone_cccd_email_consistently():
    m = VietnamesePiiMasker()
    t = "Liên hệ 0901234567 hoặc email a.b@cong.vn, CCCD 012345678901."
    out = m.mask(t)
    assert "0901234567" not in out
    assert "a.b@cong.vn" not in out
    assert "012345678901" not in out
    assert "[SĐT-1]" in out and "[EMAIL-1]" in out and "[CCCD-1]" in out


def test_same_value_same_pseudonym():
    m = VietnamesePiiMasker()
    out = m.mask("Gọi 0901234567. Lại gọi 0901234567.")
    assert out.count("[SĐT-1]") == 2


def test_name_and_company_pseudonyms():
    m = VietnamesePiiMasker()
    out = m.mask("Ông Trần Văn Hùng kiện Công ty TNHH Hoàng Gia.")
    assert "Trần Văn Hùng" not in out
    assert "Hoàng Gia" not in out
    assert "Nguyễn Văn" in out
    assert "Công ty" in out


def test_empty_is_safe():
    assert VietnamesePiiMasker().mask("") == ""
