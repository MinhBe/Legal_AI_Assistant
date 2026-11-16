"use client";

/* Trang knowledge graph: giữ state và lắp các phần lại với nhau.
   - lib/graph/model.ts           từ vựng, ontology, khớp triplet, chuỗi lọc (thuần)
   - lib/graph/drawForceGraph.ts  vẽ đồ thị chính bằng d3
   - components/graph/*           bản đồ quan hệ, thanh công cụ, chip lọc, các tab */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Script from "next/script";
import Link from "next/link";

import FilterChips from "@/components/graph/FilterChips";
import GraphToolbar from "@/components/graph/GraphToolbar";
import RelationshipMap from "@/components/graph/RelationshipMap";
import { DetailPanel, HelpPanel, LookupPanel } from "@/components/graph/SidePanels";
import { applyHighlight, drawForceGraph, type ForceGraph, zoomBy, zoomFit } from "@/lib/graph/drawForceGraph";
import {
  buildView, type ColorBy, deriveOntology, type GNode, type GraphData, type GroupBy, lookupNodes,
  ontoPositions, type Panel, type Triplet,
} from "@/lib/graph/model";
import { apiFetch } from "@/lib/api";
import { RequirePerm } from "@/lib/auth";
import { currentMode, type Mode, MODE_TEXT } from "@/lib/mode";
import { loadNumber, saveNumber, startDrag } from "@/lib/ui/drag";

const DOC_STATUS: Record<string, string> = {
  pending_review: "chờ duyệt", approved: "đã duyệt", rejected: "đã loại", failed: "lỗi",
};

const toggled = (set: Set<string>, item: string) => {
  const next = new Set(set);
  if (next.has(item)) next.delete(item); else next.add(item);
  return next;
};

export default function GraphPage() {
  return (
    <RequirePerm perm="graph">
      <GraphPageInner />
    </RequirePerm>
  );
}

function GraphPageInner() {
  const svgRef = useRef<SVGSVGElement>(null);
  const graphRef = useRef<ForceGraph | null>(null);

  const [raw, setRaw] = useState<GraphData>({ nodes: [], edges: [] });
  const [query, setQuery] = useState("");
  const [docId, setDocId] = useState<string | null>(null);
  const [docInfo, setDocInfo] = useState<{ filename: string; status: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [d3Ready, setD3Ready] = useState(false);
  const [selected, setSelected] = useState<GNode | null>(null);

  /* ontology-driven state, mirroring the yFiles demo */
  const [hiddenNodeTypes, setHiddenNodeTypes] = useState<Set<string>>(new Set());
  const [hiddenEdgeTypes, setHiddenEdgeTypes] = useState<Set<string>>(new Set());
  const [filterTriplet, setFilterTriplet] = useState<Triplet | null>(null);
  const [highlight, setHighlight] = useState<Triplet | null>(null);
  const [focusId, setFocusId] = useState<string | null>(null);
  const [groupBy, setGroupBy] = useState<GroupBy>("radial");
  const [colorBy, setColorBy] = useState<ColorBy>("type");

  /* right-hand collapsible panels */
  const [panel, setPanel] = useState<Panel>("onto");
  const [lookup, setLookup] = useState("");
  const [lookupType, setLookupType] = useState<string>("");
  const [sideW, setSideW] = useState(520);
  // cổng 3001 = chế độ ôn phỏng vấn; fetchGraph đọc thẳng currentMode() nên không phải chờ state này
  const [mode, setMode] = useState<Mode>("law");

  useEffect(() => {
    const w = loadNumber("kgv_sideW");
    if (w) setSideW(w);
    setMode(currentMode());
  }, []);

  /* /graph?doc_id=… : đồ thị của một tài liệu tải lên thay cho truy vấn */
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("doc_id");
    if (!id) return;
    setDocId(id);
    apiFetch("/api/uploads")
      .then((r) => (r.ok ? r.json() : []))
      .then((rows: { doc_id?: string; filename?: string; status?: string }[]) => {
        const hit = rows.find((u) => u.doc_id === id);
        if (hit) setDocInfo({ filename: hit.filename || id, status: hit.status || "" });
      })
      .catch((e) => console.error(e));
  }, []);

  /* ── fetch ──────────────────────────────────────────────────────────────── */
  const fetchGraph = useCallback(async (q: string) => {
    setLoading(true);
    try {
      const url = docId
        ? `/api/graph?doc_id=${encodeURIComponent(docId)}&uploads=1&top_k=150&mode=law`
        : `/api/graph?query=${encodeURIComponent(q)}&top_k=150&mode=${currentMode()}`;
      const res = await apiFetch(url);
      const data = await res.json();
      setRaw({ nodes: data.nodes || [], edges: data.edges || [] });
      setHiddenNodeTypes(new Set()); setHiddenEdgeTypes(new Set());
      setFilterTriplet(null); setHighlight(null); setFocusId(null); setSelected(null);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [docId]);

  useEffect(() => { if (d3Ready) fetchGraph(query); }, [d3Ready, query, fetchGraph]);

  /* ── derived data ───────────────────────────────────────────────────────── */
  const ontology = useMemo(() => deriveOntology(raw), [raw]);
  const ontoPos = useMemo(() => ontoPositions(ontology.types), [ontology.types]);
  const typeCounts = useMemo(() => {
    const c: Record<string, number> = {};
    raw.nodes.forEach((n) => { c[n.type] = (c[n.type] || 0) + 1; });
    return c;
  }, [raw.nodes]);
  const view = useMemo(
    () => buildView(raw, ontology, { hiddenNodeTypes, hiddenEdgeTypes, filterTriplet, focusId }),
    [raw, ontology, hiddenNodeTypes, hiddenEdgeTypes, filterTriplet, focusId],
  );
  const lookupHits = useMemo(() => lookupNodes(raw.nodes, lookup, lookupType), [raw.nodes, lookup, lookupType]);

  /* ── main graph ─────────────────────────────────────────────────────────── */
  useEffect(() => {
    if (!d3Ready || !svgRef.current) return;
    graphRef.current?.stop();
    const fg = drawForceGraph(svgRef.current, view, {
      groupBy, colorBy,
      onNodeClick: (d) => { setSelected(d); setPanel("detail"); },
    });
    graphRef.current = fg;
    return () => fg?.stop();
  }, [view, groupBy, colorBy, d3Ready]);

  // Re-apply after every redraw too: drawing builds fresh elements at full
  // opacity, so a highlight would silently vanish on a Group By / colour change.
  // Declared after the draw effect, so it always runs on the new elements.
  useEffect(() => {
    applyHighlight(graphRef.current, ontology, view, highlight);
  }, [highlight, view, ontology, groupBy, colorBy, d3Ready]);

  /* ── actions ────────────────────────────────────────────────────────────── */
  const activeFilter = !!(hiddenNodeTypes.size || hiddenEdgeTypes.size || filterTriplet || highlight || focusId);
  const resetAll = () => {
    setHiddenNodeTypes(new Set()); setHiddenEdgeTypes(new Set());
    setFilterTriplet(null); setHighlight(null); setFocusId(null);
  };
  const toggleNodeType = (t: string) => setHiddenNodeTypes((prev) => toggled(prev, t));
  const toggleEdgeType = (t: string) => setHiddenEdgeTypes((prev) => toggled(prev, t));
  const togglePanel = (p: Panel) => setPanel((cur) => (cur === p ? null : p));
  const focusNode = focusId ? raw.nodes.find((n) => n.id === focusId) : null;

  return (
    <>
      <Script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"
        strategy="afterInteractive" onLoad={() => setD3Ready(true)} />

      <div className="kgv-shell">
        <div className="kgv-topbar">
          <Link href="/" className="kgv-back">← Chat</Link>
          <span className="kgv-title">{MODE_TEXT[mode].graphTitle}</span>
          <span className="kgv-counts">
            <b>{view.nodes.length}</b>/{raw.nodes.length} nodes · <b>{view.edges.length}</b>/{raw.edges.length} edges
          </span>
        </div>

        {docId && (
          <div className="kgv-doc-banner" style={{
            display: "flex", alignItems: "center", gap: 8, padding: "6px 12px",
            fontSize: 13, background: "var(--card)", borderBottom: "1px solid var(--border)",
          }}>
            Đang xem tài liệu tải lên: <b>{docInfo?.filename || docId}</b>
            {docInfo?.status ? ` — ${DOC_STATUS[docInfo.status] ?? docInfo.status}` : ""}
            {/* thẻ a thường: tải lại trang để bỏ hẳn doc_id (Link giữ nguyên state) */}
            <a href="/graph" className="kgv-back">Bỏ lọc</a>
          </div>
        )}

        {activeFilter && (
          <FilterChips
            filterTriplet={filterTriplet} highlight={highlight}
            hiddenNodeTypes={hiddenNodeTypes} hiddenEdgeTypes={hiddenEdgeTypes}
            focusLabel={focusId ? (focusNode?.label ?? "") : null}
            onClearFilter={() => setFilterTriplet(null)} onClearHighlight={() => setHighlight(null)}
            onToggleNodeType={toggleNodeType} onToggleEdgeType={toggleEdgeType}
            onClearFocus={() => setFocusId(null)} />
        )}

        <div className="kgv-body">
          <div className="kgv-canvas-wrap">
            {loading && <div className="kgv-loading">Đang tải đồ thị…</div>}
            {!loading && !view.nodes.length && (
              <div className="kgv-loading">Không còn node nào — bộ lọc đang quá chặt.</div>
            )}
            <svg ref={svgRef} className="kgv-svg" />

            <GraphToolbar
              activeFilter={activeFilter} groupBy={groupBy} colorBy={colorBy}
              onZoom={(k) => zoomBy(graphRef.current, k)}
              onFit={() => zoomFit(graphRef.current, svgRef.current)}
              onReset={resetAll} onGroupBy={setGroupBy} onColorBy={setColorBy} onSearch={setQuery} />
          </div>

          {panel && (<>
            <div className="kgv-side-resize" title="Kéo để đổi chiều rộng"
              onPointerDown={(e) => {
                const w0 = sideW;
                let w = w0;
                startDrag(e, (dx) => {
                  w = Math.max(300, Math.min(window.innerWidth - 320, w0 - dx));
                  setSideW(w);
                }, () => saveNumber("kgv_sideW", w));
              }} />
            <div className="kgv-side" style={{ width: sideW }}>
              {panel === "onto" && (
                <RelationshipMap
                  ontology={ontology} positions={ontoPos} typeCounts={typeCounts}
                  hiddenNodeTypes={hiddenNodeTypes} hiddenEdgeTypes={hiddenEdgeTypes}
                  filterTriplet={filterTriplet} highlight={highlight} activeFilter={activeFilter}
                  panelWidth={sideW}
                  onHighlight={setHighlight}
                  onFilter={(t) => { setFilterTriplet(t); setHighlight(null); }}
                  onToggleNodeType={toggleNodeType} onToggleEdgeType={toggleEdgeType}
                  onReset={resetAll} />
              )}
              {panel === "detail" && (
                <DetailPanel selected={selected} focused={!!selected && focusId === selected.id}
                  onToggleFocus={() => selected && setFocusId((p) => (p === selected.id ? null : selected.id))} />
              )}
              {panel === "filter" && (
                <LookupPanel types={ontology.types}
                  query={lookup} onQuery={setLookup} type={lookupType} onType={setLookupType}
                  hits={lookupHits} onPick={(n) => { setSelected(n); setFocusId(n.id); }} />
              )}
              {panel === "help" && <HelpPanel relations={ontology.edges} />}
            </div>
          </>)}

          <div className="kgv-tabs">
            <button className={panel === "onto" ? "on" : ""} onClick={() => togglePanel("onto")}>Bản đồ mối quan hệ</button>
            <button className={panel === "detail" ? "on" : ""} onClick={() => togglePanel("detail")}>Chi tiết</button>
            <button className={panel === "filter" ? "on" : ""} onClick={() => togglePanel("filter")}>Bộ lọc</button>
            <button className={panel === "help" ? "on" : ""} onClick={() => togglePanel("help")}>Tương tác</button>
          </div>
        </div>
      </div>
    </>
  );
}
