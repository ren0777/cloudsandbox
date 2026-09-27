"use client";
// Student IAM console (PLAN console fidelity principle): User groups, Users, Roles, Policies and the
// Policy simulator, with AWS terminology and wizard workflows. Talks only to CloudLabs FastAPI endpoints.
// The simulator is evaluated by CloudLabs (support level `simulated`) and is labelled as such.
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { type Feature, FlashBanner, type Notify, SimLabel, useFlash } from "./console-kit";

type PolicyRef = { name: string; arn: string };
type PolicyRow = PolicyRef & { type: string; attachments: number };
type UserRow = { name: string; arn: string; groups: string[]; created_at: string | null };
type GroupRow = { name: string; arn: string; users: number; policies: number; created_at: string | null };
type RoleRow = { name: string; arn: string; trusted: string[]; created_at: string | null };
type Section = "groups" | "users" | "roles" | "policies" | "simulator";
type View = { section: Section; page: "list" | "create" | "detail"; name?: string };
type Ctx = { base: string; fail: (e: unknown) => void; notify: Notify; go: (v: View) => void; features: Record<string, Feature> };

const SECTIONS: [Section, string][] = [["groups", "User groups"], ["users", "Users"], ["roles", "Roles"],
  ["policies", "Policies"], ["simulator", "Policy simulator"]];
const POLICY_TEMPLATE = `{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [],
      "Resource": []
    }
  ]
}`;

export function IamConsole({ sessionId, readOnly, features }: { sessionId: string; readOnly: boolean; features: Record<string, Feature> }) {
  const base = `/api/sessions/${sessionId}/console/iam`;
  const [view, setView] = useState<View>({ section: "users", page: "list" });
  const { flash, notify, fail, clear } = useFlash();
  const ctx: Ctx = { base, fail, notify, go: setView, features };
  const label = SECTIONS.find(([s]) => s === view.section)![1];

  return (
    <section className="svc-main">
      <div className="crumbs small" aria-label="Breadcrumb">
        <button className="linklike" onClick={() => setView({ section: "users", page: "list" })}>IAM</button><span>›</span>
        <button className="linklike" onClick={() => setView({ section: view.section, page: "list" })}>{label}</button>
        {view.page === "create" && <><span>›</span><span>Create</span></>}
        {view.page === "detail" && <><span>›</span><span className="mono">{view.name}</span></>}
      </div>
      <FlashBanner flash={flash} onClose={clear} />
      {readOnly ? <div className="banner info">This lab is submitted or not running, so the console is read-only.</div> : (
        <>
          <div className="tabs" role="tablist" aria-label="Access management">
            {SECTIONS.map(([s, l]) => (
              <button key={s} role="tab" aria-selected={view.section === s} className={view.section === s ? "tab on" : "tab"}
                onClick={() => setView({ section: s, page: "list" })} data-testid={`iam-${s}`}>{l}</button>
            ))}
          </div>
          {view.section === "users" && (view.page === "list" ? <UserList {...ctx} /> : view.page === "create" ? <CreateUser {...ctx} /> : <UserDetail {...ctx} name={view.name!} />)}
          {view.section === "groups" && (view.page === "list" ? <GroupList {...ctx} /> : view.page === "create" ? <CreateGroup {...ctx} /> : <GroupDetail {...ctx} name={view.name!} />)}
          {view.section === "roles" && (view.page === "list" ? <RoleList {...ctx} /> : view.page === "create" ? <CreateRole {...ctx} /> : <RoleDetail {...ctx} name={view.name!} />)}
          {view.section === "policies" && (view.page === "list" ? <PolicyList {...ctx} /> : view.page === "create" ? <CreatePolicy {...ctx} /> : <PolicyDetail {...ctx} arn={view.name!} />)}
          {view.section === "simulator" && <Simulator {...ctx} />}
        </>
      )}
    </section>
  );
}

// ----------------------------------------------------------------------------------- shared bits
function usePolicies(base: string, fail: (e: unknown) => void, scope = "all", search = "") {
  const [policies, setPolicies] = useState<PolicyRow[] | null>(null);
  const load = useCallback(async () => {
    try { setPolicies((await api<{ policies: PolicyRow[] }>(`${base}/policies?scope=${scope}&search=${encodeURIComponent(search)}`)).policies); }
    catch (e) { fail(e); }
  }, [base, fail, scope, search]);
  useEffect(() => { void load(); }, [load]);
  return { policies, load };
}

function PolicyPicker({ base, fail, selected, onChange }: { base: string; fail: (e: unknown) => void; selected: string[]; onChange: (arns: string[]) => void }) {
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const { policies } = usePolicies(base, fail, "all", q);
  useEffect(() => { const t = setTimeout(() => setQ(search), 300); return () => clearTimeout(t); }, [search]);
  return (
    <div className="stack">
      <input placeholder="Filter policies by name" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Filter policies" style={{ maxWidth: 360 }} data-testid="policy-filter" />
      <div style={{ maxHeight: 260, overflow: "auto", border: "1px solid var(--line)", borderRadius: 8 }}>
        <table className="data">
          <thead><tr><th style={{ width: 36 }} /><th>Policy name</th><th>Type</th></tr></thead>
          <tbody>
            {policies?.length === 0 && <tr><td colSpan={3} className="muted">No policies match.</td></tr>}
            {policies?.map((p) => (
              <tr key={p.arn}>
                <td><input type="checkbox" style={{ width: "auto" }} aria-label={`Select ${p.name}`} checked={selected.includes(p.arn)}
                  onChange={(e) => onChange(e.target.checked ? [...selected, p.arn] : selected.filter((a) => a !== p.arn))} /></td>
                <td className="mono small">{p.name}</td><td className="small">{p.type}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <span className="help">{selected.length} selected</span>
    </div>
  );
}

function ListPanel({ title, count, onRefresh, action, children }: { title: string; count?: number; onRefresh: () => void; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="panel">
      <div className="panel-head"><h3>{title} <span className="muted">({count ?? "…"})</span></h3>
        <button className="small" onClick={onRefresh}>Refresh</button>{action}</div>
      <div className="panel-body" style={{ padding: 0 }}>{children}</div>
    </div>
  );
}

function Steps({ steps, at }: { steps: string[]; at: number }) {
  return (
    <ol className="wizard-steps">
      {steps.map((s, i) => <li key={s} className={i === at ? "now" : i < at ? "done" : ""}><span className="small muted">Step {i + 1}</span><br />{s}</li>)}
      <style>{`.wizard-steps { list-style: none; display: flex; gap: 18px; padding: 0; margin: 0 0 14px; flex-wrap: wrap; }
        .wizard-steps li { color: var(--muted); font-size: 14px; } .wizard-steps li.now { color: var(--ink); font-weight: 600; }
        .wizard-steps li.done { color: var(--pass); }`}</style>
    </ol>
  );
}

function AttachedPolicies({ ctx, kind, name, attached, reload }: { ctx: Ctx; kind: "users" | "groups" | "roles"; name: string; attached: PolicyRef[]; reload: () => Promise<void> }) {
  const [adding, setAdding] = useState(false);
  const [sel, setSel] = useState<string[]>([]);
  async function add() {
    try { for (const arn of sel) await api(`${ctx.base}/${kind}/${encodeURIComponent(name)}/policies`, { method: "POST", body: { arn } });
      setAdding(false); setSel([]); await reload(); ctx.notify("pass", "Policies attached."); } catch (e) { ctx.fail(e); }
  }
  async function detach(arn: string) {
    try { await api(`${ctx.base}/${kind}/${encodeURIComponent(name)}/policies?arn=${encodeURIComponent(arn)}`, { method: "DELETE" });
      await reload(); ctx.notify("pass", "Policy removed."); } catch (e) { ctx.fail(e); }
  }
  return (
    <div className="panel">
      <div className="panel-head"><h3>Permissions policies <span className="muted">({attached.length})</span></h3>
        {!adding && <button className="small primary" onClick={() => setAdding(true)} data-testid="add-permissions">Add permissions</button>}</div>
      <div className="panel-body">
        {adding ? (
          <>
            <PolicyPicker base={ctx.base} fail={ctx.fail} selected={sel} onChange={setSel} />
            <div className="actions"><button className="small" onClick={() => setAdding(false)}>Cancel</button>
              <button className="small primary" disabled={!sel.length} onClick={() => void add()} data-testid="attach-policies">Attach policies</button></div>
          </>
        ) : attached.length === 0 ? <p className="help" style={{ margin: 0 }}>No policies attached.</p> : (
          <table className="data"><thead><tr><th>Policy name</th><th /></tr></thead>
            <tbody>{attached.map((p) => (
              <tr key={p.arn}><td><button className="linklike mono" onClick={() => ctx.go({ section: "policies", page: "detail", name: p.arn })}>{p.name}</button></td>
                <td style={{ textAlign: "right" }}><button className="small danger" onClick={() => void detach(p.arn)}>Remove</button></td></tr>))}</tbody></table>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------------------------------ users
function UserList(ctx: Ctx) {
  const [users, setUsers] = useState<UserRow[] | null>(null);
  const load = useCallback(async () => { try { setUsers((await api<{ users: UserRow[] }>(`${ctx.base}/users`)).users); } catch (e) { ctx.fail(e); } }, [ctx.base, ctx.fail]);
  useEffect(() => { void load(); }, [load]);
  async function del(name: string) {
    if (!confirm(`Delete user ${name}?`)) return;
    try { await api(`${ctx.base}/users/${encodeURIComponent(name)}`, { method: "DELETE" }); await load(); ctx.notify("pass", `User ${name} deleted.`); } catch (e) { ctx.fail(e); }
  }
  return (
    <ListPanel title="Users" count={users?.length} onRefresh={() => void load()}
      action={<button className="small primary" onClick={() => ctx.go({ section: "users", page: "create" })} data-testid="open-create-user">Create user</button>}>
      <table className="data">
        <thead><tr><th>User name</th><th>Groups</th><th>Creation time</th><th /></tr></thead>
        <tbody>
          {users?.length === 0 && <tr><td colSpan={4} className="muted">No users. An IAM user is an identity for a person or an application.</td></tr>}
          {users?.map((u) => (
            <tr key={u.name}>
              <td><button className="linklike mono" onClick={() => ctx.go({ section: "users", page: "detail", name: u.name })}>{u.name}</button></td>
              <td className="small">{u.groups.join(", ") || "None"}</td><td className="small muted">{fmtDate(u.created_at)}</td>
              <td style={{ textAlign: "right" }}><button className="small danger" onClick={() => void del(u.name)}>Delete</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </ListPanel>
  );
}

function CreateUser(ctx: Ctx) {
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [mode, setMode] = useState<"group" | "direct">("group");
  const [groups, setGroups] = useState<GroupRow[]>([]);
  const [selGroups, setSelGroups] = useState<string[]>([]);
  const [selPolicies, setSelPolicies] = useState<string[]>([]);
  useEffect(() => { void api<{ groups: GroupRow[] }>(`${ctx.base}/groups`).then((r) => setGroups(r.groups)).catch(ctx.fail); }, [ctx.base, ctx.fail]);
  async function create() {
    try {
      await api(`${ctx.base}/users`, { method: "POST", body: { name, groups: mode === "group" ? selGroups : [], policy_arns: mode === "direct" ? selPolicies : [] } });
      ctx.notify("pass", `User ${name} created.`); ctx.go({ section: "users", page: "list" });
    } catch (e) { ctx.fail(e); }
  }
  return (
    <div>
      <h2 style={{ marginBottom: 10 }}>Create user</h2>
      <Steps steps={["Specify user details", "Set permissions", "Review and create"]} at={step} />
      {step === 0 && (
        <div className="panel"><div className="panel-head"><h3>User details</h3></div><div className="panel-body">
          <label>User name<input className="mono" value={name} onChange={(e) => setName(e.target.value)} style={{ maxWidth: 360 }} data-testid="new-user-name" />
            <span className="help">Up to 64 characters: letters, numbers and + = , . @ _ -</span></label>
          <div className="row small"><span className="muted">Provide user access to the AWS Management Console</span><SimLabel note="Console sign-in and access keys aren't issued in the simulator." /></div>
          <div className="actions"><button className="small" onClick={() => ctx.go({ section: "users", page: "list" })}>Cancel</button>
            <button className="small primary" disabled={!/^[\w+=,.@-]{1,64}$/.test(name)} onClick={() => setStep(1)} data-testid="wizard-next">Next</button></div>
        </div></div>
      )}
      {step === 1 && (
        <div className="panel"><div className="panel-head"><h3>Permissions options</h3></div><div className="panel-body">
          <label className="choice"><input type="radio" checked={mode === "group"} onChange={() => setMode("group")} /><span>Add user to group<br /><span className="help">Recommended: manage permissions by job function.</span></span></label>
          <label className="choice"><input type="radio" checked={mode === "direct"} onChange={() => setMode("direct")} data-testid="attach-directly" /><span>Attach policies directly</span></label>
          {mode === "group" ? (
            groups.length === 0 ? <p className="help">No user groups yet. Create one under <strong>User groups</strong>, or attach policies directly.</p> : (
              <table className="data"><thead><tr><th style={{ width: 36 }} /><th>Group name</th><th>Users</th><th>Attached policies</th></tr></thead>
                <tbody>{groups.map((g) => (
                  <tr key={g.name}><td><input type="checkbox" style={{ width: "auto" }} aria-label={`Select group ${g.name}`} checked={selGroups.includes(g.name)}
                    onChange={(e) => setSelGroups(e.target.checked ? [...selGroups, g.name] : selGroups.filter((x) => x !== g.name))} /></td>
                    <td className="mono small">{g.name}</td><td className="small">{g.users}</td><td className="small">{g.policies}</td></tr>))}</tbody></table>)
          ) : <PolicyPicker base={ctx.base} fail={ctx.fail} selected={selPolicies} onChange={setSelPolicies} />}
          <div className="actions"><button className="small" onClick={() => setStep(0)}>Previous</button>
            <button className="small primary" onClick={() => setStep(2)} data-testid="wizard-next">Next</button></div>
        </div></div>
      )}
      {step === 2 && (
        <div className="panel"><div className="panel-head"><h3>Review and create</h3></div><div className="panel-body">
          <dl className="kv" style={{ margin: 0 }}>
            <div><dt>User name</dt><dd className="mono">{name}</dd></div>
            <div><dt>{mode === "group" ? "Groups" : "Permissions policies"}</dt><dd className="small">{(mode === "group" ? selGroups : selPolicies.map((a) => a.split("/").pop())).join(", ") || "None"}</dd></div>
          </dl>
          <div className="actions"><button className="small" onClick={() => setStep(1)}>Previous</button>
            <button className="small primary" onClick={() => void create()} data-testid="create-user">Create user</button></div>
        </div></div>
      )}
    </div>
  );
}

function UserDetail({ name, ...ctx }: Ctx & { name: string }) {
  const [u, setU] = useState<{ arn: string; groups: string[]; attached: PolicyRef[]; inline: string[] } | null>(null);
  const [allGroups, setAllGroups] = useState<string[]>([]);
  const [editGroups, setEditGroups] = useState<string[] | null>(null);
  const load = useCallback(async () => { try { setU(await api(`${ctx.base}/users/${encodeURIComponent(name)}`)); } catch (e) { ctx.fail(e); } }, [ctx.base, name]);
  useEffect(() => { void load(); void api<{ groups: GroupRow[] }>(`${ctx.base}/groups`).then((r) => setAllGroups(r.groups.map((g) => g.name))).catch(() => undefined); }, [load, ctx.base]);
  async function saveGroups() {
    try { await api(`${ctx.base}/users/${encodeURIComponent(name)}/groups`, { method: "PUT", body: { groups: editGroups } }); setEditGroups(null); await load(); ctx.notify("pass", "Group memberships updated."); }
    catch (e) { ctx.fail(e); }
  }
  if (!u) return null;
  return (
    <div>
      <h2 className="mono" style={{ fontSize: 20, marginBottom: 10 }}>{name}</h2>
      <div className="panel"><div className="panel-head"><h3>Summary</h3></div><div className="panel-body"><dl className="kv" style={{ margin: 0 }}><div><dt>ARN</dt><dd className="mono small">{u.arn}</dd></div></dl></div></div>
      <AttachedPolicies ctx={ctx} kind="users" name={name} attached={u.attached} reload={load} />
      <div className="panel"><div className="panel-head"><h3>Groups <span className="muted">({u.groups.length})</span></h3>
        {editGroups === null && <button className="small" onClick={() => setEditGroups(u.groups)} data-testid="edit-user-groups">Add user to groups</button>}</div>
        <div className="panel-body">
          {editGroups !== null ? (
            <>
              {allGroups.map((g) => <label key={g} className="choice"><input type="checkbox" checked={editGroups.includes(g)} aria-label={`Group ${g}`}
                onChange={(e) => setEditGroups(e.target.checked ? [...editGroups, g] : editGroups.filter((x) => x !== g))} /><span className="mono small">{g}</span></label>)}
              <div className="actions"><button className="small" onClick={() => setEditGroups(null)}>Cancel</button>
                <button className="small primary" onClick={() => void saveGroups()}>Save changes</button></div>
            </>
          ) : <p className="small" style={{ margin: 0 }}>{u.groups.join(", ") || "This user isn't in any group."}</p>}
        </div></div>
      {u.inline.length > 0 && <div className="panel"><div className="panel-head"><h3>Inline policies</h3></div><div className="panel-body mono small">{u.inline.join(", ")}</div></div>}
    </div>
  );
}

// ----------------------------------------------------------------------------------------- groups
function GroupList(ctx: Ctx) {
  const [groups, setGroups] = useState<GroupRow[] | null>(null);
  const load = useCallback(async () => { try { setGroups((await api<{ groups: GroupRow[] }>(`${ctx.base}/groups`)).groups); } catch (e) { ctx.fail(e); } }, [ctx.base, ctx.fail]);
  useEffect(() => { void load(); }, [load]);
  async function del(name: string) {
    if (!confirm(`Delete group ${name}?`)) return;
    try { await api(`${ctx.base}/groups/${encodeURIComponent(name)}`, { method: "DELETE" }); await load(); ctx.notify("pass", `Group ${name} deleted.`); } catch (e) { ctx.fail(e); }
  }
  return (
    <ListPanel title="User groups" count={groups?.length} onRefresh={() => void load()}
      action={<button className="small primary" onClick={() => ctx.go({ section: "groups", page: "create" })} data-testid="open-create-group">Create group</button>}>
      <table className="data">
        <thead><tr><th>Group name</th><th>Users</th><th>Permissions</th><th>Creation time</th><th /></tr></thead>
        <tbody>
          {groups?.length === 0 && <tr><td colSpan={5} className="muted">No user groups. A user group is a collection of users that share permissions.</td></tr>}
          {groups?.map((g) => (
            <tr key={g.name}>
              <td><button className="linklike mono" onClick={() => ctx.go({ section: "groups", page: "detail", name: g.name })}>{g.name}</button></td>
              <td className="small">{g.users}</td><td className="small">{g.policies ? `${g.policies} policies` : "Not defined"}</td>
              <td className="small muted">{fmtDate(g.created_at)}</td>
              <td style={{ textAlign: "right" }}><button className="small danger" onClick={() => void del(g.name)}>Delete</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </ListPanel>
  );
}

function CreateGroup(ctx: Ctx) {
  const [name, setName] = useState("");
  const [sel, setSel] = useState<string[]>([]);
  async function create(e: React.FormEvent) {
    e.preventDefault();
    try { await api(`${ctx.base}/groups`, { method: "POST", body: { name, policy_arns: sel } }); ctx.notify("pass", `User group ${name} created.`); ctx.go({ section: "groups", page: "list" }); }
    catch (err) { ctx.fail(err); }
  }
  return (
    <form onSubmit={create}>
      <h2 style={{ marginBottom: 12 }}>Create user group</h2>
      <div className="panel"><div className="panel-head"><h3>Name the group</h3></div><div className="panel-body">
        <label>User group name<input className="mono" required pattern="[\w+=,.@\-]{1,64}" value={name} onChange={(e) => setName(e.target.value)} style={{ maxWidth: 360 }} data-testid="new-group-name" /></label>
      </div></div>
      <div className="panel"><div className="panel-head"><h3>Attach permissions policies <span className="help">- optional</span></h3></div>
        <div className="panel-body"><PolicyPicker base={ctx.base} fail={ctx.fail} selected={sel} onChange={setSel} /></div></div>
      <div className="actions"><button type="button" onClick={() => ctx.go({ section: "groups", page: "list" })}>Cancel</button>
        <button className="primary" data-testid="create-group">Create user group</button></div>
    </form>
  );
}

function GroupDetail({ name, ...ctx }: Ctx & { name: string }) {
  const [g, setG] = useState<{ arn: string; users: string[]; attached: PolicyRef[] } | null>(null);
  const load = useCallback(async () => { try { setG(await api(`${ctx.base}/groups/${encodeURIComponent(name)}`)); } catch (e) { ctx.fail(e); } }, [ctx.base, name]);
  useEffect(() => { void load(); }, [load]);
  if (!g) return null;
  return (
    <div>
      <h2 className="mono" style={{ fontSize: 20, marginBottom: 10 }}>{name}</h2>
      <div className="panel"><div className="panel-head"><h3>Users in this group <span className="muted">({g.users.length})</span></h3></div>
        <div className="panel-body small">{g.users.join(", ") || "No users. Add users from their Users page."}</div></div>
      <AttachedPolicies ctx={ctx} kind="groups" name={name} attached={g.attached} reload={load} />
    </div>
  );
}

// ------------------------------------------------------------------------------------------ roles
function RoleList(ctx: Ctx) {
  const [roles, setRoles] = useState<RoleRow[] | null>(null);
  const load = useCallback(async () => { try { setRoles((await api<{ roles: RoleRow[] }>(`${ctx.base}/roles`)).roles); } catch (e) { ctx.fail(e); } }, [ctx.base, ctx.fail]);
  useEffect(() => { void load(); }, [load]);
  async function del(name: string) {
    if (!confirm(`Delete role ${name}?`)) return;
    try { await api(`${ctx.base}/roles/${encodeURIComponent(name)}`, { method: "DELETE" }); await load(); ctx.notify("pass", `Role ${name} deleted.`); } catch (e) { ctx.fail(e); }
  }
  return (
    <ListPanel title="Roles" count={roles?.length} onRefresh={() => void load()}
      action={<button className="small primary" onClick={() => ctx.go({ section: "roles", page: "create" })} data-testid="open-create-role">Create role</button>}>
      <table className="data">
        <thead><tr><th>Role name</th><th>Trusted entities</th><th>Creation time</th><th /></tr></thead>
        <tbody>
          {roles?.length === 0 && <tr><td colSpan={4} className="muted">No roles. A role is an identity that AWS services or users can assume.</td></tr>}
          {roles?.map((r) => (
            <tr key={r.name}>
              <td><button className="linklike mono" onClick={() => ctx.go({ section: "roles", page: "detail", name: r.name })}>{r.name}</button></td>
              <td className="small">{r.trusted.map((t) => `AWS Service: ${t.split(".")[0]}`).join(", ") || "-"}</td>
              <td className="small muted">{fmtDate(r.created_at)}</td>
              <td style={{ textAlign: "right" }}><button className="small danger" onClick={() => void del(r.name)}>Delete</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </ListPanel>
  );
}

function CreateRole(ctx: Ctx) {
  const [step, setStep] = useState(0);
  const [service, setService] = useState<"lambda" | "ec2">("lambda");
  const [sel, setSel] = useState<string[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  async function create() {
    try { await api(`${ctx.base}/roles`, { method: "POST", body: { name, service, policy_arns: sel, description } }); ctx.notify("pass", `Role ${name} created.`); ctx.go({ section: "roles", page: "list" }); }
    catch (e) { ctx.fail(e); }
  }
  return (
    <div>
      <h2 style={{ marginBottom: 10 }}>Create role</h2>
      <Steps steps={["Select trusted entity", "Add permissions", "Name, review, and create"]} at={step} />
      {step === 0 && (
        <div className="panel"><div className="panel-head"><h3>Trusted entity type</h3></div><div className="panel-body">
          <label className="choice"><input type="radio" checked readOnly /><span>AWS service<br /><span className="help">Allow AWS services like EC2 or Lambda to perform actions in this account.</span></span></label>
          {["AWS account", "Web identity", "SAML 2.0 federation", "Custom trust policy"].map((t) => (
            <label key={t} className="choice off"><input type="radio" disabled /><span>{t} <SimLabel /></span></label>))}
          <label>Use case
            <select value={service} onChange={(e) => setService(e.target.value as "lambda" | "ec2")} style={{ maxWidth: 240 }} data-testid="role-service">
              <option value="lambda">Lambda</option><option value="ec2">EC2</option></select></label>
          <div className="actions"><button className="small" onClick={() => ctx.go({ section: "roles", page: "list" })}>Cancel</button>
            <button className="small primary" onClick={() => setStep(1)} data-testid="wizard-next">Next</button></div>
        </div></div>
      )}
      {step === 1 && (
        <div className="panel"><div className="panel-head"><h3>Permissions policies</h3></div><div className="panel-body">
          <PolicyPicker base={ctx.base} fail={ctx.fail} selected={sel} onChange={setSel} />
          <div className="actions"><button className="small" onClick={() => setStep(0)}>Previous</button>
            <button className="small primary" onClick={() => setStep(2)} data-testid="wizard-next">Next</button></div>
        </div></div>
      )}
      {step === 2 && (
        <div className="panel"><div className="panel-head"><h3>Role details</h3></div><div className="panel-body">
          <label>Role name<input className="mono" value={name} onChange={(e) => setName(e.target.value)} style={{ maxWidth: 360 }} data-testid="new-role-name" /></label>
          <label>Description<input value={description} onChange={(e) => setDescription(e.target.value)} style={{ maxWidth: 520 }} /></label>
          <div className="small">Trusted entity: <span className="mono">{service}.amazonaws.com</span> · Permissions: {sel.length}</div>
          <div className="actions"><button className="small" onClick={() => setStep(1)}>Previous</button>
            <button className="small primary" disabled={!/^[\w+=,.@-]{1,64}$/.test(name)} onClick={() => void create()} data-testid="create-role">Create role</button></div>
        </div></div>
      )}
    </div>
  );
}

function RoleDetail({ name, ...ctx }: Ctx & { name: string }) {
  const [r, setR] = useState<{ arn: string; description: string; trust: unknown; attached: PolicyRef[] } | null>(null);
  const load = useCallback(async () => { try { setR(await api(`${ctx.base}/roles/${encodeURIComponent(name)}`)); } catch (e) { ctx.fail(e); } }, [ctx.base, name]);
  useEffect(() => { void load(); }, [load]);
  if (!r) return null;
  return (
    <div>
      <h2 className="mono" style={{ fontSize: 20, marginBottom: 10 }}>{name}</h2>
      <AttachedPolicies ctx={ctx} kind="roles" name={name} attached={r.attached} reload={load} />
      <div className="panel"><div className="panel-head"><h3>Trust relationships</h3></div>
        <div className="panel-body"><pre className="mono small" style={{ margin: 0 }}>{JSON.stringify(r.trust, null, 2)}</pre></div></div>
    </div>
  );
}

// --------------------------------------------------------------------------------------- policies
function PolicyList(ctx: Ctx) {
  const [scope, setScope] = useState<"all" | "local" | "aws">("local");
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => { const t = setTimeout(() => setQ(search), 300); return () => clearTimeout(t); }, [search]);
  const { policies, load } = usePolicies(ctx.base, ctx.fail, scope, q);
  async function del(arn: string) {
    if (!confirm("Delete this policy? It must be detached first.")) return;
    try { await api(`${ctx.base}/policy?arn=${encodeURIComponent(arn)}`, { method: "DELETE" }); await load(); ctx.notify("pass", "Policy deleted."); } catch (e) { ctx.fail(e); }
  }
  return (
    <ListPanel title="Policies" count={policies?.length} onRefresh={() => void load()}
      action={<button className="small primary" onClick={() => ctx.go({ section: "policies", page: "create" })} data-testid="open-create-policy">Create policy</button>}>
      <div className="row" style={{ padding: 12 }}>
        <select value={scope} onChange={(e) => setScope(e.target.value as "all" | "local" | "aws")} style={{ width: 200 }} aria-label="Filter by type">
          <option value="local">Customer managed</option><option value="aws">AWS managed</option><option value="all">All types</option></select>
        <input placeholder="Search" value={search} onChange={(e) => setSearch(e.target.value)} style={{ maxWidth: 280 }} aria-label="Search policies" />
      </div>
      <table className="data">
        <thead><tr><th>Policy name</th><th>Type</th><th>Attached entities</th><th /></tr></thead>
        <tbody>
          {policies?.length === 0 && <tr><td colSpan={4} className="muted">No policies match.</td></tr>}
          {policies?.map((p) => (
            <tr key={p.arn}>
              <td><button className="linklike mono" onClick={() => ctx.go({ section: "policies", page: "detail", name: p.arn })}>{p.name}</button></td>
              <td className="small">{p.type}</td><td className="small">{p.attachments}</td>
              <td style={{ textAlign: "right" }}>{p.type === "Customer managed" && <button className="small danger" onClick={() => void del(p.arn)}>Delete</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </ListPanel>
  );
}

function CreatePolicy(ctx: Ctx) {
  const [step, setStep] = useState(0);
  const [doc, setDoc] = useState(POLICY_TEMPLATE);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  let jsonError: string | null = null;
  try { JSON.parse(doc); } catch (e) { jsonError = (e as Error).message; }
  async function create() {
    try { await api(`${ctx.base}/policies`, { method: "POST", body: { name, document: doc, description } }); ctx.notify("pass", `Policy ${name} created.`); ctx.go({ section: "policies", page: "list" }); }
    catch (e) { ctx.fail(e); }
  }
  return (
    <div>
      <h2 style={{ marginBottom: 10 }}>Create policy</h2>
      <Steps steps={["Specify permissions", "Review and create"]} at={step} />
      {step === 0 ? (
        <div className="panel"><div className="panel-head"><h3>Policy editor</h3><span className="pill info">JSON</span><SimLabel note="The visual editor isn't available; use JSON." /></div>
          <div className="panel-body">
            <textarea className="mono" rows={16} value={doc} onChange={(e) => setDoc(e.target.value)} spellCheck={false} aria-label="Policy document JSON" data-testid="policy-json" />
            {jsonError && <div className="banner fail small">JSON error: {jsonError}</div>}
            <div className="actions"><button className="small" onClick={() => ctx.go({ section: "policies", page: "list" })}>Cancel</button>
              <button className="small primary" disabled={!!jsonError} onClick={() => setStep(1)} data-testid="wizard-next">Next</button></div>
          </div></div>
      ) : (
        <div className="panel"><div className="panel-head"><h3>Policy details</h3></div><div className="panel-body">
          <label>Policy name<input className="mono" value={name} onChange={(e) => setName(e.target.value)} style={{ maxWidth: 360 }} data-testid="new-policy-name" /></label>
          <label>Description <span className="help">- optional</span><input value={description} onChange={(e) => setDescription(e.target.value)} style={{ maxWidth: 520 }} /></label>
          <div className="actions"><button className="small" onClick={() => setStep(0)}>Previous</button>
            <button className="small primary" disabled={!/^[\w+=,.@-]{1,128}$/.test(name)} onClick={() => void create()} data-testid="create-policy">Create policy</button></div>
        </div></div>
      )}
    </div>
  );
}

function PolicyDetail({ arn, ...ctx }: Ctx & { arn: string }) {
  const [p, setP] = useState<{ name: string; type: string; description: string; attachments: number; document: unknown } | null>(null);
  useEffect(() => { void api<typeof p>(`${ctx.base}/policy?arn=${encodeURIComponent(arn)}`).then(setP).catch(ctx.fail); }, [ctx.base, arn]);
  if (!p) return null;
  return (
    <div>
      <h2 className="mono" style={{ fontSize: 20, marginBottom: 10 }}>{p.name}</h2>
      <div className="panel"><div className="panel-head"><h3>Policy details</h3></div><div className="panel-body"><dl className="kv" style={{ margin: 0 }}>
        <div><dt>Type</dt><dd>{p.type}</dd></div><div><dt>Attached entities</dt><dd>{p.attachments}</dd></div>
        <div><dt>ARN</dt><dd className="mono small">{arn}</dd></div></dl></div></div>
      <div className="panel"><div className="panel-head"><h3>Permissions defined in this policy</h3></div>
        <div className="panel-body"><pre className="mono small" style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(p.document, null, 2)}</pre></div></div>
    </div>
  );
}

// -------------------------------------------------------------------------------------- simulator
function Simulator(ctx: Ctx) {
  const [principals, setPrincipals] = useState<string[]>([]);
  const [principal, setPrincipal] = useState("");
  const [actions, setActions] = useState("s3:GetObject, s3:PutObject, s3:DeleteObject");
  const [resource, setResource] = useState("*");
  const [results, setResults] = useState<{ action: string; decision: string; matched_policies: string[]; conditions_not_evaluated: string[] }[] | null>(null);
  useEffect(() => {
    void (async () => {
      try {
        const [u, g, r] = await Promise.all([api<{ users: UserRow[] }>(`${ctx.base}/users`), api<{ groups: GroupRow[] }>(`${ctx.base}/groups`), api<{ roles: RoleRow[] }>(`${ctx.base}/roles`)]);
        const all = [...u.users.map((x) => `user:${x.name}`), ...g.groups.map((x) => `group:${x.name}`), ...r.roles.map((x) => `role:${x.name}`)];
        setPrincipals(all); setPrincipal((p) => p || all[0] || "");
      } catch (e) { ctx.fail(e); }
    })();
  }, [ctx.base]);
  async function run(e: React.FormEvent) {
    e.preventDefault();
    try {
      const out = await api<{ results: typeof results }>(`${ctx.base}/simulate`, { method: "POST", body: {
        principal, resource, actions: actions.split(",").map((a) => a.trim()).filter(Boolean) } });
      setResults(out.results);
    } catch (err) { ctx.fail(err); }
  }
  const label = (d: string) => d === "allowed" ? ["pass", "Allowed"] : d === "explicit_deny" ? ["fail", "Denied (explicit)"] : ["fail", "Denied"];
  return (
    <form onSubmit={run}>
      <div className="panel"><div className="panel-head"><h3>Policy simulator</h3><span className="pill info">Simulated by Stackora</span></div>
        <div className="panel-body">
          <p className="help" style={{ margin: 0 }}>Tests identity-based policies (the user&apos;s own and its groups&apos;) the way IAM evaluates them: an explicit deny wins, then an allow, otherwise an implicit deny. Conditions aren&apos;t evaluated.</p>
          <label>Principal<select value={principal} onChange={(e) => setPrincipal(e.target.value)} style={{ maxWidth: 360 }} data-testid="sim-principal">
            {principals.length === 0 && <option value="">Create a user, group or role first</option>}
            {principals.map((p) => <option key={p} value={p}>{p.replace(":", ": ")}</option>)}</select></label>
          <label>Actions (comma-separated)<input className="mono" value={actions} onChange={(e) => setActions(e.target.value)} data-testid="sim-actions" /></label>
          <label>Resource ARN<input className="mono" value={resource} onChange={(e) => setResource(e.target.value)} data-testid="sim-resource" /></label>
          <div className="actions"><button className="small primary" disabled={!principal} data-testid="run-simulation">Run simulation</button></div>
        </div></div>
      {results && (
        <div className="panel"><div className="panel-head"><h3>Results</h3></div>
          <div className="panel-body" style={{ padding: 0 }}>
            <table className="data"><thead><tr><th>Action</th><th>Permission</th><th>Matched policies</th></tr></thead>
              <tbody>{results.map((r) => { const [cls, text] = label(r.decision); return (
                <tr key={r.action} data-testid="sim-result"><td className="mono small">{r.action}</td><td><span className={`pill ${cls}`}>{text}</span></td>
                  <td className="small">{r.matched_policies.join(", ") || "-"}{r.conditions_not_evaluated.length > 0 && <span className="muted"> (conditions not evaluated: {r.conditions_not_evaluated.join(", ")})</span>}</td></tr>); })}</tbody></table>
          </div></div>
      )}
    </form>
  );
}
