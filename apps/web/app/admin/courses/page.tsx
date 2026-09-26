"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Shell } from "@/components/shell";
import { ErrorBanner } from "@/components/ui";
import { api } from "@/lib/api";

type C = { id: string; code: string; title: string; students: number; staff: { id: string; name: string; email: string }[] };

export default function AdminCourses() {
  const [courses, setCourses] = useState<C[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [adding, setAdding] = useState<Record<string, string>>({});
  const [creating, setCreating] = useState(false);
  const load = useCallback(() => api<{ courses: C[] }>("/api/admin/courses").then((r) => { setCourses(r.courses); setError(null); }).catch(setError), []);
  useEffect(() => { void load(); }, [load]);
  async function add(c: C) {
    try { await api(`/api/admin/courses/${c.id}/staff`, { method: "POST", body: { email: adding[c.id] ?? "" } }); setAdding({ ...adding, [c.id]: "" }); await load(); } catch (e) { setError(e); }
  }
  async function remove(c: C, s: C["staff"][number]) {
    if (!confirm(`Remove ${s.name} from ${c.code}? They lose access to its roster, gradebook and results.`)) return;
    try { await api(`/api/admin/courses/${c.id}/staff/${s.id}`, { method: "DELETE" }); await load(); } catch (e) { setError(e); }
  }
  return (
    <Shell>
      <div className="stack" style={{ gap: 18 }}>
        <div className="row between">
          <div><div className="eyebrow">Admin</div><h1>Courses and staff</h1>
            <p className="small muted" style={{ margin: "6px 0 0" }}>Instructors see and manage only the courses they teach.</p></div>
          <button className="primary" onClick={() => setCreating(true)} data-testid="admin-new-course">New course</button>
        </div>
        <ErrorBanner error={error} />
        <div className="card" style={{ padding: 0, overflowX: "auto" }}>
          <table className="data">
            <thead><tr><th>Course</th><th>Students</th><th>Instructors</th><th>Add instructor</th></tr></thead>
            <tbody>{courses.map((c) => (
              <tr key={c.id}>
                <td><Link href={`/instructor/courses/${c.id}`} style={{ fontWeight: 600 }}>{c.code}</Link><div className="small muted">{c.title}</div></td>
                <td className="score">{c.students}</td>
                <td className="small">{c.staff.length === 0 && <span className="muted">none</span>}
                  {c.staff.map((s) => <div key={s.id} className="row" style={{ gap: 6 }}>{s.name} <span className="muted">{s.email}</span>
                    <button className="small ghost danger" onClick={() => void remove(c, s)} aria-label={`Remove ${s.name}`}>Remove</button></div>)}</td>
                <td><form className="row" onSubmit={(e) => { e.preventDefault(); void add(c); }}>
                  <input type="email" required placeholder="instructor@college.edu" value={adding[c.id] ?? ""} style={{ width: 220 }}
                    onChange={(e) => setAdding({ ...adding, [c.id]: e.target.value })} aria-label={`Instructor email for ${c.code}`} />
                  <button className="small">Add</button></form></td>
              </tr>))}</tbody>
          </table>
        </div>
      </div>
      {creating && <NewCourse onClose={(changed) => { setCreating(false); if (changed) void load(); }} />}
    </Shell>
  );
}

function NewCourse({ onClose }: { onClose: (changed: boolean) => void }) {
  const [code, setCode] = useState("");
  const [title, setTitle] = useState("");
  const [instructor, setInstructor] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function save(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError(null);
    try {
      await api("/api/instructor/courses", { method: "POST", body: { code, title, instructor_email: instructor.trim() || null } });
      onClose(true);
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  return (
    <div className="dialog-backdrop" role="dialog" aria-modal aria-labelledby="nc-title" onClick={() => onClose(false)}>
      <form className="dialog stack" onClick={(e) => e.stopPropagation()} onSubmit={save}>
        <h2 id="nc-title">New course</h2>
        <label>Course code<input required maxLength={40} value={code} onChange={(e) => setCode(e.target.value)} placeholder="e.g. CS-341" data-testid="nc-code" /></label>
        <label>Title<input required maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Cloud Computing (Fall)" data-testid="nc-title" /></label>
        <label>Instructor email (optional)<input type="email" value={instructor} onChange={(e) => setInstructor(e.target.value)} placeholder="instructor@college.edu" data-testid="nc-instructor" />
          <span className="small muted" style={{ fontWeight: 400 }}>They must already have an instructor account (create one under <strong>Users</strong>). You can add more instructors later.</span></label>
        <ErrorBanner error={error} />
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button type="button" onClick={() => onClose(false)}>Cancel</button>
          <button className="primary" disabled={busy} data-testid="nc-save">Create course</button>
        </div>
      </form>
    </div>
  );
}
