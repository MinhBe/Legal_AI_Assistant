"use client";

/* Trang /tinh: sáu máy tính lao động, chọn phiên bản luật theo ngày sự kiện.
   Backend: POST /api/calc/{kind}. Kết quả luôn kèm căn cứ và nhãn cần luật sư. */

import { useState } from "react";
import Link from "next/link";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
const WARNING = "Kết quả tính tự động — cần luật sư đối chiếu";

type FieldType = "text" | "number" | "money" | "date" | "select" | "checkbox";
type Field = {
  name: string;
  label: string;
  type: FieldType;
  options?: { value: string; label: string }[];
  hint?: string;
};
type Tab = { kind: string; label: string; fields: Field[] };
type Basis = { doc_id: string; node_id?: string; label: string };
type TimeframeDoc = { doc_id: string; title?: string; number?: string };
type CalcResult = {
  value: number | string;
  unit: string;
  steps: string[];
  basis: Basis[];
  version: string;
  note: string;
  deadline?: string;
  timeframe_version?: TimeframeDoc[];
};

const EVENT: Field = { name: "event_date", label: "Ngày sự kiện", type: "date", hint: "Bỏ trống = hôm nay" };

const TABS: Tab[] = [
  {
    kind: "notice",
    label: "Báo trước",
    fields: [
      {
        name: "contract_type", label: "Loại hợp đồng", type: "select",
        options: [
          { value: "indefinite", label: "Không xác định thời hạn" },
          { value: "fixed", label: "Xác định thời hạn" },
        ],
      },
      { name: "employer_side", label: "Người sử dụng lao động đơn phương chấm dứt", type: "checkbox" },
      { name: "term_months", label: "Thời hạn hợp đồng (tháng)", type: "number" },
      EVENT,
    ],
  },
  {
    kind: "service-years",
    label: "Thời gian làm việc",
    fields: [
      { name: "start", label: "Bắt đầu làm việc", type: "date" },
      { name: "end", label: "Kết thúc làm việc", type: "date" },
      { name: "unemployment_insured_months", label: "Số tháng đã đóng BHTN", type: "number" },
      EVENT,
    ],
  },
  {
    kind: "severance",
    label: "Trợ cấp thôi việc",
    fields: [
      { name: "avg_salary_6m", label: "Lương bình quân 6 tháng (VND)", type: "money" },
      { name: "years", label: "Số năm tính trợ cấp", type: "number" },
      EVENT,
    ],
  },
  {
    kind: "job-loss",
    label: "Trợ cấp mất việc",
    fields: [
      { name: "avg_salary_6m", label: "Lương bình quân 6 tháng (VND)", type: "money" },
      { name: "years", label: "Số năm tính trợ cấp", type: "number" },
      EVENT,
    ],
  },
  {
    kind: "unlawful-dismissal",
    label: "Sa thải trái luật",
    fields: [
      { name: "monthly_salary", label: "Lương tháng (VND)", type: "money" },
      { name: "days_not_working", label: "Số ngày không được làm việc", type: "number" },
      { name: "notice_days_missing", label: "Số ngày thiếu báo trước", type: "number" },
      { name: "daily_salary", label: "Lương ngày (VND, bỏ trống = tháng / 26)", type: "money" },
      EVENT,
    ],
  },
  {
    kind: "limitation",
    label: "Thời hiệu",
    fields: [
      { name: "discovered_on", label: "Ngày phát hiện vi phạm", type: "date" },
      { name: "dispute", label: "Loại tranh chấp", type: "select", options: [{ value: "individual", label: "Cá nhân" }] },
      EVENT,
    ],
  },
];

function groupDigits(value: string): string {
  const digits = value.replace(/\D/g, "").replace(/^0+(?=\d)/, "");
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

function FieldInput({ field, value, onChange }: {
  field: Field;
  value: string;
  onChange: (v: string) => void;
}) {
  const id = `calc-${field.name}`;
  if (field.type === "checkbox") {
    return (
      <label className="calc-check" htmlFor={id}>
        <input
          id={id}
          type="checkbox"
          checked={value !== "false"}
          onChange={(e) => onChange(e.target.checked ? "true" : "false")}
        />
        <span>{field.label}</span>
      </label>
    );
  }
  return (
    <label className="calc-field" htmlFor={id}>
      <span>{field.label}{field.hint ? <em> — {field.hint}</em> : null}</span>
      {field.type === "select" ? (
        <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
          {(field.options ?? []).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      ) : (
        <input
          id={id}
          type={field.type === "money" ? "text" : field.type}
          inputMode={field.type === "money" || field.type === "number" ? "numeric" : undefined}
          value={field.type === "money" ? groupDigits(value) : value}
          onChange={(e) => onChange(
            field.type === "money" ? e.target.value.replace(/\D/g, "") : e.target.value,
          )}
        />
      )}
    </label>
  );
}

function ResultCard({ result }: { result: CalcResult }) {
  const value = typeof result.value === "number"
    ? result.value.toLocaleString("vi-VN")
    : result.value;
  return (
    <section className="calc-result">
      <p className="calc-warning">{WARNING}</p>
      <div className="calc-value">
        {value} <span className="calc-unit">{result.unit}</span>
      </div>
      {result.deadline && (
        <p className="calc-deadline">Hạn cuối: {result.deadline.split("-").reverse().join("/")}</p>
      )}

      <h3 className="calc-section-title">Các bước tính</h3>
      <ol className="calc-steps">
        {result.steps.map((step, i) => <li key={i}>{step}</li>)}
      </ol>

      <h3 className="calc-section-title">Căn cứ pháp lý</h3>
      <div className="calc-basis">
        {result.basis.map((item) => item.node_id ? (
          <a
            key={`${item.doc_id}-${item.node_id}`}
            className="calc-chip"
            href={`${API_BASE}/api/law/${item.node_id}`}
            target="_blank"
            rel="noreferrer"
            title={item.doc_id}
          >
            {item.label}
          </a>
        ) : (
          <span key={`${item.doc_id}-${item.label}`} className="calc-chip" title={item.doc_id}>
            {item.label}
          </span>
        ))}
      </div>

      <p className="calc-version">
        Phiên bản áp dụng: <strong>{result.version === "blld2012" ? "BLLĐ 2012" : "BLLĐ 2019"}</strong>
      </p>
      <p className="calc-note">{result.note}</p>
    </section>
  );
}

export default function CalcPage() {
  const [tabIndex, setTabIndex] = useState(0);
  const [values, setValues] = useState<Record<string, string>>({
    contract_type: "indefinite",
    employer_side: "true",
    dispute: "individual",
  });
  const [result, setResult] = useState<CalcResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const tab = TABS[tabIndex];

  const visibleFields = tab.fields.filter((f) =>
    !(tab.kind === "notice" && f.name === "term_months" && values.contract_type !== "fixed"),
  );

  function choose(index: number) {
    setTabIndex(index);
    setResult(null);
    setError("");
  }

  function setValue(name: string, value: string) {
    setValues((prev) => ({ ...prev, [name]: value }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const body: Record<string, unknown> = {};
    for (const field of visibleFields) {
      const raw = values[field.name] ?? "";
      if (field.type === "checkbox") {
        body[field.name] = raw !== "false";
        continue;
      }
      if (raw === "") continue;
      body[field.name] = field.type === "money" || field.type === "number" ? Number(raw) : raw;
    }
    try {
      const res = await fetch(`${API_BASE}/api/calc/${tab.kind}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(typeof data.detail === "string" ? data.detail : "Dữ liệu chưa hợp lệ.");
      }
      setResult(data as CalcResult);
    } catch (err) {
      setResult(null);
      setError(err instanceof Error ? err.message : "Không tính được, thử lại.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="calc-shell">
      <header className="calc-header">
        <Link href="/" className="calc-back">← Trang chủ</Link>
        <span className="calc-title">Máy tính lao động</span>
      </header>

      <main className="calc-body">
        <p className="calc-warning">{WARNING}</p>

        <div className="calc-tabs" role="tablist">
          {TABS.map((item, i) => (
            <button
              key={item.kind}
              role="tab"
              aria-selected={i === tabIndex}
              className={`calc-tab ${i === tabIndex ? "active" : ""}`}
              onClick={() => choose(i)}
            >
              {item.label}
            </button>
          ))}
        </div>

        <form className="calc-form" onSubmit={submit}>
          {visibleFields.map((field) => (
            <FieldInput
              key={field.name}
              field={field}
              value={values[field.name] ?? ""}
              onChange={(v) => setValue(field.name, v)}
            />
          ))}
          <div className="calc-actions">
            <button className="calc-btn" type="submit" disabled={busy}>
              {busy ? "Đang tính…" : "Tính"}
            </button>
            {error && <span className="calc-error">{error}</span>}
          </div>
        </form>

        {result && <ResultCard result={result} />}
      </main>
    </div>
  );
}
