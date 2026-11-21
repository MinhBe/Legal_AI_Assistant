"use client";

/* Trang /ra-soat-hop-dong: dán hoặc tải hợp đồng lao động, rà soát bằng luật code.
   Backend: POST /api/contract/review (văn bản) và /api/contract/review-file (tệp).
   Không gọi LLM, không lưu nội dung. Giao diện tối giản, làm đẹp sau. */

import { useState } from "react";
import Link from "next/link";

import { apiFetch } from "@/lib/api";

type Basis = { doc_id: string; node_id?: string; label: string };
type Finding = {
  rule: string;
  severity: "high" | "medium" | "low";
  clause: number | null;
  message: string;
  suggestion: string;
  basis: Basis[];
  quote: string;
};
type Result = {
  as_of: string;
  verdict: "ok" | "review" | "risky";
  counts: Record<string, number>;
  findings: Finding[];
  facts: Record<string, unknown>;
  note: string;
};

const SEV: Record<Finding["severity"], { label: string; color: string }> = {
  high: { label: "Trái luật", color: "#b42318" },
  medium: { label: "Cần sửa", color: "#b54708" },
  low: { label: "Lưu ý", color: "#475467" },
};
const VERDICT = { ok: "Không thấy vấn đề", review: "Cần sửa vài điểm", risky: "Có điều khoản trái luật" };

const SAMPLE = `HỢP ĐỒNG LAO ĐỘNG
Bên A: Công ty TNHH ABC, địa chỉ 12 Lê Lợi, Quận 1.
Bên B: Nguyễn Văn A, ngày sinh 01/01/1995, CCCD số ...
Điều 1. Công việc
Vị trí: nhân viên kinh doanh, yêu cầu trình độ đại học. Địa điểm làm việc: TP. Hồ Chí Minh, vùng I.
Điều 2. Thời hạn hợp đồng
Hợp đồng xác định thời hạn 48 tháng. Thời gian thử việc 3 tháng, lương thử việc bằng 70% lương chính thức.
Điều 3. Tiền lương
Mức lương cơ bản: 4.500.000 đồng/tháng, trả lương bằng chuyển khoản ngày 5 hằng tháng.
Điều 4. Thời giờ làm việc
Làm việc 10 giờ/ngày, 60 giờ/tuần. Làm thêm tối đa 60 giờ/tháng. Nghỉ phép 10 ngày mỗi năm.
Điều 5. Cam kết
Công ty giữ bản chính bằng đại học trong thời gian làm việc và Bên B đặt cọc 5.000.000 đồng.
Phạt tiền 200.000 đồng mỗi lần đi muộn vi phạm nội quy.
Người lao động muốn nghỉ việc phải báo trước 60 ngày.`;

export default function ContractReviewPage() {
  const [text, setText] = useState("");
  const [asOf, setAsOf] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Result | null>(null);

  async function run() {
    setBusy(true);
    setError("");
    try {
      let res: Response;
      if (file) {
        const form = new FormData();
        form.append("file", file);
        if (asOf) form.append("as_of", asOf);
        res = await apiFetch("/api/contract/review-file", { method: "POST", body: form });
      } else {
        res = await apiFetch("/api/contract/review", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text, as_of: asOf || null }),
        });
      }
      const data = await res.json();
      if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Nội dung chưa hợp lệ (tối thiểu 20 ký tự).");
      setResult(data as Result);
    } catch (err) {
      setResult(null);
      setError(err instanceof Error ? err.message : "Không rà soát được, thử lại.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main style={{ maxWidth: 920, margin: "0 auto", padding: "24px 16px" }}>
      <Link href="/">← Về trang chính</Link>
      <h1>Rà soát hợp đồng lao động</h1>
      <p>Đối chiếu từng điều khoản với Bộ luật Lao động 2019 và lương tối thiểu vùng tại ngày áp dụng. Chạy bằng luật
        lập trình sẵn, không gửi nội dung ra ngoài, không lưu lại.</p>

      <textarea value={text} onChange={(e) => { setText(e.target.value); setFile(null); }} rows={14}
        placeholder="Dán nội dung hợp đồng vào đây…" style={{ width: "100%", fontFamily: "inherit" }} />
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center", margin: "8px 0 16px" }}>
        <button type="button" onClick={() => { setText(SAMPLE); setFile(null); }}>Dùng hợp đồng mẫu có lỗi</button>
        <label>Hoặc tải tệp (DOCX, PDF, ảnh):{" "}
          <input type="file" accept=".docx,.pdf,.txt,.png,.jpg,.jpeg" onChange={(e) => setFile(e.target.files?.[0] || null)} />
        </label>
        <label>Ngày áp dụng: <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></label>
        <button type="button" onClick={run} disabled={busy || (!file && text.trim().length < 20)}>
          {busy ? "Đang rà soát…" : "Rà soát"}
        </button>
      </div>

      {error && <p role="alert" style={{ color: "#b42318" }}>{error}</p>}

      {result && (
        <section>
          <h2>{VERDICT[result.verdict]}</h2>
          <p>Áp dụng tại ngày {result.as_of}: {result.counts.high || 0} điểm trái luật, {result.counts.medium || 0} điểm
            cần sửa, {result.counts.low || 0} lưu ý.</p>
          <ol style={{ paddingLeft: 20 }}>
            {result.findings.map((f, i) => (
              <li key={i} style={{ marginBottom: 14 }}>
                <strong style={{ color: SEV[f.severity].color }}>{SEV[f.severity].label}</strong>
                {f.clause != null && <> · Điều {f.clause} của hợp đồng</>}
                <div>{f.message}</div>
                {f.quote && <blockquote style={{ margin: "4px 0", color: "#475467" }}>“{f.quote}”</blockquote>}
                <div>Đề xuất: {f.suggestion}</div>
                <div style={{ fontSize: 13, color: "#475467" }}>Căn cứ: {f.basis.map((b) => b.label).join("; ")}</div>
              </li>
            ))}
          </ol>
          <p style={{ fontSize: 13, color: "#475467" }}>{result.note}</p>
        </section>
      )}
    </main>
  );
}
