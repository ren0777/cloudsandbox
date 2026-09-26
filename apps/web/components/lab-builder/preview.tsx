"use client";
import { useEffect, useState } from "react";
import { Markdown } from "@/components/markdown";
import { ErrorBanner } from "@/components/ui";
import { api } from "@/lib/api";
import type { Preview } from "@/lib/builder";

/** The draft exactly as a student sees it (the API's redacted student view: no checks, no private files). */
export function PreviewTab({ draftId, version }: { draftId: string; version: string }) {
  const [p, setP] = useState<Preview | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    let live = true;
    setError(null);
    api<Preview>(`/api/instructor/builder/drafts/${draftId}/preview`).then((r) => { if (live) setP(r); })
      .catch((e) => { if (live) { setP(null); setError(e); } });
    return () => { live = false; };
  }, [draftId, version]);
  if (error) return <ErrorBanner error={error} />;
  if (!p) return <p className="muted"><span className="spinner" /> Loading…</p>;
  const lab = p.lab;
  return (
    <div className="stack" style={{ gap: 16 }} data-testid="preview">
      <div className="banner info small"><div>Student view, with the variables of your own account. Checks and private files are never shown.</div></div>
      <div>
        <div className="eyebrow">{lab.services.map((s) => s.toUpperCase()).join(" · ")} · {lab.duration_minutes} min</div>
        <h2 style={{ fontSize: 26, marginTop: 4 }} data-testid="preview-title">{lab.title}</h2>
        {lab.summary && <p className="lede" style={{ margin: "6px 0 0" }}>{lab.summary}</p>}
      </div>
      <div className="card"><Markdown text={lab.story} /></div>
      <div className="card">
        <h3 style={{ marginBottom: 10 }}>What you&apos;ll do</h3>
        <ol className="lb-preview-tasks">
          {lab.tasks.map((t) => (
            <li key={t.id}>
              <div className="row between"><strong>{t.title}</strong><span className="mono muted small">{Number(t.marks)} marks</span></div>
              {t.description && <div className="small" style={{ marginTop: 4 }}><Markdown text={t.description} /></div>}
              {t.hints.length > 0 && (
                <details className="small" style={{ marginTop: 4 }}><summary>{t.hints.length} {t.hints.length === 1 ? "hint" : "hints"}</summary>
                  <ul>{t.hints.map((h, i) => <li key={i}>{h}</li>)}</ul></details>
              )}
            </li>
          ))}
        </ol>
      </div>
      {Object.keys(p.variables).length > 0 && (
        <table className="data">
          <thead><tr><th>Variable</th><th>Your value</th></tr></thead>
          <tbody>{Object.entries(p.variables).map(([k, v]) => <tr key={k}><td className="mono">{k}</td><td className="mono">{v}</td></tr>)}</tbody>
        </table>
      )}
    </div>
  );
}
