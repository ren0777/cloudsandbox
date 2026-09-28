"use client";
import { useEffect, useState } from "react";
import { ErrorBanner } from "@/components/ui";
import { api } from "@/lib/api";
import type { AttemptDiff, ChangeKind, DiffCheck } from "@/lib/types";

// "Since your last attempt": a comparison of two stored grades (M48). It never touches a sandbox, and the
// student's copy carries no expected/actual — the API has already redacted it (PLAN §7b).
const WORD: Record<ChangeKind, string> = {
  fixed: "Fixed", regressed: "Worse than last time", added: "New check", removed: "No longer checked",
  unchanged: "Unchanged",
};
const MARK: Record<ChangeKind, string> = { fixed: "✓", regressed: "✗", added: "＋", removed: "－", unchanged: "" };
const ORDER: ChangeKind[] = ["regressed", "fixed", "added", "removed"];

export function AttemptDiffPanel({ attemptId, staff = false }: { attemptId: string; staff?: boolean }) {
  const [d, setD] = useState<AttemptDiff | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    let live = true;
    const base = staff ? `/api/instructor/attempts/${attemptId}/diff` : `/api/attempts/${attemptId}/diff`;
    api<AttemptDiff>(base).then((r) => { if (live) setD(r); }).catch((e) => { if (live) setError(e); });
    return () => { live = false; };
  }, [attemptId, staff]);

  if (error) return <section className="card" data-testid="attempt-diff"><ErrorBanner error={error} /></section>;
  if (!d) return null;
  if (d.first_attempt) {
    return (
      <section className="card" data-testid="attempt-diff">
        <h2>Since your last attempt</h2>
        <p className="muted small" style={{ margin: "4px 0 0" }} data-testid="diff-first">
          This is your first attempt, so there&apos;s nothing to compare yet. Take another run at the lab and
          you&apos;ll see exactly what changed.
        </p>
      </section>
    );
  }

  const rows: (DiffCheck & { task: string })[] =
    d.tasks.flatMap((t) => t.checks.map((c) => ({ ...c, task: t.title })));
  const visible = rows.filter((r) => r.change !== "unchanged");
  const unchanged = rows.filter((r) => r.change === "unchanged");
  const s = d.summary;

  return (
    <section className="card stack" data-testid="attempt-diff">
      <div className="row between" style={{ flexWrap: "wrap", gap: 8 }}>
        <div>
          <h2 style={{ margin: 0 }}>Since attempt {d.previous?.attempt_no}</h2>
          <p className="small muted" style={{ margin: "4px 0 0" }}>
            {d.previous?.score} → {d.current.score} marks
            {d.current.regraded && " · this attempt has been regraded"}
          </p>
        </div>
        {s.delta && (
          <span className={`pill ${s.delta.startsWith("+") ? "pass" : "warn"}`} data-testid="diff-delta">
            {s.delta} marks
          </span>
        )}
      </div>

      <p className="small" style={{ margin: 0 }} data-testid="diff-counts">
        {s.fixed} fixed{s.regressed > 0 ? ` · ${s.regressed} worse` : ""}
        {s.added > 0 ? ` · ${s.added} new` : ""}{s.removed > 0 ? ` · ${s.removed} gone` : ""}
        {` · ${s.unchanged} unchanged`}
      </p>

      {visible.length === 0 ? (
        <p className="small muted" style={{ margin: 0 }} data-testid="diff-nothing">
          Nothing changed between these attempts.
        </p>
      ) : (
        <ul className="diff-list" data-testid="diff-list">
          {visible.map((r, i) => (
            <li key={`${r.check}-${i}`} className={`diff-row ${r.change}`} data-change={r.change}>
              <div className="row" style={{ gap: 8, alignItems: "baseline" }}>
                <span aria-hidden className="diff-mark">{MARK[r.change]}</span>
                <strong>{WORD[r.change]}</strong>
                <span className="small">{r.label}</span>
                {r.hidden && <span className="pill">Hidden check</span>}
              </div>
              <p className="small" style={{ margin: "2px 0 0 26px" }} data-testid="diff-detail">
                {r.before && <span className="diff-was">{r.before.message}</span>}
                {r.before && r.after && <span aria-hidden> → </span>}
                {r.after && <span>{r.after.message}</span>}
                {staff && (
                  <span className="mono muted small">
                    {r.before ? ` [was: ${show(r.before.expected)} / ${show(r.before.actual)}]` : ""}
                    {r.after ? ` [now: ${show(r.after.expected)} / ${show(r.after.actual)}]` : ""}
                  </span>
                )}
              </p>
            </li>
          ))}
        </ul>
      )}

      {unchanged.length > 0 && (
        <details className="small" data-testid="diff-unchanged">
          <summary>{unchanged.length} unchanged check{unchanged.length === 1 ? "" : "s"}</summary>
          <ul className="diff-list">
            {unchanged.map((r, i) => (
              <li key={`${r.check}-${i}`} className="diff-row unchanged">
                <div className="row" style={{ gap: 8, alignItems: "baseline" }}>
                  <span aria-hidden className="diff-mark">{MARK.unchanged}</span>
                  <span className="small">{r.label}</span>
                  {r.hidden && <span className="pill">Hidden check</span>}
                </div>
                <p className="small muted" style={{ margin: "2px 0 0 26px" }}>{r.after?.message}</p>
              </li>
            ))}
          </ul>
        </details>
      )}
      <style>{`
        .diff-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
        .diff-row { border-left: 3px solid var(--line); padding: 6px 0 6px 10px; }
        .diff-row.fixed { border-color: var(--pass); }
        .diff-row.regressed { border-color: var(--fail); }
        .diff-row.added, .diff-row.removed { border-color: var(--warn); }
        .diff-mark { width: 16px; display: inline-block; text-align: center; font-weight: 700; }
        .diff-row.fixed .diff-mark { color: var(--pass); }
        .diff-row.regressed .diff-mark { color: var(--fail); }
        .diff-was { text-decoration: line-through; opacity: .75; }
      `}</style>
    </section>
  );
}

const show = (v: unknown) => (v === undefined || v === null ? "—" : typeof v === "string" ? v : JSON.stringify(v));
