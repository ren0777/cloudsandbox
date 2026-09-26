"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ArchitectureDiagram, type Insights } from "@/components/architecture-diagram";
import { Shell } from "@/components/shell";
import { ErrorBanner } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate, TRIGGER_LABEL } from "@/lib/format";

type Check = { check: string; params: Record<string, unknown>; expected: unknown; actual: unknown; passed: boolean;
  hidden: boolean; message: string; marks_awarded: string; marks_possible: string };
type Detail = {
  attempt: { id: string; attempt_no: number; trigger: string; counts: boolean; late: boolean; score: string;
    max_score: string; grader_version: string; emulator_image_digest: string | null; variables: Record<string, string>;
    assignment_id: string; session_id: string; created_at: string };
  student: { name: string; email: string };
  tasks: { task_id: string; title: string; passed: boolean; marks_awarded: string; marks_possible: string; checks: Check[] }[];
  grades: { id: string; score: string; max_score: string; grader_version: string; reason: string; created_by: string | null; created_at: string }[];
  evidence: { final: { sha256: string; normalized_sha256: string; captured_at: string; payload: unknown } | null;
    baselines: { sha256: string; normalized_sha256: string; captured_at: string }[] };
  events: { from: string | null; to: string; reason: string | null; actor: string; request_id: string | null; at: string }[];
  insights: Insights | null;
};

const show = (v: unknown) => (typeof v === "string" ? v : JSON.stringify(v));

export default function AttemptEvidence() {
  const { id } = useParams<{ id: string }>();
  const [d, setD] = useState<Detail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => api<Detail>(`/api/instructor/attempts/${id}`).then(setD).catch(setError), [id]);
  useEffect(() => { void load(); }, [load]);

  async function regrade(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try { await api(`/api/instructor/attempts/${id}/regrade`, { method: "POST", body: { reason } }); setReason(""); await load(); }
    catch (err) { setError(err); } finally { setBusy(false); }
  }

  if (!d) return <Shell><ErrorBanner error={error} />{!error && <p className="muted">Loading…</p>}</Shell>;
  const current = d.grades[d.grades.length - 1];
  return (
    <Shell>
      <div className="stack" style={{ gap: 18 }}>
        <Link href={`/instructor/assignments/${d.attempt.assignment_id}`} className="small">← Results</Link>
        <div className="row between">
          <div>
            <div className="eyebrow">Attempt #{d.attempt.attempt_no} · {TRIGGER_LABEL[d.attempt.trigger]}{d.attempt.late ? " · late" : ""}{d.attempt.counts ? "" : " · not counted"}</div>
            <h1>{d.student.name}</h1>
            <p className="small muted" style={{ margin: "4px 0 0" }}>{d.student.email} · {fmtDate(d.attempt.created_at)}</p>
          </div>
          <div className="score" style={{ fontSize: 34 }} data-testid="instructor-score">{current?.score ?? d.attempt.score}<span className="muted small"> / {Number(d.attempt.max_score)}</span></div>
        </div>
        <ErrorBanner error={error} />

        <section className="card">
          <h2 style={{ marginBottom: 10 }}>Checks</h2>
          <table className="data">
            <thead><tr><th>Task</th><th>Check</th><th>Expected</th><th>Actual</th><th>Marks</th></tr></thead>
            <tbody>
              {d.tasks.flatMap((t) => t.checks.map((c, i) => (
                <tr key={`${t.task_id}-${i}`} data-testid="evidence-check">
                  <td>{i === 0 ? <strong>{t.title}</strong> : null}</td>
                  <td className="mono small">{c.check}{c.hidden && <span className="pill" style={{ marginLeft: 6 }}>hidden</span>}
                    <div className="muted">{Object.entries(c.params).map(([k, v]) => `${k}=${show(v)}`).join(" ")}</div></td>
                  <td className="mono small">{show(c.expected)}</td>
                  <td className="mono small" style={{ color: c.passed ? "var(--pass)" : "var(--fail)" }}>{c.passed ? "✓ " : "✗ "}{show(c.actual)}</td>
                  <td className="score">{c.marks_awarded}/{Number(c.marks_possible)}</td>
                </tr>
              )))}
            </tbody>
          </table>
        </section>

        <div className="two">
          <section className="card stack">
            <h2>Grade history</h2>
            <table className="data">
              <tbody>
                {d.grades.map((g) => (
                  <tr key={g.id}><td className="score">{g.score}</td><td className="small">{g.reason}{g.created_by ? " (regrade)" : ""}</td>
                    <td className="small muted">grader {g.grader_version} · {fmtDate(g.created_at)}</td></tr>
                ))}
              </tbody>
            </table>
            <form className="row" onSubmit={regrade}>
              <input className="grow" required minLength={3} value={reason} onChange={(e) => setReason(e.target.value)}
                placeholder="Reason for regrading" aria-label="Reason for regrading" />
              <button disabled={busy}>Regrade from stored evidence</button>
            </form>
            <p className="small muted" style={{ margin: 0 }}>Regrading re-runs the grader on the snapshot below. The original grade stays on record.</p>
          </section>
          <section className="card stack">
            <h2>Session timeline</h2>
            <ol className="timeline">
              {d.events.map((e, i) => (
                <li key={i}><span className="mono small">{e.to}</span> <span className="small muted">{e.reason} · {e.actor.split(":")[0]} · {new Date(e.at).toLocaleTimeString()}</span></li>
              ))}
            </ol>
          </section>
        </div>

        {d.insights && (
          <section className="card stack">
            <h2>Architecture at submission</h2>
            <ArchitectureDiagram graph={d.insights.graph} />
          </section>)}
        <section className="card stack">
          <h2>Graded snapshot</h2>
          <div className="small muted mono">sha256 {d.evidence.final?.sha256} · captured {fmtDate(d.evidence.final?.captured_at)} · emulator {d.attempt.emulator_image_digest?.slice(0, 19)}</div>
          <div className="small muted">Variables: {Object.entries(d.attempt.variables).map(([k, v]) => `${k}=${v}`).join(", ")}</div>
          <details><summary className="small">Show raw evidence</summary>
            <pre className="raw">{JSON.stringify(d.evidence.final?.payload, null, 2)}</pre></details>
        </section>
      </div>
      <style>{`
        .two { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
        .timeline { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 4px; }
        .raw { background: #0c1426; color: #cfe0ff; padding: 12px; border-radius: 8px; overflow: auto; max-height: 420px; font-size: 12px; }
        @media (max-width: 860px) { .two { grid-template-columns: 1fr; } }
      `}</style>
    </Shell>
  );
}
