"use client";

/* Hiểu hệ thống Legal Agentic: bài học tương tác, sơ đồ SVG chạy từng bước (Minh 20/11/2026).
   Tự thiết kế; nội dung ở lib/explainer/lessons.ts. Phím ←/→ để lùi/tiến, Space để tự chạy. */
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { type Lesson, LESSONS, STATUS_LABEL } from "@/lib/explainer/lessons";

const W = 1080, H = 300, NW = 150, NH = 58;

function Diagram({ lesson, step }: { lesson: Lesson; step: number }) {
  const s = lesson.steps[step];
  const on = new Set(s.nodes);
  const onEdge = new Set(s.edges.map(([a, b]) => `${a}>${b}`));
  const pos = Object.fromEntries(lesson.nodes.map((n) => [n.id, n]));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="ex-svg" role="img" aria-label={`Sơ đồ: ${s.title}`}>
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" className="ex-arrow" />
        </marker>
      </defs>
      {lesson.edges.map((e) => {
        const a = pos[e.from], b = pos[e.to];
        const x1 = a.x + NW / 2, y1 = a.y, x2 = b.x - NW / 2, y2 = b.y;
        const active = onEdge.has(`${e.from}>${e.to}`);
        const d = `M${x1},${y1} C${(x1 + x2) / 2},${y1} ${(x1 + x2) / 2},${y2} ${x2},${y2}`;
        return (
          <g key={`${e.from}-${e.to}`} className={active ? "ex-edge on" : "ex-edge"}>
            <path d={d} markerEnd="url(#arrow)" />
            {active && <circle r="5" className="ex-packet"><animateMotion dur="1.4s" repeatCount="indefinite" path={d} /></circle>}
            {e.label && <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 6} className="ex-edge-label">{e.label}</text>}
          </g>
        );
      })}
      {lesson.nodes.map((n) => (
        <g key={n.id} className={`ex-node ${n.kind} ${on.has(n.id) ? "on" : ""}`} transform={`translate(${n.x - NW / 2},${n.y - NH / 2})`}>
          <rect width={NW} height={NH} rx="10" />
          <text x={NW / 2} y="24" className="ex-node-label">{n.label}</text>
          <text x={NW / 2} y="42" className="ex-node-sub">{n.sub}</text>
        </g>
      ))}
    </svg>
  );
}

export default function Explainer() {
  const [li, setLi] = useState(0);
  const [step, setStep] = useState(0);
  const [auto, setAuto] = useState(false);
  const lesson = LESSONS[li];
  const s = lesson.steps[step];
  const last = lesson.steps.length - 1;

  useEffect(() => { setStep(0); }, [li]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") setStep((x) => Math.min(last, x + 1));
      if (e.key === "ArrowLeft") setStep((x) => Math.max(0, x - 1));
      if (e.key === " ") { e.preventDefault(); setAuto((a) => !a); }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [last]);
  useEffect(() => {
    if (!auto) return;
    const t = setInterval(() => setStep((x) => (x >= last ? 0 : x + 1)), 4000);
    return () => clearInterval(t);
  }, [auto, last]);

  const counts = useMemo(() => {
    const c = { done: 0, wip: 0, roadmap: 0 };
    lesson.steps.forEach((x) => { c[x.status] += 1; });
    return c;
  }, [lesson]);

  return (
    <main className="ex-page">
      <header className="ex-top">
        <Link href="/" className="auth-link">← Trợ lý</Link>
        <strong>Legal Agentic · Hiểu hệ thống</strong>
      </header>
      <div className="ex-layout">
        <aside className="ex-lessons">
          {LESSONS.map((l, i) => (
            <button key={l.id} className={i === li ? "active" : ""} onClick={() => setLi(i)}>
              <span>Bài {i + 1}</span> {l.title} <small>{l.minutes} phút · {l.steps.length} bước</small>
            </button>
          ))}
          <p className="vi-note">Sắp có: dữ liệu và train model, RAG theo thời gian, agentic và luật sư duyệt, automation và MCP.</p>
        </aside>
        <section className="ex-main">
          <h1>{lesson.title}</h1>
          <p className="ex-summary">{lesson.summary}</p>
          <div className="ex-legend">
            <span className="ex-st done">Đã có {counts.done}</span>
            <span className="ex-st wip">Đang làm {counts.wip}</span>
            <span className="ex-st roadmap">Lộ trình {counts.roadmap}</span>
          </div>
          <div className="ex-diagram"><Diagram lesson={lesson} step={step} /></div>
          <ol className="ex-steps" aria-label="Các bước">
            {lesson.steps.map((x, i) => (
              <li key={i}>
                <button className={`${i === step ? "active" : ""} ${x.status}`} onClick={() => setStep(i)} aria-label={`Bước ${i + 1}: ${x.title}`}>{i + 1}</button>
              </li>
            ))}
          </ol>
        </section>
        <aside className="ex-panel">
          <div className="ex-step-head">
            <span>Bước {step + 1}/{lesson.steps.length}</span>
            <span className={`ex-st ${s.status}`}>{STATUS_LABEL[s.status]}</span>
          </div>
          <h2>{s.title}</h2>
          <p>{s.body}</p>
          {s.problem && <div className="ex-problem"><strong>Vấn đề</strong><p>{s.problem}</p></div>}
          {s.metric && s.metric.map((m) => (
            <div key={m.label} className="ex-metric"><small>{m.label}</small><b>{m.value}</b></div>
          ))}
          <div className="ex-nav">
            <button className="vi-btn" disabled={step === 0} onClick={() => setStep(step - 1)}>← Lùi</button>
            <button className="vi-btn" onClick={() => setAuto((a) => !a)}>{auto ? "❚❚ Dừng" : "▶ Tự chạy"}</button>
            <button className="vi-btn primary" disabled={step === last} onClick={() => setStep(step + 1)}>
              {step === last ? "Hết bài" : `Tiếp: ${lesson.steps[step + 1].title} →`}
            </button>
          </div>
          <p className="vi-note">← / → để chuyển bước · Space để tự chạy</p>
        </aside>
      </div>
    </main>
  );
}
