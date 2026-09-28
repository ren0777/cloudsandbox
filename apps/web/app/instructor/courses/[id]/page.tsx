"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { AssignmentDialog } from "@/components/assignment-dialog";
import { Shell } from "@/components/shell";
import { ErrorBanner } from "@/components/ui";
import { api } from "@/lib/api";
import { downloadText, toCsv } from "@/lib/csv";
import { fmtDate } from "@/lib/format";

type Student = { id: string; name: string; email: string; short_id: string; active: boolean; pending_first_sign_in: boolean };
type Roster = { course: { id: string; code: string; title: string; leaderboard: "off" | "anonymous" | "named" }; students: Student[]; staff: { id: string; name: string; email: string }[] };
type CourseSummary = { id: string; assignments: { id: string; title: string; due_at: string; close_at: string }[] };
type PreviewRow = { row: number; email: string; name: string; status: "create" | "enrol" | "already_enrolled" | "error"; errors: string[]; warnings: string[] };
type Preview = { ok: boolean; file_errors: string[]; preview_token: string | null; rows: PreviewRow[];
  summary: { rows: number; create: number; enrol: number; already_enrolled: number; error: number } };
type Credential = { email: string; name: string; temporary_password: string };

const STATUS: Record<PreviewRow["status"], { label: string; pill: string }> = {
  create: { label: "New account", pill: "info" }, enrol: { label: "Enrol", pill: "pass" },
  already_enrolled: { label: "Already enrolled", pill: "" }, error: { label: "Error", pill: "fail" } };

export default function CoursePage() {
  const { id } = useParams<{ id: string }>();
  const [roster, setRoster] = useState<Roster | null>(null);
  const [assignments, setAssignments] = useState<CourseSummary["assignments"]>([]);
  const [error, setError] = useState<unknown>(null);
  const [newAssignment, setNewAssignment] = useState(false);
  const load = useCallback(async () => {
    try {
      setRoster(await api<Roster>(`/api/instructor/courses/${id}/roster`));
      const all = await api<{ courses: CourseSummary[] }>("/api/instructor/courses");
      setAssignments(all.courses.find((c) => c.id === id)?.assignments ?? []);
    } catch (e) { setError(e); }
  }, [id]);
  useEffect(() => { void load(); }, [load]);

  if (!roster) return <Shell><ErrorBanner error={error} onRetry={load} />{!error && <p className="muted">Loading…</p>}</Shell>;
  const c = roster.course;
  return (
    <Shell>
      <div className="stack" style={{ gap: 20 }}>
        <Link href="/instructor" className="small">← Courses</Link>
        <div className="row between">
          <div><div className="eyebrow">Course · {roster.staff.map((s) => s.name).join(", ") || "no staff"}</div><h1>{c.code} · {c.title}</h1></div>
          <div className="row">
            <Link href={`/instructor/courses/${id}/live`} className="btn small" data-testid="open-live">Live</Link>
            <Link href={`/instructor/courses/${id}/gradebook`} className="btn small" data-testid="open-gradebook">Gradebook</Link>
            <Link href={`/instructor/courses/${id}/analytics`} className="btn small" data-testid="open-analytics">Analytics</Link>
            <Link href={`/instructor/courses/${id}/audit`} className="btn small">Activity log</Link>
          </div>
        </div>
        <ErrorBanner error={error} />

        <section className="card stack">
          <div className="row between"><h2>Lab assignments</h2>
            <button className="small primary" onClick={() => setNewAssignment(true)} data-testid="new-assignment">New assignment</button></div>
          <table className="data">
            <thead><tr><th>Assignment</th><th>Due</th><th>Closes</th></tr></thead>
            <tbody>
              {assignments.length === 0 && <tr><td colSpan={3} className="muted">No labs assigned yet. Choose <strong>New assignment</strong>.</td></tr>}
              {assignments.map((a) => (
                <tr key={a.id}><td><Link href={`/instructor/assignments/${a.id}`} data-testid="assignment-link">{a.title}</Link></td>
                  <td>{fmtDate(a.due_at)}</td><td>{fmtDate(a.close_at)}</td></tr>))}
            </tbody>
          </table>
        </section>

        <LeaderboardSetting courseId={id} mode={c.leaderboard} onDone={load} />

        <RosterImport courseId={id} onDone={load} />

        <section className="card stack">
          <div className="row between"><h2>Students <span className="muted">({roster.students.length})</span></h2>
            <AddStudent courseId={id} onDone={load} /></div>
          <table className="data">
            <thead><tr><th>Name</th><th>Email</th><th>Student ID</th><th>Account</th><th /></tr></thead>
            <tbody>
              {roster.students.length === 0 && <tr><td colSpan={5} className="muted">No students yet. Import a roster CSV above.</td></tr>}
              {roster.students.map((s) => (
                <tr key={s.id} data-testid="roster-row">
                  <td style={{ fontWeight: 600 }}>{s.name}</td><td className="small">{s.email}</td><td className="mono small">{s.short_id}</td>
                  <td>{!s.active ? <span className="pill fail">Deactivated</span> : s.pending_first_sign_in
                    ? <span className="pill warn" title="Hasn't replaced the temporary password yet">Awaiting first sign-in</span>
                    : <span className="pill pass">Active</span>}</td>
                  <td style={{ textAlign: "right" }}><RemoveStudent courseId={id} student={s} onDone={load} onError={setError} /></td>
                </tr>))}
            </tbody>
          </table>
        </section>
      </div>
      {newAssignment && <AssignmentDialog courseId={id} onClose={(changed) => { setNewAssignment(false); if (changed) void load(); }} />}
    </Shell>
  );
}

function RosterImport({ courseId, onDone }: { courseId: string; onDone: () => Promise<void> }) {
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [creds, setCreds] = useState<Credential[] | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const base = `/api/instructor/courses/${courseId}/roster`;

  async function onFile(f: File | undefined) {
    if (!f) return;
    setFileName(f.name); setText(await f.text()); setPreview(null); setResult(null); setCreds(null);
  }
  async function runPreview() {
    setBusy(true); setError(null); setResult(null); setCreds(null);
    try { setPreview(await api<Preview>(`${base}/preview`, { method: "POST", body: { csv: text } })); } catch (e) { setError(e); } finally { setBusy(false); }
  }
  async function runImport() {
    if (!preview?.preview_token) return;
    setBusy(true); setError(null);
    try {
      const r = await api<{ created: number; enrolled: number; credentials: Credential[] }>(`${base}/import`,
        { method: "POST", body: { csv: text, preview_token: preview.preview_token } });
      setResult(`Imported: ${r.created} new account${r.created === 1 ? "" : "s"} created, ${r.enrolled} existing student${r.enrolled === 1 ? "" : "s"} enrolled.`);
      setCreds(r.credentials.length ? r.credentials : null);
      setPreview(null); setText(""); setFileName(null);
      await onDone();
    } catch (e) { setError(e); } finally { setBusy(false); }
  }
  const shown = preview?.rows.filter((r) => r.status === "error" || r.warnings.length) ?? [];
  return (
    <section className="card stack" data-testid="roster-import">
      <div><h2>Import roster</h2>
        <p className="small muted" style={{ margin: "4px 0 0" }}>A CSV file with a header row and the columns <code>email</code> and <code>name</code>.
          New emails get a student account with a temporary password; existing students are enrolled. Nothing changes until you choose <strong>Import</strong>.</p></div>
      <div className="row">
        <label className="btn small" style={{ flexDirection: "row", fontWeight: 600 }}>Choose CSV file
          <input type="file" accept=".csv,text/csv" className="sr-only" onChange={(e) => void onFile(e.target.files?.[0])} data-testid="roster-file" /></label>
        <span className="small muted">{fileName ?? "or paste the rows below"}</span>
      </div>
      <textarea className="mono" rows={4} value={text} placeholder={"email,name\nasha@college.edu,Asha Patel"} aria-label="Roster CSV"
        onChange={(e) => { setText(e.target.value); setPreview(null); }} data-testid="roster-text" />
      <div className="row"><button onClick={() => void runPreview()} disabled={!text.trim() || busy} data-testid="roster-preview">Preview</button></div>
      <ErrorBanner error={error} />
      {preview && (
        <div className="stack" data-testid="roster-preview-result">
          <div className="row">
            <span className="pill info">{preview.summary.create} new</span><span className="pill pass">{preview.summary.enrol} to enrol</span>
            <span className="pill">{preview.summary.already_enrolled} already enrolled</span>
            <span className={`pill ${preview.summary.error ? "fail" : ""}`} data-testid="roster-error-count">{preview.summary.error} with errors</span>
          </div>
          {preview.file_errors.map((e) => <div key={e} className="banner fail small" role="alert">{e}</div>)}
          {shown.length > 0 && (
            <table className="data">
              <thead><tr><th>Line</th><th>Email</th><th>Name</th><th>Result</th><th>Details</th></tr></thead>
              <tbody>{shown.map((r) => (
                <tr key={r.row} data-testid="roster-issue">
                  <td className="mono small">{r.row}</td><td className="small">{r.email || "—"}</td><td className="small">{r.name || "—"}</td>
                  <td><span className={`pill ${STATUS[r.status].pill}`}>{STATUS[r.status].label}</span></td>
                  <td className="small">{r.errors.map((e) => <div key={e} style={{ color: "var(--fail)" }}>{e}</div>)}
                    {r.warnings.map((w) => <div key={w} className="muted">{w}</div>)}</td>
                </tr>))}</tbody>
            </table>)}
          {preview.ok
            ? <div className="row"><button className="primary" onClick={() => void runImport()} disabled={busy} data-testid="roster-import-commit">
                Import {preview.summary.create + preview.summary.enrol} student{preview.summary.create + preview.summary.enrol === 1 ? "" : "s"}</button></div>
            : <div className="banner warn small">Fix the rows marked Error in your file, then preview it again. Nothing has been imported.</div>}
        </div>)}
      {result && <div className="banner pass small" role="status" data-testid="roster-result">{result}</div>}
      {creds && (
        <div className="banner warn" style={{ display: "block" }} data-testid="roster-credentials">
          <strong>Temporary passwords are shown only now.</strong>
          <p className="small" style={{ margin: "4px 0 8px" }}>Give each new student their password. They must choose their own at first sign-in.</p>
          <button className="small" onClick={() => downloadText("cloudlabs-new-accounts.csv", toCsv([["email", "name", "temporary_password"], ...creds.map((x) => [x.email, x.name, x.temporary_password])]))}
            data-testid="download-credentials">Download credentials CSV</button>
        </div>)}
    </section>
  );
}

function LeaderboardSetting({ courseId, mode, onDone }: { courseId: string; mode: Roster["course"]["leaderboard"]; onDone: () => Promise<void> }) {
  const [error, setError] = useState<unknown>(null);
  async function change(v: string) {
    try { await api(`/api/instructor/courses/${courseId}/settings`, { method: "PATCH", body: { leaderboard: v } }); await onDone(); } catch (e) { setError(e); }
  }
  return (
    <section className="card stack">
      <div className="row between">
        <div><h2>Class leaderboard</h2>
          <p className="small muted" style={{ margin: "4px 0 0" }}>Ranks students by XP earned from graded labs in this course. Off by default. Changes are recorded in the activity log.</p></div>
        <div className="row">
          <select value={mode} onChange={(e) => void change(e.target.value)} style={{ width: 260 }} aria-label="Leaderboard" data-testid="leaderboard-mode">
            <option value="off">Off</option>
            <option value="anonymous">On, with anonymous nicknames</option>
            <option value="named">On, with students&apos; names</option>
          </select>
          {mode !== "off" && <Link href={`/courses/${courseId}/leaderboard`} className="btn small">View</Link>}
        </div>
      </div>
      <ErrorBanner error={error} />
    </section>
  );
}

function AddStudent({ courseId, onDone }: { courseId: string; onDone: () => Promise<void> }) {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<unknown>(null);
  async function add(e: React.FormEvent) {
    e.preventDefault(); setError(null);
    try { await api(`/api/instructor/courses/${courseId}/enrolments`, { method: "POST", body: { email } }); setEmail(""); await onDone(); } catch (err) { setError(err); }
  }
  return (
    <form className="row" onSubmit={add}>
      <input type="email" required placeholder="student@college.edu" value={email} onChange={(e) => setEmail(e.target.value)} style={{ width: 240 }} aria-label="Existing student email" />
      <button className="small" type="submit">Enrol existing student</button>
      {error ? <div style={{ flexBasis: "100%" }}><ErrorBanner error={error} /></div> : null}
    </form>
  );
}

function RemoveStudent({ courseId, student, onDone, onError }: { courseId: string; student: Student; onDone: () => Promise<void>; onError: (e: unknown) => void }) {
  async function remove() {
    if (!confirm(`Remove ${student.name} from this course? Their attempts and results are kept.`)) return;
    try { await api(`/api/instructor/courses/${courseId}/enrolments/${student.id}`, { method: "DELETE" }); await onDone(); } catch (e) { onError(e); }
  }
  return <button className="small danger" onClick={() => void remove()}>Remove</button>;
}
