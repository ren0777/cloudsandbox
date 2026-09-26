"use client";
// Architecture diagram of the student's own resources, drawn from the API's graph (which is derived only from
// grading-collector evidence). Live mode polls the read-only snapshot endpoint; static mode shows a stored
// graph (results pages). New resources briefly light up so students see the effect of each action.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";

export type GraphNode = { id: string; service: string; kind: string; label: string; lane: string; detail: string;
  state: "ok" | "warn" | "off"; flags: string[] };
export type Graph = { nodes: GraphNode[]; edges: { source: string; target: string; kind: string }[]; lanes: string[] };
export type Insights = { graph: Graph; cost?: CostEstimate | null };
export type CostEstimate = { simulated: true; pricing_version: string; pricing_effective: string; currency: string; hourly: string; monthly: string; disclaimer: string;
  lines: { resource: string; service: string; label: string; unit: string; quantity: string; rate: string; hourly: string; monthly: string; note?: string | null }[] };

const LANE_LABEL: Record<string, string> = { principals: "Identities", policies: "Permissions", compute: "Compute", network: "Network access", data: "Storage & data" };
const SERVICE: Record<string, { tag: string; color: string }> = {
  s3: { tag: "S3", color: "#2f9e44" }, dynamodb: { tag: "DynamoDB", color: "#3b5bdb" }, iam: { tag: "IAM", color: "#c2255c" },
  ec2: { tag: "EC2", color: "#d9730d" }, lambda: { tag: "Lambda", color: "#d9730d" } };
const KIND: Record<string, string> = { bucket: "Bucket", table: "Table", user: "User", group: "User group", role: "Role", policy: "Policy",
  instance: "Instance", security_group: "Security group", key_pair: "Key pair", function: "Function" };
const KIND_ORDER = ["user", "group", "role", "policy", "function", "instance", "security_group", "key_pair", "bucket", "table"];
const W = 244, H = 60, COL = 300, ROW = 76, TOP = 34, PAD = 16, LEFT = 64; // LEFT leaves room for same-lane arcs

function layout(g: Graph) {
  const pos = new Map<string, { x: number; y: number }>();
  let rows = 0;
  g.lanes.forEach((lane, li) => {
    const inLane = g.nodes.filter((n) => n.lane === lane)
      .sort((a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind) || a.label.localeCompare(b.label));
    inLane.forEach((n, ri) => pos.set(n.id, { x: LEFT + li * COL, y: TOP + ri * ROW }));
    rows = Math.max(rows, inLane.length);
  });
  return { pos, width: LEFT + PAD + Math.max(1, g.lanes.length) * COL - (COL - W), height: TOP + rows * ROW + PAD };
}

function edgePath(a: { x: number; y: number }, b: { x: number; y: number }): { d: string; mx: number; my: number } {
  if (a.x === b.x) { // same lane: arc out to the left
    const x = a.x, y1 = a.y + H / 2, y2 = b.y + H / 2, bend = 28 + Math.min(40, Math.abs(y2 - y1) / 6);
    return { d: `M${x},${y1} C${x - bend},${y1} ${x - bend},${y2} ${x},${y2}`, mx: x - bend * 0.75, my: (y1 + y2) / 2 };
  }
  const leftToRight = a.x < b.x;
  const x1 = leftToRight ? a.x + W : a.x, x2 = leftToRight ? b.x : b.x + W;
  const y1 = a.y + H / 2, y2 = b.y + H / 2, dx = (x2 - x1) / 2;
  return { d: `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`, mx: (x1 + x2) / 2, my: (y1 + y2) / 2 };
}

export function ArchitectureDiagram({ graph, fresh = new Set<string>() }: { graph: Graph; fresh?: Set<string> }) {
  const { pos, width, height } = useMemo(() => layout(graph), [graph]);
  const [hover, setHover] = useState<string | null>(null);
  if (graph.nodes.length === 0) {
    return <div className="arch-empty" data-testid="arch-empty">Nothing built yet. Resources you create in the console or the AWS CLI appear here as you make them.</div>;
  }
  const related = (id: string) => hover === null || hover === id || graph.edges.some((e) => (e.source === hover && e.target === id) || (e.target === hover && e.source === id));
  return (
    <div className="arch-scroll">
      <svg className="arch" width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img"
        aria-label={`Architecture: ${graph.nodes.length} resources, ${graph.edges.length} connections`}>
        <defs><marker id="arch-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L8,4 L0,8 z" fill="#8b98b3" /></marker></defs>
        {graph.lanes.map((lane, i) => (
          <g key={lane}>
            <rect x={LEFT + i * COL - 10} y={4} width={W + 20} height={height - 8} rx={12} className="arch-lane" />
            <text x={LEFT + i * COL} y={22} className="arch-lane-label">{LANE_LABEL[lane] ?? lane}</text>
          </g>))}
        {graph.edges.map((e, i) => {
          const a = pos.get(e.source), b = pos.get(e.target);
          if (!a || !b) return null;
          const p = edgePath(a, b);
          const on = hover !== null && (hover === e.source || hover === e.target);
          return (
            <g key={i} className={on ? "arch-edge on" : hover ? "arch-edge dim" : "arch-edge"}>
              <path d={p.d} markerEnd="url(#arch-arrow)" />
              {on && <text x={p.mx} y={p.my - 4} textAnchor="middle" className="arch-edge-label">{e.kind}</text>}
            </g>);
        })}
        {graph.nodes.map((n) => {
          const p = pos.get(n.id)!;
          const svc = SERVICE[n.service] ?? { tag: n.service, color: "#5b6784" };
          return (
            <g key={n.id} transform={`translate(${p.x},${p.y})`} className={`arch-node ${n.state} ${fresh.has(n.id) ? "fresh" : ""} ${related(n.id) ? "" : "dim"}`}
              onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(n.id)} onBlur={() => setHover(null)}
              tabIndex={0} data-testid="arch-node" data-node={n.id}>
              <title>{`${KIND[n.kind] ?? n.kind} ${n.label}\n${n.detail}${n.flags.length ? `\n⚠ ${n.flags.join("; ")}` : ""}`}</title>
              <rect width={W} height={H} rx={9} className="arch-box" />
              <rect width={5} height={H} rx={2} fill={svc.color} />
              <text x={14} y={17} className="arch-kind">{svc.tag} · {KIND[n.kind] ?? n.kind}</text>
              <text x={14} y={36} className="arch-label">{n.label.length > 30 ? `${n.label.slice(0, 29)}…` : n.label}</text>
              <text x={14} y={52} className="arch-detail">{n.detail.length > 42 ? `${n.detail.slice(0, 41)}…` : n.detail}</text>
              {n.flags.length > 0 && <g transform={`translate(${W - 22},8)`}><circle r={8} cx={7} cy={7} className="arch-flag" /><text x={7} y={11} textAnchor="middle" className="arch-flag-text">!</text></g>}
            </g>);
        })}
      </svg>
      <style>{ARCH_CSS}</style>
    </div>
  );
}

/** Educational cost estimate. Always labelled as simulated, with the price-table version it used. */
export function CostMeter({ cost }: { cost: CostEstimate }) {
  const billable = cost.lines.filter((l) => Number(l.monthly) > 0 || l.note);
  return (
    <div className="cost" data-testid="cost-meter">
      <div className="cost-head">
        <span className="cost-tag">Simulated · educational</span>
        <div className="cost-figs">
          <span><strong className="score" data-testid="cost-hourly">${cost.hourly}</strong><span className="muted small"> / hour</span></span>
          <span><strong className="score" data-testid="cost-monthly">${cost.monthly}</strong><span className="muted small"> / month if left running</span></span>
        </div>
      </div>
      {billable.length > 0 && (
        <details className="cost-details"><summary className="small">What costs money</summary>
          <table className="data small"><thead><tr><th>Resource</th><th>Quantity</th><th>Rate</th><th>Per month</th></tr></thead>
            <tbody>{billable.map((l, i) => (
              <tr key={i}><td>{l.label}{l.note && <div className="muted">{l.note}</div>}</td>
                <td className="mono">{l.quantity} {l.unit}</td><td className="mono">${l.rate}</td><td className="mono">${l.monthly}</td></tr>))}</tbody>
          </table></details>)}
      {cost.lines.length === 0 && <p className="small" style={{ margin: "8px 0 0" }}>Nothing here costs money on its own: IAM users, groups, roles and policies,
        security groups and key pairs are free. Compute, storage and provisioned capacity are what you pay for.</p>}
      <p className="cost-note">{cost.disclaimer} Prices effective {cost.pricing_effective}.</p>
    </div>
  );
}

/** Live diagram for a running lab (polls while visible; the API caches snapshots for a few seconds). */
export function LiveArchitecture({ sessionId, active, children }: { sessionId: string; active: boolean; children?: (i: Insights | null) => React.ReactNode }) {
  const [data, setData] = useState<Insights | null>(null);
  const [fresh, setFresh] = useState<Set<string>>(new Set());
  const [note, setNote] = useState<string | null>(null);
  const known = useRef<Set<string> | null>(null);
  const load = useCallback(async () => {
    try {
      const r = await api<Insights>(`/api/sessions/${sessionId}/architecture`);
      const ids = new Set(r.graph.nodes.map((n) => n.id));
      if (known.current) {
        const added = new Set([...ids].filter((x) => !known.current!.has(x)));
        if (added.size) { setFresh(added); setTimeout(() => setFresh(new Set()), 2400); }
      }
      known.current = ids;
      setData(r); setNote(null);
    } catch (e) {
      setNote(e instanceof ApiError && e.code === "invalid_state" ? "The diagram updates while the lab is running." : "Couldn't read your sandbox just now. Retrying…");
    }
  }, [sessionId]);
  useEffect(() => {
    if (!active) return;
    void load();
    const t = setInterval(() => { if (document.visibilityState === "visible") void load(); }, 6000);
    return () => clearInterval(t);
  }, [active, load]);
  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="row between">
        <span className="small muted">Built from your sandbox&apos;s current state · updates every few seconds</span>
        <button className="small" onClick={() => void load()} disabled={!active}>Refresh</button>
      </div>
      {note && <div className="banner info small">{note}</div>}
      {children?.(data)}
      {data?.cost && <CostMeter cost={data.cost} />}
      {data ? <ArchitectureDiagram graph={data.graph} fresh={fresh} /> : !note && <p className="muted small">Reading your sandbox…</p>}
    </div>
  );
}

const ARCH_CSS = `
  .arch-scroll { overflow: auto; border: 1px solid var(--line); border-radius: var(--radius); background:
    radial-gradient(circle, #dfe6f1 1px, transparent 1px) 0 0 / 18px 18px, #fbfcfe; }
  .arch { display: block; font-family: var(--font-body); }
  .arch-lane { fill: rgba(255,255,255,.72); stroke: #e3e9f2; }
  .arch-lane-label { font: 600 10.5px var(--font-mono); letter-spacing: .08em; text-transform: uppercase; fill: var(--muted); }
  .arch-box { fill: #fff; stroke: #cfd8e6; }
  .arch-node { cursor: default; transition: opacity .15s; outline: none; }
  .arch-node:focus-visible .arch-box, .arch-node:hover .arch-box { stroke: var(--signal); stroke-width: 1.5; }
  .arch-node.warn .arch-box { stroke: #e2b454; }
  .arch-node.off { opacity: .6; }
  .arch-node.dim { opacity: .28; }
  .arch-node.fresh .arch-box { stroke: var(--signal); stroke-width: 2; animation: arch-in 2.4s ease-out; }
  @keyframes arch-in { 0% { stroke-width: 6; stroke-opacity: .9; } 100% { stroke-width: 2; stroke-opacity: 1; } }
  .arch-kind { font: 600 10px var(--font-mono); fill: var(--muted); letter-spacing: .02em; }
  .arch-label { font: 650 13.5px var(--font-body); fill: var(--ink); }
  .arch-detail { font: 11.5px var(--font-body); fill: var(--muted); }
  .arch-flag { fill: var(--warn); } .arch-flag-text { font: 700 11px var(--font-body); fill: #fff; }
  .arch-edge path { fill: none; stroke: #9aa7c0; stroke-width: 1.4; }
  .arch-edge.on path { stroke: var(--signal); stroke-width: 2; }
  .arch-edge.dim path { stroke-opacity: .25; }
  .arch-edge-label { font: 600 10.5px var(--font-body); fill: var(--signal-strong); paint-order: stroke; stroke: #fff; stroke-width: 4px; }
  .cost { border: 1px solid var(--line); border-radius: var(--radius); padding: 12px 14px; background: #fff; }
  .cost-head { display: flex; gap: 18px; align-items: center; flex-wrap: wrap; }
  .cost-tag { font: 600 10.5px var(--font-mono); letter-spacing: .08em; text-transform: uppercase; color: var(--warn);
    background: var(--warn-soft); border: 1px dashed #e2b454; padding: 4px 8px; border-radius: 6px; }
  .cost-figs { display: flex; gap: 22px; flex-wrap: wrap; } .cost-figs .score { font-size: 20px; }
  .cost-details { margin-top: 8px; } .cost-details table { margin-top: 6px; }
  .cost-note { margin: 8px 0 0; font-size: 12px; color: var(--muted); }
  .arch-empty { border: 1px dashed var(--line); border-radius: var(--radius); padding: 28px; text-align: center; color: var(--muted); background: #fbfcfe; }
  @media (prefers-reduced-motion: reduce) { .arch-node.fresh .arch-box { animation: none; } }
`;
