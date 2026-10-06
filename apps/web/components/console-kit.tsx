"use client";
// Shared building blocks for the student cloud console (PLAN console fidelity principle).
import { useCallback, useRef, useState } from "react";
import { ApiError } from "@/lib/api";

export type Feature = { level: string; note?: string };
export type Notify = (kind: "fail" | "pass", text: string, ref?: string | null) => void;
export type Flash = { kind: "fail" | "pass"; text: string; ref?: string | null } | null;

export function useFlash() {
  const [flash, setFlash] = useState<Flash>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const notify: Notify = useCallback((kind, text, ref) => {
    setFlash({ kind, text, ref });
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setFlash(null), kind === "fail" ? 9000 : 5000);
  }, []);
  const fail = useCallback((e: unknown) => {
    if (e instanceof ApiError) notify("fail", `${e.extra.aws_code ? `${e.extra.aws_code}: ` : ""}${e.message}`, e.requestId);
    else notify("fail", "The console couldn't reach your sandbox. Try again.");
  }, [notify]);
  return { flash, notify, fail, clear: () => setFlash(null) };
}

export function FlashBanner({ flash, onClose }: { flash: Flash; onClose: () => void }) {
  if (!flash) return null;
  return (
    <div className={`banner ${flash.kind} console-flash`} role={flash.kind === "fail" ? "alert" : "status"}>
      <div className="grow small">{flash.text}{flash.ref && <div className="ref">ref: {flash.ref}</div>}</div>
      <button className="small ghost" onClick={onClose} aria-label="Dismiss">✕</button>
    </div>
  );
}

export function SimLabel({ note }: { note?: string }) {
  return <span className="pill warn sim-label" title={note}>Not available in Stackora simulator</span>;
}

export function fmtSize(n: number): string {
  return n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`;
}

export function TagRows({ tags, setTags }: { tags: { key: string; value: string }[]; setTags: (t: { key: string; value: string }[]) => void }) {
  return (
    <>
      {tags.length === 0 && <p className="help" style={{ margin: 0 }}>No tags associated with this resource.</p>}
      {tags.map((t, i) => (
        <div className="row" key={i}>
          <label style={{ flexDirection: "row", alignItems: "center" }}><span className="sr-only">Tag key</span>
            <input className="mono" style={{ width: 200 }} placeholder="Key" value={t.key} aria-label="Tag key"
              onChange={(e) => setTags(tags.map((x, j) => (j === i ? { ...x, key: e.target.value } : x)))} /></label>
          <label style={{ flexDirection: "row", alignItems: "center" }}><span className="sr-only">Tag value</span>
            <input className="mono" style={{ width: 240 }} placeholder="Value - optional" value={t.value} aria-label="Tag value"
              onChange={(e) => setTags(tags.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))} /></label>
          <button type="button" className="small" onClick={() => setTags(tags.filter((_, j) => j !== i))}>Remove</button>
        </div>
      ))}
      <div><button type="button" className="small" onClick={() => setTags([...tags, { key: "", value: "" }])} data-testid="add-tag">Add tag</button></div>
    </>
  );
}

export const CONSOLE_CSS = `
        .console { display: grid; grid-template-columns: 150px minmax(0, 1fr); height: 100%; background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; }
        .svc-nav { border-right: 1px solid var(--line); padding: 12px 6px; background: #f7f9fc; display: flex; flex-direction: column; gap: 2px; }
        .svc { justify-content: space-between; border: 0; background: transparent; padding: 8px 10px; width: 100%; flex-wrap: wrap; }
        .svc.active { background: var(--signal-soft); color: var(--signal-strong); }
        .svc .soon { font-size: 10px; font-weight: 500; color: var(--muted); }
        .svc-main { padding: 14px 18px 24px; overflow: auto; }
        .crumbs { display: flex; gap: 6px; align-items: center; color: var(--muted); margin-bottom: 10px; }
        .console-flash { margin-bottom: 12px; }
        .linklike { background: none; border: 0; padding: 0; color: var(--signal-strong); font-weight: 500; font-size: inherit; }
        .linklike:hover { text-decoration: underline; background: none !important; }
        .panel { border: 1px solid var(--line); border-radius: var(--radius); margin-bottom: 14px; }
        .panel-head { display: flex; align-items: center; gap: 10px; padding: 12px 14px; border-bottom: 1px solid var(--line); flex-wrap: wrap; }
        .panel-head h3 { flex: 1; }
        .panel-body { padding: 14px; display: flex; flex-direction: column; gap: 12px; }
        .panel.disabled { background: #fafbfd; }
        .panel.disabled h3 { color: var(--muted); }
        .kv { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
        .kv dt { font-size: 12px; color: var(--muted); } .kv dd { margin: 2px 0 0; font-size: 14px; word-break: break-all; }
        .help { font-size: 12px; color: var(--muted); font-weight: 400; }
        .choice { flex-direction: row; align-items: flex-start; gap: 8px; font-weight: 500; }
        .choice input { width: auto; margin-top: 3px; }
        .choice.off { color: var(--muted); }
        .sim-label { font-size: 11px; }
        .tabs { display: flex; gap: 2px; border-bottom: 1px solid var(--line); margin-bottom: 14px; flex-wrap: wrap; }
        .tab { border: 0; border-bottom: 2px solid transparent; border-radius: 0; background: transparent; padding: 8px 12px; color: var(--muted); }
        .tab.on { color: var(--ink); border-bottom-color: var(--signal); }
        .tab:hover { background: transparent !important; color: var(--ink); }
        .actions { display: flex; gap: 8px; justify-content: flex-end; }
        @media (max-width: 700px) { .console { grid-template-columns: 1fr; } .svc-nav { flex-direction: row; overflow-x: auto; } }
      `;
