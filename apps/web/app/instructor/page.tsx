"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Shell } from "@/components/shell";
import { ErrorBanner } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";

type Course = { id: string; code: string; title: string; students: number;
  assignments: { id: string; title: string; due_at: string; close_at: string }[] };

export default function InstructorHome() {
  const [courses, setCourses] = useState<Course[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [creating, setCreating] = useState(false);
  const load = useCallback(() => api<{ courses: Course[] }>("/api/instructor/courses").then((r) => setCourses(r.courses)).catch(setError), []);
  useEffect(() => { void load(); }, [load]);
  return (
    <Shell>
      <div className="stack" style={{ gap: 20 }}>
        <div className="row between">
          <div><div className="eyebrow">Teaching</div><h1>Courses</h1></div>
          <button className="primary" onClick={() => setCreating(true)} data-testid="new-course">New course</button>
        </div>
        <ErrorBanner error={error} />
        {courses?.length === 0 && (
          <section className="card" data-testid="first-run">
            <h2>Your first run</h2>
            <p className="muted small" style={{ margin: "6px 0 0" }}>
              Four steps from an empty account to a graded class — all in the browser, no YAML, shell or
              developer tooling.
            </p>
            <ol className="stack" style={{ gap: 8, margin: "12px 0 0", paddingLeft: 20 }}>
              <li><strong>Create a course</strong> — choose <strong>New course</strong>; you are added as its instructor.</li>
              <li><strong>Import your roster</strong> — paste a CSV on the course page, preview it, then import.</li>
              <li><strong>Build a lab</strong> — <strong>Labs → New lab</strong>, pick a template, edit the generated forms, test and publish.</li>
              <li><strong>Assign it</strong> — <strong>New assignment</strong> on the course page; students see it in <em>My labs</em>.</li>
            </ol>
            <p className="small" style={{ margin: "12px 0 0" }}>
              <a href="https://github.com/ren0777/cloudsandbox/blob/main/docs/INSTRUCTOR-QUICKSTART.md"
                target="_blank" rel="noreferrer" data-testid="quickstart-link">Read the instructor quickstart →</a>
            </p>
          </section>
        )}
        {courses?.map((c) => (
          <section key={c.id} className="card" data-testid="course-card">
            <div className="row between">
              <h2><Link href={`/instructor/courses/${c.id}`} data-testid="course-link">{c.code} · {c.title}</Link></h2>
              <div className="row">
                <span className="pill">{c.students} students</span>
                <Link href={`/instructor/courses/${c.id}/live`} className="btn small">Live</Link>
                <Link href={`/instructor/courses/${c.id}/gradebook`} className="btn small">Gradebook</Link>
                <Link href={`/instructor/courses/${c.id}`} className="btn small">Roster &amp; labs</Link>
              </div>
            </div>
            <table className="data" style={{ marginTop: 12 }}>
              <thead><tr><th>Lab assignment</th><th>Due</th><th>Closes</th></tr></thead>
              <tbody>
                {c.assignments.length === 0 && <tr><td colSpan={3} className="muted">No labs assigned yet.</td></tr>}
                {c.assignments.map((a) => (
                  <tr key={a.id}>
                    <td><Link href={`/instructor/assignments/${a.id}`} data-testid="assignment-link">{a.title}</Link></td>
                    <td>{fmtDate(a.due_at)}</td><td>{fmtDate(a.close_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        ))}
      </div>
      {creating && <NewCourse onClose={(changed) => { setCreating(false); if (changed) void load(); }} />}
    </Shell>
  );
}

function NewCourse({ onClose }: { onClose: (changed: boolean) => void }) {
  const [code, setCode] = useState("");
  const [title, setTitle] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function save(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError(null);
    try { await api("/api/instructor/courses", { method: "POST", body: { code, title } }); onClose(true); } catch (err) { setError(err); } finally { setBusy(false); }
  }
  return (
    <div className="dialog-backdrop" role="dialog" aria-modal aria-labelledby="course-title" onClick={() => onClose(false)}>
      <form className="dialog stack" onClick={(e) => e.stopPropagation()} onSubmit={save}>
        <h2 id="course-title">New course</h2>
        <label>Course code<input required value={code} onChange={(e) => setCode(e.target.value)} placeholder="e.g. CS-341" maxLength={40} data-testid="course-code" /></label>
        <label>Title<input required value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Cloud Computing (Fall)" maxLength={200} data-testid="course-title" /></label>
        <p className="small muted" style={{ margin: 0 }}>You&apos;ll be added as the course instructor. Import the roster next.</p>
        <ErrorBanner error={error} />
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button type="button" onClick={() => onClose(false)}>Cancel</button>
          <button className="primary" disabled={busy} data-testid="course-save">Create course</button>
        </div>
      </form>
    </div>
  );
}
