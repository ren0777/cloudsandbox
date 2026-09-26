"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { AssignmentDialog } from "@/components/assignment-dialog";
import { Shell } from "@/components/shell";
import { ErrorBanner } from "@/components/ui";
import { api } from "@/lib/api";
import { FAILURE_TEXT, fmtDate, TRIGGER_LABEL } from "@/lib/format";
import type { AttemptSummary } from "@/lib/types";

type Row = {
  user: { id: string; name: string; email: string; short_id: string };
  attempts: AttemptSummary[]; final_score: string | null; attempts_used: number; attempts_allowed: number;
  close_at: string; active_session: { id: string; state: string } | null;
  interrupted: { session_id: string; reason: string | null; at: string | null }[];
};
type Results = {
  assignment: { id: string; title: string; lab: string; lab_version: string; lab_version_id: string; course_id: string;
    allow_late: boolean; open_at: string; due_at: string; close_at: string; max_attempts: number; grade_policy: string; max_score: string };
  students: Row[];
};

export default function AssignmentResults() {
  const { id } = useParams<{ id: string }>();
  const [r, setR] = useState<Results | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [reopen, setReopen] = useState<Row | null>(null);
  const [editing, setEditing] = useState(false);
  const router = useRouter();
  const load = useCallback(() => api<Results>(`/api/instructor/assignments/${id}/results`).then(setR).catch(setError), [id]);
  useEffect(() => { void load(); }, [load]);

  if (!r) return <Shell><ErrorBanner error={error} onRetry={load} />{!error && <p className="muted">Loading…</p>}</Shell>;
  const a = r.assignment;

  async function remove() {
    if (!confirm(`Delete "${a.title}"? This is possible only while no student has started it.`)) return;
    try { await api(`/api/instructor/assignments/${a.id}`, { method: "DELETE" }); router.replace(`/instructor/courses/${a.course_id}`); } catch (e) { setError(e); }
  }

  return (
    <Shell>
      <div className="stack" style={{ gap: 18 }}>
        <ErrorBanner error={error} />
        <Link href={`/instructor/courses/${a.course_id}`} className="small">← Course</Link>
        <div className="row between">
          <div>
            <div className="eyebrow">{a.lab} · v{a.lab_version} · {a.grade_policy} score counts</div>
            <h1>{a.title}</h1>
            <p className="muted small" style={{ margin: "6px 0 0" }}>Due {fmtDate(a.due_at)} · closes {fmtDate(a.close_at)} · {a.max_attempts} attempts</p>
          </div>
          <div className="row">
            <button className="small" onClick={() => void load()}>Refresh</button>
            <a className="btn small" href={`/api/instructor/assignments/${a.id}/grades.csv`} data-testid="export-assignment">Export CSV</a>
            <button className="small" onClick={() => setEditing(true)} data-testid="edit-assignment">Edit</button>
            <button className="small danger" onClick={() => void remove()} data-testid="delete-assignment">Delete</button>
          </div>
        </div>
        <div className="card" style={{ padding: 0, overflowX: "auto" }}>
          <table className="data">
            <thead><tr><th>Student</th><th>Score</th><th>Attempts</th><th>Status</th><th /></tr></thead>
            <tbody>
              {r.students.map((s) => (
                <tr key={s.user.id} data-testid="result-row">
                  <td><div style={{ fontWeight: 600 }}>{s.user.name}</div><div className="small muted">{s.user.email}</div></td>
                  <td className="score" style={{ fontSize: 18 }}>{s.final_score ?? "—"}<span className="small muted"> / {Number(a.max_score)}</span></td>
                  <td>
                    <div className="small">{s.attempts_used} of {s.attempts_allowed} used</div>
                    <div className="row" style={{ gap: 6, marginTop: 4 }}>
                      {s.attempts.map((t) => (
                        <Link key={t.id} href={`/instructor/attempts/${t.id}`} className="pill info"
                          title={`${TRIGGER_LABEL[t.trigger]}${t.late ? " · late" : ""}${t.counts ? "" : " · not counted"}`}>
                          #{t.attempt_no}: {t.score}{t.regraded ? "*" : ""}
                        </Link>
                      ))}
                    </div>
                  </td>
                  <td className="small">
                    {s.active_session && <span className="pill pass">Working now</span>}
                    {s.interrupted.map((x) => (
                      <div key={x.session_id} className="interrupted">
                        <span className="pill fail">Interrupted</span> {FAILURE_TEXT[x.reason ?? ""] ?? x.reason} <span className="muted">{fmtDate(x.at)}</span>
                      </div>
                    ))}
                  </td>
                  <td style={{ textAlign: "right" }}><button className="small" onClick={() => setReopen(s)}>Reopen…</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {editing && <AssignmentDialog existing={a} onClose={(changed) => { setEditing(false); if (changed) void load(); }} />}
      {reopen && <ReopenDialog assignmentId={id} row={reopen} onClose={(changed) => { setReopen(null); if (changed) void load(); }} />}
      <style>{`.interrupted { margin-top: 4px; }`}</style>
    </Shell>
  );
}

function ReopenDialog({ assignmentId, row, onClose }: { assignmentId: string; row: Row; onClose: (changed: boolean) => void }) {
  const [extra, setExtra] = useState(1);
  const [until, setUntil] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api(`/api/instructor/assignments/${assignmentId}/overrides`, { method: "POST", body: {
        user_id: row.user.id, extra_attempts: extra, reason,
        close_at_override: until ? new Date(until).toISOString() : null } });
      onClose(true);
    } catch (err) { setError(err); } finally { setBusy(false); }
  }

  return (
    <div className="dialog-backdrop" role="dialog" aria-modal aria-labelledby="reopen-title" onClick={() => onClose(false)}>
      <form className="dialog stack" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h2 id="reopen-title">Reopen for {row.user.name}</h2>
        <p className="small muted" style={{ margin: 0 }}>Grants are permanent and recorded with your name and reason.</p>
        <label>Extra attempts<input type="number" min={0} max={10} value={extra} onChange={(e) => setExtra(Number(e.target.value))} /></label>
        <label>Extend closing time (optional)<input type="datetime-local" value={until} onChange={(e) => setUntil(e.target.value)} /></label>
        <label>Reason<input required minLength={3} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. sandbox crashed during class" /></label>
        <ErrorBanner error={error} />
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button type="button" onClick={() => onClose(false)}>Cancel</button>
          <button className="primary" disabled={busy || (extra === 0 && !until)}>Grant</button>
        </div>
      </form>
    </div>
  );
}
