"use client";
import { useCallback, useEffect, useState } from "react";
import { type RunnerView, RunnerFleet } from "@/components/runner-fleet";
import { Shell } from "@/components/shell";
import { ErrorBanner } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";

type Status = {
  server_time: string; database: { ok: boolean };
  runners: RunnerView[];
  sessions_by_state: Record<string, number>;
  provisioning_seconds: { samples: number; p50: number | null; p95: number | null };
  failures_24h: Record<string, number>;
};

type RunningSession = { session_id: string; state: string; runner_id: string; engine: string;
  student: { id: string; name: string; email: string }; course: { id: string; code: string }; assignment: { id: string; title: string };
  lab: string; created_at: string; ready_at: string | null; expires_at: string | null; last_activity_at: string | null };

const secs = (v: number | null) => (v === null ? "—" : `${v.toFixed(1)} s`);

export default function RuntimeStatus() {
  const [s, setS] = useState<Status | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [sessions, setSessions] = useState<RunningSession[]>([]);
  const load = useCallback(async () => {
    try {
      setS(await api<Status>("/api/admin/runtime-status"));
      setSessions((await api<{ sessions: RunningSession[] }>("/api/admin/sessions")).sessions);
      setError(null);
    } catch (e) { setError(e); }
  }, []);
  async function kill(x: RunningSession) {
    if (!confirm(`End ${x.student.name}'s lab now without grading? The sandbox is deleted and no attempt is used.`)) return;
    try { await api(`/api/admin/sessions/${x.session_id}/kill`, { method: "POST" }); await load(); } catch (e) { setError(e); }
  }
  async function extend(x: RunningSession) {
    const reason = prompt(`Add 15 minutes to ${x.student.name}'s lab. Reason (recorded in the audit log):`);
    if (!reason || reason.trim().length < 3) return;
    try { await api(`/api/instructor/sessions/${x.session_id}/extend`, { method: "POST", body: { minutes: 15, reason } }); await load(); } catch (e) { setError(e); }
  }
  useEffect(() => { void load(); const t = setInterval(load, 10000); return () => clearInterval(t); }, [load]);

  return (
    <Shell>
      <div className="stack" style={{ gap: 18 }}>
        <div className="row between">
          <div><div className="eyebrow">Admin</div><h1>Runtime status</h1></div>
          <span className="small muted">Refreshes every 10 s{s ? ` · ${new Date(s.server_time).toLocaleTimeString()}` : ""}</span>
        </div>
        <ErrorBanner error={error} onRetry={load} />
        {s && (
          <>
            <div className="grid">
              <div className="card"><div className="eyebrow">Database</div>
                <h2 style={{ marginTop: 6 }}><span className={`pill ${s.database.ok ? "pass" : "fail"}`}>{s.database.ok ? "Healthy" : "Unreachable"}</span></h2></div>
              <div className="card"><div className="eyebrow">Provisioning time (last hour)</div>
                <h2 style={{ marginTop: 6 }}>p50 {secs(s.provisioning_seconds.p50)} · p95 {secs(s.provisioning_seconds.p95)}</h2>
                <div className="small muted">{s.provisioning_seconds.samples} labs started</div></div>
              <div className="card"><div className="eyebrow">Active sessions</div>
                <h2 style={{ marginTop: 6 }}>{Object.values(s.sessions_by_state).reduce((a, b) => a + b, 0)}</h2>
                <div className="small muted">{Object.entries(s.sessions_by_state).map(([k, v]) => `${k.toLowerCase()} ${v}`).join(" · ") || "none"}</div></div>
            </div>
            <RunnerFleet runners={s.runners} onChange={load} />
            <section className="card">
              <h2 style={{ marginBottom: 10 }}>Running labs <span className="muted">({sessions.length})</span></h2>
              {sessions.length === 0 ? <p className="muted" style={{ margin: 0 }}>No labs are running.</p> : (
                <div style={{ overflowX: "auto" }}><table className="data">
                  <thead><tr><th>Student</th><th>Course · lab</th><th>State</th><th>Engine · runner</th><th>Ends</th><th /></tr></thead>
                  <tbody>{sessions.map((x) => (
                    <tr key={x.session_id} data-testid="admin-session-row">
                      <td><div style={{ fontWeight: 600 }}>{x.student.name}</div><div className="small muted">{x.student.email}</div></td>
                      <td className="small">{x.course.code} · {x.assignment.title}<div className="muted">{x.lab}</div></td>
                      <td><span className={`pill ${x.state === "READY" ? "pass" : "info"}`}>{x.state.toLowerCase()}</span></td>
                      <td className="small mono">{x.engine} · {x.runner_id}</td>
                      <td className="small">{fmtDate(x.expires_at)}</td>
                      <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                        {x.state === "READY" && <button className="small" onClick={() => void extend(x)}>+15 min</button>}{" "}
                        <button className="small danger" onClick={() => void kill(x)} data-testid="admin-kill">End</button></td>
                    </tr>))}</tbody>
                </table></div>)}
            </section>
            <section className="card">
              <h2 style={{ marginBottom: 10 }}>Session failures (last 24 h)</h2>
              {Object.keys(s.failures_24h).length === 0 ? <p className="muted" style={{ margin: 0 }}>No failures.</p> : (
                <table className="data"><tbody>
                  {Object.entries(s.failures_24h).map(([k, v]) => <tr key={k}><td className="mono">{k}</td><td className="score">{v}</td></tr>)}
                </tbody></table>
              )}
            </section>
          </>
        )}
      </div>
      <style>{`.meter { height: 6px; background: #e7ecf4; border-radius: 3px; margin-top: 6px; max-width: 160px; overflow: hidden; }
        .meter span { display: block; height: 100%; background: var(--signal); }`}</style>
    </Shell>
  );
}
