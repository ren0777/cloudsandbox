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
        {courses?.length === 0 && <div className="card flat muted">You aren&apos;t teaching any courses yet. Choose <strong>New course</strong> to start one.</div>}
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
