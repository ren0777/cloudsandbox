"use client";
import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/components/auth";
import { Shell } from "@/components/shell";
import { ErrorBanner } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import type { Role } from "@/lib/types";

type U = { id: string; name: string; email: string; role: Role; short_id: string; active: boolean; must_change_password: boolean; created_at: string };

export default function AdminUsers() {
  const { me } = useAuth();
  const [users, setUsers] = useState<U[]>([]);
  const [totals, setTotals] = useState<Record<string, number>>({});
  const [q, setQ] = useState("");
  const [role, setRole] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [secret, setSecret] = useState<{ email: string; password: string } | null>(null);
  const [creating, setCreating] = useState(false);
  const load = useCallback(async () => {
    try {
      const qs = new URLSearchParams(); if (q) qs.set("q", q); if (role) qs.set("role", role);
      const r = await api<{ users: U[]; totals: Record<string, number> }>(`/api/admin/users?${qs}`);
      setUsers(r.users); setTotals(r.totals); setError(null);
    } catch (e) { setError(e); }
  }, [q, role]);
  useEffect(() => { const t = setTimeout(() => void load(), 250); return () => clearTimeout(t); }, [load]);

  async function patch(u: U, body: Record<string, unknown>, question: string) {
    const reason = prompt(`${question}\nReason (recorded in the audit log):`);
    if (reason === null) return;
    try { await api(`/api/admin/users/${u.id}`, { method: "PATCH", body: { ...body, reason: reason || null } }); await load(); } catch (e) { setError(e); }
  }
  async function reset(u: U) {
    if (!confirm(`Reset ${u.name}'s password? They will be signed out and must choose a new password with the temporary one.`)) return;
    try { const r = await api<{ temporary_password: string }>(`/api/admin/users/${u.id}/reset-password`, { method: "POST" });
      setSecret({ email: u.email, password: r.temporary_password }); await load(); } catch (e) { setError(e); }
  }

  return (
    <Shell>
      <div className="stack" style={{ gap: 18 }}>
        <div className="row between">
          <div><div className="eyebrow">Admin · {totals.student ?? 0} students · {totals.instructor ?? 0} instructors · {totals.admin ?? 0} admins</div><h1>Users</h1></div>
          <button className="primary" onClick={() => setCreating(true)} data-testid="new-user">New staff account</button>
        </div>
        <div className="row">
          <input placeholder="Search name, email or student ID" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 300 }} aria-label="Search users" />
          <select value={role} onChange={(e) => setRole(e.target.value)} style={{ width: 160 }} aria-label="Role">
            <option value="">All roles</option><option value="student">Students</option><option value="instructor">Instructors</option><option value="admin">Admins</option></select>
        </div>
        <ErrorBanner error={error} />
        {secret && <div className="banner warn" role="status" data-testid="temp-password">
          <div className="grow small">Temporary password for <strong>{secret.email}</strong>: <code>{secret.password}</code> — shown only now.</div>
          <button className="small" onClick={() => setSecret(null)}>Done</button></div>}
        <div className="card" style={{ padding: 0, overflowX: "auto" }}>
          <table className="data">
            <thead><tr><th>Name</th><th>Role</th><th>Status</th><th>Created</th><th /></tr></thead>
            <tbody>
              {users.length === 0 && <tr><td colSpan={5} className="muted">No users match.</td></tr>}
              {users.map((u) => (
                <tr key={u.id} data-testid="user-row">
                  <td><div style={{ fontWeight: 600 }}>{u.name}</div><div className="small muted">{u.email} · <span className="mono">{u.short_id}</span></div></td>
                  <td>
                    <select value={u.role} disabled={u.id === me?.id} style={{ width: 130 }} aria-label={`Role of ${u.name}`}
                      onChange={(e) => void patch(u, { role: e.target.value }, `Change ${u.name}'s role to ${e.target.value}?`)}>
                      <option value="student">student</option><option value="instructor">instructor</option><option value="admin">admin</option></select></td>
                  <td>{!u.active ? <span className="pill fail">Deactivated</span> : u.must_change_password ? <span className="pill warn">Awaiting first sign-in</span> : <span className="pill pass">Active</span>}</td>
                  <td className="small">{fmtDate(u.created_at)}</td>
                  <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                    {u.id !== me?.id && <>
                      <button className="small" onClick={() => void reset(u)}>Reset password</button>{" "}
                      {u.active
                        ? <button className="small danger" onClick={() => void patch(u, { active: false }, `Deactivate ${u.name}? They are signed out immediately.`)}>Deactivate</button>
                        : <button className="small" onClick={() => void patch(u, { active: true }, `Reactivate ${u.name}?`)}>Reactivate</button>}</>}
                  </td>
                </tr>))}
            </tbody>
          </table>
        </div>
        <p className="small muted" style={{ margin: 0 }}>Students are normally added by instructors through a roster import.</p>
      </div>
      {creating && <NewUser onClose={(r) => { setCreating(false); if (r) { setSecret(r); void load(); } }} />}
    </Shell>
  );
}

function NewUser({ onClose }: { onClose: (r: { email: string; password: string } | null) => void }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<Role>("instructor");
  const [error, setError] = useState<unknown>(null);
  async function save(e: React.FormEvent) {
    e.preventDefault();
    try { const r = await api<{ user: U; temporary_password: string }>("/api/admin/users", { method: "POST", body: { email, name, role } });
      onClose({ email: r.user.email, password: r.temporary_password }); } catch (err) { setError(err); }
  }
  return (
    <div className="dialog-backdrop" role="dialog" aria-modal aria-labelledby="nu-title" onClick={() => onClose(null)}>
      <form className="dialog stack" onClick={(e) => e.stopPropagation()} onSubmit={save}>
        <h2 id="nu-title">New account</h2>
        <label>Email<input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <label>Name<input required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label>Role<select value={role} onChange={(e) => setRole(e.target.value as Role)}>
          <option value="instructor">Instructor</option><option value="admin">Admin</option><option value="student">Student</option></select></label>
        <p className="small muted" style={{ margin: 0 }}>You&apos;ll get a temporary password to hand over. They must replace it at first sign-in.</p>
        <ErrorBanner error={error} />
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button type="button" onClick={() => onClose(null)}>Cancel</button><button className="primary">Create account</button></div>
      </form>
    </div>
  );
}
