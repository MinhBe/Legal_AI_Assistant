"use client";

/* Trang /theo-doi: đăng ký theo dõi văn bản mới theo lĩnh vực + từ khoá.
   Backend: /api/intel/domains, /api/intel/subscriptions[/{id}/feed|read]. Giao diện tối giản. */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { apiFetch } from "@/lib/api";

type Domain = { id: string; label: string };
type Sub = { id: number; name: string; domains: string[]; domain_labels: string[]; keywords: string[]; unread?: number };
type Item = {
  id: string; title: string; number: string; url: string; source: string;
  listed_date: string | null; domains: string[]; why: string[]; unread: boolean; in_corpus: boolean;
};

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(path, init);
  const data = await res.json();
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Có lỗi, thử lại.");
  return data as T;
}

export default function FollowPage() {
  const [domains, setDomains] = useState<Domain[]>([]);
  const [subs, setSubs] = useState<Sub[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [keywords, setKeywords] = useState("");
  const [active, setActive] = useState<number | null>(null);
  const [items, setItems] = useState<Item[]>([]);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const data = await json<{ subscriptions: Sub[] }>("/api/intel/subscriptions");
    setSubs(data.subscriptions);
  }, []);

  useEffect(() => {
    json<{ domains: Domain[] }>("/api/intel/domains").then((d) => setDomains(d.domains)).catch(() => {});
    load().catch((e) => setError(e.message));
  }, [load]);

  async function create() {
    setError("");
    try {
      await json("/api/intel/subscriptions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ domains: picked, keywords: keywords.split(",").map((k) => k.trim()).filter(Boolean) }),
      });
      setPicked([]);
      setKeywords("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không tạo được.");
    }
  }

  async function open(id: number) {
    setActive(id);
    const data = await json<{ items: Item[] }>(`/api/intel/subscriptions/${id}/feed`);
    setItems(data.items);
    await json(`/api/intel/subscriptions/${id}/read`, { method: "POST" });
    await load();
  }

  async function remove(id: number) {
    await json(`/api/intel/subscriptions/${id}`, { method: "DELETE" });
    if (active === id) { setActive(null); setItems([]); }
    await load();
  }

  return (
    <main style={{ maxWidth: 920, margin: "0 auto", padding: "24px 16px" }}>
      <Link href="/">← Về trang chính</Link>
      <h1>Theo dõi văn bản mới</h1>
      <p>Chọn lĩnh vực và từ khoá. Khi hệ thống quét được văn bản mới khớp, nó hiện ở đây kèm lý do khớp.</p>

      <section style={{ border: "1px solid #d0d5dd", borderRadius: 8, padding: 12, marginBottom: 16 }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
          {domains.map((d) => (
            <label key={d.id}>
              <input type="checkbox" checked={picked.includes(d.id)}
                onChange={(e) => setPicked(e.target.checked ? [...picked, d.id] : picked.filter((x) => x !== d.id))} />{" "}
              {d.label}
            </label>
          ))}
        </div>
        <div style={{ marginTop: 8 }}>
          <input value={keywords} onChange={(e) => setKeywords(e.target.value)} style={{ width: "60%" }}
            placeholder="Từ khoá, cách nhau bằng dấu phẩy (vd: lương tối thiểu, thai sản)" />{" "}
          <button type="button" onClick={create}>Đăng ký</button>
        </div>
        {error && <p role="alert" style={{ color: "#b42318" }}>{error}</p>}
      </section>

      <ul style={{ paddingLeft: 20 }}>
        {subs.map((s) => (
          <li key={s.id} style={{ marginBottom: 6 }}>
            <button type="button" onClick={() => open(s.id)}>{s.name}</button>
            {s.keywords.length > 0 && <> · từ khoá: {s.keywords.join(", ")}</>}
            {!!s.unread && <strong> · {s.unread} mới</strong>}{" "}
            <button type="button" onClick={() => remove(s.id)} aria-label={`Huỷ ${s.name}`}>Huỷ</button>
          </li>
        ))}
        {subs.length === 0 && <li>Chưa có đăng ký nào.</li>}
      </ul>

      {active !== null && (
        <section>
          <h2>Văn bản khớp</h2>
          {items.length === 0 && <p>Chưa có văn bản nào khớp.</p>}
          <ol style={{ paddingLeft: 20 }}>
            {items.map((it) => (
              <li key={it.id} style={{ marginBottom: 10 }}>
                {it.unread && <strong>Mới · </strong>}
                <a href={it.url} target="_blank" rel="noreferrer">{it.number ? `${it.number}: ` : ""}{it.title}</a>
                <div style={{ fontSize: 13, color: "#475467" }}>
                  {it.listed_date || ""} · {it.source} · khớp {it.why.join(", ")}
                  {it.in_corpus ? " · đã có trong kho" : " · chưa có trong kho"}
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}
    </main>
  );
}
