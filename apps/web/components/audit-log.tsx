"use client";
// Audit trail viewer (admin: everything; instructors: their course). Newest first, filter by action, paged.
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { ErrorBanner } from "./ui";

type Event = { id: number; at: string; action: string; actor: string | null; actor_role: string; course: string | null;
  subject: string | null; session_id: string | null; details: Record<string, unknown>; request_id: string | null };
type Page = { events: Event[]; next_before: number | null; actions: string[] };

const s = (v: unknown) => (v === null || v === undefined ? "" : String(v));
const list = (v: unknown) => (Array.isArray(v) ? v.length : 0);

function describe(e: Event): string {
  const d = e.details;
  const who = e.subject ?? s(d.email);
  switch (e.action) {
    case "course.created": return `Created course ${s(d.code)} "${s(d.title)}"`;
    case "course.staff_added": return `Added ${who} as course staff`;
    case "course.staff_removed": return `Removed ${who} from course staff`;
    case "roster.imported": return `Imported a roster: ${list(d.created)} new account(s), ${list(d.enrolled)} enrolled, ${s(d.already_enrolled)} already enrolled`;
    case "enrolment.added": return `Enrolled ${who}`;
    case "enrolment.removed": return `Removed ${who} from the course`;
    case "assignment.created": return `Created assignment "${s(d.title)}"`;
    case "assignment.updated": return `Changed assignment: ${Object.keys((d.changes as object) ?? {}).join(", ")}`;
    case "assignment.deleted": return `Deleted assignment "${s(d.title)}"`;
    case "deadline.extended": return `Extended ${who}'s closing time to ${fmtDate(s(d.close_at))}`;
    case "attempts.granted": return `Granted ${who} ${s(d.extra_attempts)} extra attempt(s)`;
    case "grade.regraded": return `Regraded ${who}'s attempt: ${s(d.previous_score)} → ${s(d.score)}`;
    case "session.terminated": return d.mode === "grade" ? `Ended ${who}'s lab and graded it (${s(d.score)})` : `Ended ${who}'s lab without grading`;
    case "session.extended": return `Gave ${who} ${s(d.added_minutes)} more minutes`;
    case "runner.registered": return `Registered runner ${s(d.runner_id)} at ${s(d.url)}`;
    case "runner.drained": return `Drained runner ${s(d.runner_id)} (${s(d.in_use) || 0} lab(s) still running)`;
    case "runner.resumed": return `Resumed runner ${s(d.runner_id)}`;
    case "runner.retired": return `Retired runner ${s(d.runner_id)}`;
    case "course.settings_changed": return `Changed course settings: ${Object.keys((d.changes as object) ?? {}).join(", ")}`;
    case "user.created": return `Created ${s(d.role)} account ${s(d.email)}`;
    case "user.role_changed": return `Changed ${who}'s role: ${s(d.previous)} → ${s(d.role)}`;
    case "user.deactivated": return `Deactivated ${who}`;
    case "user.reactivated": return `Reactivated ${who}`;
    case "user.password_reset": return `Reset ${who}'s password`;
    default: return e.action;
  }
}

export function AuditLog({ base, showCourse = true }: { base: string; showCourse?: boolean }) {
  const [events, setEvents] = useState<Event[]>([]);
  const [actions, setActions] = useState<string[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [action, setAction] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);
  const load = useCallback(async (before?: number) => {
    try {
      const qs = new URLSearchParams({ limit: "50" });
      if (action) qs.set("action", action);
      if (before) qs.set("before", String(before));
      const p = await api<Page>(`${base}?${qs}`);
      setEvents((cur) => (before ? [...cur, ...p.events] : p.events));
      setNext(p.next_before); setActions(p.actions); setError(null);
    } catch (e) { setError(e); }
  }, [base, action]);
  useEffect(() => { void load(); }, [load]);
  return (
    <div className="stack">
      <div className="row">
        <select value={action} onChange={(e) => setAction(e.target.value)} style={{ width: 240 }} aria-label="Filter by action">
          <option value="">All actions</option>{actions.map((a) => <option key={a}>{a}</option>)}</select>
        <button className="small" onClick={() => void load()}>Refresh</button>
      </div>
      <ErrorBanner error={error} />
      <div className="card" style={{ padding: 0, overflowX: "auto" }}>
        <table className="data">
          <thead><tr><th>When</th><th>Who</th><th>What</th>{showCourse && <th>Course</th>}<th /></tr></thead>
          <tbody>
            {events.length === 0 && <tr><td colSpan={5} className="muted">Nothing recorded yet.</td></tr>}
            {events.map((e) => (
              <FragmentRow key={e.id} e={e} showCourse={showCourse} open={open === e.id} toggle={() => setOpen(open === e.id ? null : e.id)} />))}
          </tbody>
        </table>
      </div>
      {next && <div><button className="small" onClick={() => void load(next)}>Load older</button></div>}
    </div>
  );
}

function FragmentRow({ e, showCourse, open, toggle }: { e: Event; showCourse: boolean; open: boolean; toggle: () => void }) {
  const reason = typeof e.details.reason === "string" && e.details.reason ? e.details.reason : null;
  return (
    <>
      <tr data-testid="audit-row">
        <td className="small" style={{ whiteSpace: "nowrap" }}>{fmtDate(e.at)}</td>
        <td className="small"><div style={{ fontWeight: 600 }}>{e.actor ?? "—"}</div><div className="muted">{e.actor_role}</div></td>
        <td className="small"><div>{describe(e)}</div>{reason && <div className="muted">Reason: {reason}</div>}<div className="mono muted" style={{ fontSize: 11 }}>{e.action}</div></td>
        {showCourse && <td className="small mono">{e.course ?? "—"}</td>}
        <td style={{ textAlign: "right" }}><button className="small ghost" onClick={toggle} aria-expanded={open}>{open ? "Hide" : "Details"}</button></td>
      </tr>
      {open && <tr><td colSpan={5}><pre className="mono small" style={{ margin: 0, whiteSpace: "pre-wrap", background: "#f7f9fc", padding: 10, borderRadius: 8 }}>
        {JSON.stringify({ ...e.details, session_id: e.session_id, request_id: e.request_id }, null, 2)}</pre></td></tr>}
    </>
  );
}
