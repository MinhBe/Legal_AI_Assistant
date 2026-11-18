"""Định tuyến lĩnh vực câu hỏi (mở rộng kho, 18/11/2026)."""

from app.rag.domain import LABOUR, classify, label


def test_labour_is_default_and_wins_labour_questions():
    assert classify("Hôm nay trời đẹp") == [LABOUR]
    assert classify("Người lao động bị sa thải trái luật thì được bồi thường gì?")[0] == LABOUR


def test_other_domains():
    assert classify("Cha mẹ có 300 m² đất ở, tách thửa cho 3 con được không?")[0] == "dat_dai"
    assert classify("Nhờ người khác đánh đề có bị truy cứu hình sự không?")[0] == "hinh_su"
    assert classify("Ly hôn thì chia tài sản chung vợ chồng thế nào?")[0] == "hon_nhan_gia_dinh"
    assert classify("Công ty khấu trừ thuế thu nhập cá nhân thừa, hoàn thuế ra sao?")[0] == "thue_tncn"


def test_salary_tax_keeps_both_domains():
    d = classify("Thuế thu nhập cá nhân tính trên tiền lương hằng tháng như thế nào?")
    assert d[0] == "thue_tncn" and LABOUR in d
    assert label("dat_dai") == "Đất đai"
