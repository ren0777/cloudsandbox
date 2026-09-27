"use client";
// Admin runner fleet: health, load, host memory, engine images, drain (maintenance) and retire, registration.
import { useState } from "react";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { ErrorBanner } from "./ui";

export type RunnerView = { id: string; url: string; status: string; healthy: boolean; drain: boolean; safe_to_stop: boolean;
  in_use: number; max_sandboxes: number; sandboxes_on_host: number; engines: Record<string, boolean>; default_engine: string | null;
  version: string | null; cpu_count: number | null; mem_total_mib: number | null; mem_available_mib: number | null;
  last_heartbeat: string | null; unreachable_since: string | null; lost: boolean; last_error: string | null; own_secret: boolean };

const STATUS: Record<string, { label: string; pill: string }> = {
  healthy: { label: "Healthy", pill: "pass" }, unhealthy: { label: "Docker down", pill: "fail" }, unreachable: { label: "Unreachable", pill: "fail" },
  misconfigured: { label: "Wrong runner id", pill: "fail" }, unknown: { label: "Waiting for heartbeat", pill: "" }, retired: { label: "Retired", pill: "" } };

export function RunnerFleet({ runners, onChange }: { runners: RunnerView[]; onChange: () => Promise<void> }) {
  const [error, setError] = useState<unknown>(null);
  const [adding, setAdding] = useState(false);
  async function drain(r: RunnerView, on: boolean) {
    const reason = on ? prompt(`Drain ${r.id}? No new labs will start on it; the ${r.in_use} running lab(s) finish normally.\nReason (audit log):`) : "";
    if (on && reason === null) return;
    try { await api(`/api/admin/runners/${r.id}`, { method: "PATCH", body: { drain: on, reason: reason || null } }); await onChange(); } catch (e) { setError(e); }
  }
  async function retire(r: RunnerView) {
    if (!confirm(`Retire ${r.id}? It stops receiving heartbeats and labs. Register it again to bring it back.`)) return;
    try { await api(`/api/admin/runners/${r.id}`, { method: "DELETE" }); await onChange(); } catch (e) { setError(e); }
  }
  const total = runners.reduce((a, r) => a + (r.healthy && !r.drain ? r.max_sandboxes : 0), 0);
  const used = runners.reduce((a, r) => a + r.in_use, 0);
  return (
    <section className="card stack">
      <div className="row between">
        <div><h2>Runners</h2><p className="small muted" style={{ margin: "4px 0 0" }}>{used} lab seat{used === 1 ? "" : "s"} in use · {total} schedulable seats on healthy, non-draining runners.
          New labs go to the least-loaded compatible runner; running labs never move.</p></div>
        <button className="small" onClick={() => setAdding(true)} data-testid="register-runner">Register runner</button>
      </div>
      <ErrorBanner error={error} />
      <div style={{ overflowX: "auto" }}>
        <table className="data">
          <thead><tr><th>Runner</th><th>Status</th><th>Seats in use</th><th>Host</th><th>Engine images</th><th>Last heartbeat</th><th /></tr></thead>
          <tbody>
            {runners.map((r) => {
              const st = STATUS[r.status] ?? { label: r.status, pill: "" };
              return (
                <tr key={r.id} data-testid="runner-row">
                  <td><div className="mono" style={{ fontWeight: 600 }}>{r.id}</div><div className="small muted mono">{r.url}</div></td>
                  <td>
                    <span className={`pill ${st.pill}`}>{st.label}</span>{" "}
                    {r.drain && <span className="pill warn" data-testid="runner-draining">{r.safe_to_stop ? "Drained: safe to stop" : "Draining"}</span>}
                    {r.lost && <div className="small" style={{ color: "var(--fail)" }}>Lost: its labs were ended (runner_lost)</div>}
                    {r.last_error && <div className="small muted">{r.last_error}</div>}
                  </td>
                  <td><span className="score">{r.in_use}</span> / {r.max_sandboxes}
                    <div className="meter"><span style={{ width: `${Math.min(100, (r.in_use / Math.max(1, r.max_sandboxes)) * 100)}%` }} /></div></td>
                  <td className="small">{r.cpu_count ?? "?"} CPU · {r.mem_available_mib !== null && r.mem_total_mib !== null
                    ? `${(r.mem_available_mib / 1024).toFixed(1)} of ${(r.mem_total_mib / 1024).toFixed(1)} GiB free` : "memory unknown"}</td>
                  <td className="small">{Object.keys(r.engines).length === 0 ? <span className="muted">unknown</span> :
                    Object.entries(r.engines).map(([name, ok]) => (
                      <span key={name} className={`pill ${ok ? "pass" : "fail"}`} style={{ marginRight: 4 }} title={ok ? "images present" : "image missing"}>
                        {name}{name === r.default_engine ? " · default" : ""}</span>))}</td>
                  <td className="small">{fmtDate(r.last_heartbeat)}{r.unreachable_since && <div className="muted">unreachable since {fmtDate(r.unreachable_since)}</div>}</td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    {r.drain ? <button className="small" onClick={() => void drain(r, false)}>Resume</button>
                      : <button className="small" onClick={() => void drain(r, true)} data-testid="drain-runner">Drain</button>}
                    {r.drain && r.safe_to_stop && <>{" "}<button className="small danger" onClick={() => void retire(r)}>Retire</button></>}
                  </td>
                </tr>);
            })}
          </tbody>
        </table>
      </div>
      {adding && <RegisterRunner onClose={(changed) => { setAdding(false); if (changed) void onChange(); }} />}
    </section>
  );
}

function RegisterRunner({ onClose }: { onClose: (changed: boolean) => void }) {
  const [id, setId] = useState("");
  const [url, setUrl] = useState("http://");
  const [secret, setSecret] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function save(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError(null);
    try { await api("/api/admin/runners", { method: "POST", body: { id, url, secret } }); onClose(true); } catch (err) { setError(err); } finally { setBusy(false); }
  }
  return (
    <div className="dialog-backdrop" role="dialog" aria-modal aria-labelledby="rr-title" onClick={() => onClose(false)}>
      <form className="dialog stack" onClick={(e) => e.stopPropagation()} onSubmit={save} style={{ width: "min(520px, 100%)" }}>
        <h2 id="rr-title">Register a runner</h2>
        <p className="small muted" style={{ margin: 0 }}>Start the runner on its server first (see docs/DEPLOYMENT.md). Stackora contacts it with these
          settings and saves it only if it answers with the same id.</p>
        <label>Runner id<input required pattern="[a-z0-9][a-z0-9-]*" minLength={3} maxLength={64} value={id} onChange={(e) => setId(e.target.value)} placeholder="runner-lab2" className="mono" /></label>
        <label>URL (reachable from the API server only)<input required value={url} onChange={(e) => setUrl(e.target.value)} placeholder="http://10.0.0.12:7070" className="mono" /></label>
        <label>Runner secret (its RUNNER_SECRET)<input required type="password" minLength={16} value={secret} onChange={(e) => setSecret(e.target.value)} autoComplete="off" />
          <span className="small muted" style={{ fontWeight: 400 }}>Stored encrypted. Use a different random secret for every runner.</span></label>
        <ErrorBanner error={error} />
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button type="button" onClick={() => onClose(false)}>Cancel</button><button className="primary" disabled={busy}>{busy ? "Checking…" : "Register"}</button></div>
      </form>
    </div>
  );
}
