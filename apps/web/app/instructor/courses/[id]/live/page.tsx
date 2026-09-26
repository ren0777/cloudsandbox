"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Shell } from "@/components/shell";
import { ErrorBanner } from "@/components/ui";
import { api } from "@/lib/api";
import { FAILURE_TEXT, fmtDuration } from "@/lib/format";

type Task = { task_id: string; title: string; passed: boolean };
type LiveRow = { session_id: string; state: string; failure_reason: string | null;
  student: { id: string; name: string; email: string; short_id: string };
  assignment: { id: string; title: string; lab: string };
  started_at: string; expires_at: string | null; last_activity_at: string | null; idle_deadline_at: string | null;
  progress: { score: string; max_score: string; tasks: Task[] } | null; progress_at: string | null;
  tasks_total: number; tasks_passed: number | null };
type Live = { server_time: string; course: { id: string; code: string; title: string }; sessions: LiveRow[] };

const STATE_TEXT: Record<string, string> = { REQUESTED: "Starting", PROVISIONING: "Starting", READY: "Working",
  RESETTING: "Resetting", SUBMITTING: "Submitting", FAILED: "Interrupted" };
const POLL_MS = 10_000;

function ago(iso: string | null, now: number): string {
  if (!iso) return "never";
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  return s < 60 ? `${s}s ago` : s < 3600 ? `${Math.floor(s / 60)} min ago` : `${Math.floor(s / 3600)} h ago`;
}

export default function LiveProgress() {
  const { id } = useParams<{ id: string }>();
  const [live, setLive] = useState<Live | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [skew, setSkew] = useState(0);
  const [now, setNow] = useState(Date.now());
  const [acting, setActing] = useState<{ row: LiveRow; kind: "extend" | "end" } | null>(null);
  const [filter, setFilter] = useState("");
  const timer = useRef<ReturnType<typeof setInterval>>(undefined);
  const load = useCallback(async () => {
    try { const r = await api<Live>(`/api/instructor/courses/${id}/live`); setLive(r); setSkew(new Date(r.server_time).getTime() - Date.now()); setError(null); }
    catch (e) { setError(e); }
  }, [id]);
  useEffect(() => {
    void load();
    timer.current = setInterval(() => { if (document.visibilityState === "visible") void load(); }, POLL_MS);
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => { clearInterval(timer.current); clearInterval(tick); };
  }, [load]);
  const t = now + skew;
  const assignments = Array.from(new Map((live?.sessions ?? []).map((s) => [s.assignment.id, s.assignment.title])));
  const rows = (live?.sessions ?? []).filter((s) => !filter || s.assignment.id === filter);

  return (
    <Shell>
      <div className="stack" style={{ gap: 18 }}>
        <Link href={`/instructor/courses/${id}`} className="small">← {live?.course.code ?? "Course"}</Link>
        <div className="row between">
          <div><div className="eyebrow"><span className="live-dot" aria-hidden /> Live · updates every 10 s</div><h1>Students working now</h1></div>
          <div className="row">
            {assignments.length > 1 && (
              <select value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: 240 }} aria-label="Filter by lab">
                <option value="">All labs</option>{assignments.map(([aid, title]) => <option key={aid} value={aid}>{title}</option>)}</select>)}
            <button className="small" onClick={() => void load()}>Refresh</button>
          </div>
        </div>
        <ErrorBanner error={error} />
        <p className="small muted" style={{ margin: 0 }}>Task progress is each student&apos;s latest <strong>Check progress</strong> result. Watching never touches their sandbox.</p>
        {live && rows.length === 0 && <div className="card flat muted" data-testid="live-empty">Nobody is working on a lab in this course right now.</div>}
        <div className="stack" style={{ gap: 10 }}>
          {rows.map((r) => {
            const left = r.expires_at ? new Date(r.expires_at).getTime() - t : null;
            const idleLeft = r.idle_deadline_at ? new Date(r.idle_deadline_at).getTime() - t : null;
            const tasks = r.progress?.tasks ?? Array.from({ length: r.tasks_total }, (_, i) => ({ task_id: String(i), title: "Not checked yet", passed: false }));
            return (
              <article key={r.session_id} className="card live-row" data-testid="live-row">
                <div className="live-who">
                  <div style={{ fontWeight: 650 }}>{r.student.name}</div>
                  <div className="small muted">{r.assignment.title}</div>
                </div>
                <div className="live-progress">
                  <div className="strip" role="img" aria-label={r.progress ? `${r.tasks_passed} of ${r.tasks_total} tasks passing` : "No progress check yet"}>
                    {tasks.map((x) => <span key={x.task_id} className={x.passed ? "seg on" : "seg"} title={x.title} />)}
                  </div>
                  <div className="small muted" data-testid="live-progress">
                    {r.progress ? <><strong className="score" style={{ color: "var(--ink)" }}>{Number(r.progress.score)}</strong> / {Number(r.progress.max_score)} · {r.tasks_passed}/{r.tasks_total} tasks · checked {ago(r.progress_at, t)}</>
                      : "Hasn't checked progress yet"}
                  </div>
                </div>
                <div className="live-time small">
                  <span className={`pill ${r.state === "READY" ? "pass" : r.state === "FAILED" ? "fail" : "info"}`}>{STATE_TEXT[r.state] ?? r.state}</span>
                  {r.state === "FAILED" ? <div className="muted">{FAILURE_TEXT[r.failure_reason ?? ""] ?? r.failure_reason}</div> : <>
                    <div>{left !== null ? <>{fmtDuration(left)} left</> : "—"}</div>
                    <div className={idleLeft !== null && idleLeft < 5 * 60_000 ? "warn-text" : "muted"}>active {ago(r.last_activity_at, t)}</div></>}
                </div>
                <div className="live-actions">
                  {r.state === "READY" && <>
                    <button className="small" onClick={() => setActing({ row: r, kind: "extend" })} data-testid="live-extend">Extend</button>
                    <button className="small danger" onClick={() => setActing({ row: r, kind: "end" })} data-testid="live-end">End lab</button></>}
                </div>
              </article>);
          })}
        </div>
      </div>
      {acting && <ActionDialog {...acting} onClose={(changed) => { setActing(null); if (changed) void load(); }} />}
      <style>{`
        .live-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--pass); margin-right: 4px; animation: pulse 2s ease-in-out infinite; vertical-align: 1px; }
        @keyframes pulse { 50% { opacity: .35; } }
        .live-row { display: grid; grid-template-columns: minmax(160px, 1.1fr) minmax(200px, 2fr) minmax(130px, .9fr) auto; gap: 16px; align-items: center; padding: 14px 16px; }
        .strip { display: flex; gap: 3px; margin-bottom: 6px; }
        .strip .seg { flex: 1; height: 10px; border-radius: 3px; background: #e6ebf3; }
        .strip .seg.on { background: var(--pass); }
        .live-time { display: flex; flex-direction: column; gap: 3px; align-items: flex-start; }
        .warn-text { color: var(--warn); font-weight: 600; }
        .live-actions { display: flex; gap: 6px; justify-content: flex-end; }
        @media (max-width: 800px) { .live-row { grid-template-columns: 1fr; } .live-actions { justify-content: flex-start; } }
      `}</style>
    </Shell>
  );
}

function ActionDialog({ row, kind, onClose }: { row: LiveRow; kind: "extend" | "end"; onClose: (changed: boolean) => void }) {
  const [minutes, setMinutes] = useState(15);
  const [mode, setMode] = useState<"grade" | "discard">("grade");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError(null);
    try {
      if (kind === "extend") {
        const r = await api<{ added_minutes: number }>(`/api/instructor/sessions/${row.session_id}/extend`, { method: "POST", body: { minutes, reason } });
        setDone(r.added_minutes < minutes ? `Added ${r.added_minutes} minutes (the most allowed before the lab closes or reaches the time limit).` : null);
        if (r.added_minutes >= minutes) onClose(true);
      } else {
        await api(`/api/instructor/sessions/${row.session_id}/terminate`, { method: "POST", body: { mode, reason } });
        onClose(true);
      }
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  return (
    <div className="dialog-backdrop" role="dialog" aria-modal aria-labelledby="act-title" onClick={() => onClose(!!done)}>
      <form className="dialog stack" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h2 id="act-title">{kind === "extend" ? `Give ${row.student.name} more time` : `End ${row.student.name}'s lab`}</h2>
        {kind === "extend" ? (
          <label>Extra minutes<select value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} data-testid="extend-minutes">
            {[5, 10, 15, 30, 45, 60].map((m) => <option key={m} value={m}>{m} minutes</option>)}</select></label>
        ) : (
          <div className="stack" style={{ gap: 8 }}>
            <label className="choice-row"><input type="radio" checked={mode === "grade"} onChange={() => setMode("grade")} />
              <span><strong>Grade it now</strong><br /><span className="small muted">Submits the current work. It uses an attempt only if the student changed something.</span></span></label>
            <label className="choice-row"><input type="radio" checked={mode === "discard"} onChange={() => setMode("discard")} data-testid="end-discard" />
              <span><strong>End without grading</strong><br /><span className="small muted">Deletes the sandbox. No attempt is used and the work is lost.</span></span></label>
          </div>)}
        <label>Reason (recorded in the audit log)<input required minLength={3} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)}
          placeholder={kind === "extend" ? "e.g. network outage in lab 2" : "e.g. class ended"} data-testid="action-reason" /></label>
        {done && <div className="banner info small">{done}</div>}
        <ErrorBanner error={error} />
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button type="button" onClick={() => onClose(!!done)}>{done ? "Close" : "Cancel"}</button>
          {!done && <button className={kind === "end" ? "danger" : "primary"} disabled={busy || reason.trim().length < 3} data-testid="action-confirm">
            {busy ? "Working…" : kind === "extend" ? "Add time" : mode === "grade" ? "Grade and end" : "End without grading"}</button>}
        </div>
        <style>{`.choice-row { flex-direction: row; align-items: flex-start; gap: 8px; font-weight: 400; } .choice-row input { width: auto; margin-top: 4px; }`}</style>
      </form>
    </div>
  );
}
