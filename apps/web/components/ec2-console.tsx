"use client";
// Student EC2 console (PLAN console fidelity principle): Instances + Launch instance, Security Groups
// (Edit inbound rules), Key Pairs. Instances are simulated records; connecting is labelled unsupported.
// Talks only to CloudLabs FastAPI endpoints.
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { type Feature, FlashBanner, type Notify, SimLabel, TagRows, useFlash } from "./console-kit";

type Instance = { id: string; name: string; state: string; type: string; image_id: string; key_name: string | null;
  security_groups: { id: string; name: string }[]; private_ip: string | null; launched_at: string | null; tags: { key: string; value: string }[] };
type Sg = { id: string; name: string; description: string; vpc_id: string; inbound_rules: number };
type Rule = { protocol: string; from_port: number | null; to_port: number | null; cidr: string; description?: string };
type Options = { images: { id: string; name: string; description: string; platform: string }[];
  instance_types: { name: string; free_tier: boolean }[]; key_pairs: string[]; security_groups: { id: string; name: string }[];
  vpc_id: string; subnet_id: string | null };
type Section = "instances" | "sgs" | "keys";
type View = { section: Section; page: "list" | "launch" | "detail" | "create"; id?: string };
type Ctx = { base: string; fail: (e: unknown) => void; notify: Notify; go: (v: View) => void; features: Record<string, Feature> };

const RULE_TYPES: Record<string, { protocol: string; port: number | null }> = {
  SSH: { protocol: "tcp", port: 22 }, HTTP: { protocol: "tcp", port: 80 }, HTTPS: { protocol: "tcp", port: 443 },
  "Custom TCP": { protocol: "tcp", port: null }, "All traffic": { protocol: "-1", port: null } };
const STATE_PILL: Record<string, string> = { running: "pass", stopped: "warn", terminated: "", pending: "info", stopping: "info" };

function ruleType(r: Rule): string {
  if (r.protocol === "-1") return "All traffic";
  const t = Object.entries(RULE_TYPES).find(([, v]) => v.protocol === r.protocol && v.port === r.from_port && r.from_port === r.to_port);
  return t ? t[0] : "Custom TCP";
}

export function Ec2Console({ sessionId, readOnly, features }: { sessionId: string; readOnly: boolean; features: Record<string, Feature> }) {
  const base = `/api/sessions/${sessionId}/console/ec2`;
  const [view, setView] = useState<View>({ section: "instances", page: "list" });
  const { flash, notify, fail, clear } = useFlash();
  const ctx: Ctx = { base, fail, notify, go: setView, features };
  const label = { instances: "Instances", sgs: "Security Groups", keys: "Key Pairs" }[view.section];
  return (
    <section className="svc-main">
      <div className="crumbs small" aria-label="Breadcrumb">
        <button className="linklike" onClick={() => setView({ section: "instances", page: "list" })}>EC2</button><span>›</span>
        <button className="linklike" onClick={() => setView({ section: view.section, page: "list" })}>{label}</button>
        {view.page === "launch" && <><span>›</span><span>Launch an instance</span></>}
        {view.page === "create" && <><span>›</span><span>Create</span></>}
        {view.page === "detail" && <><span>›</span><span className="mono">{view.id}</span></>}
      </div>
      <FlashBanner flash={flash} onClose={clear} />
      {readOnly ? <div className="banner info">This lab is submitted or not running, so the console is read-only.</div> : (
        <>
          <div className="tabs" role="tablist" aria-label="EC2">
            {(["instances", "sgs", "keys"] as Section[]).map((s) => (
              <button key={s} role="tab" aria-selected={view.section === s} className={view.section === s ? "tab on" : "tab"}
                onClick={() => setView({ section: s, page: "list" })} data-testid={`ec2-${s}`}>
                {{ instances: "Instances", sgs: "Security Groups", keys: "Key Pairs" }[s]}</button>))}
          </div>
          {view.section === "instances" && (view.page === "list" ? <InstanceList {...ctx} /> : view.page === "launch" ? <Launch {...ctx} /> : <InstanceDetail {...ctx} id={view.id!} />)}
          {view.section === "sgs" && (view.page === "list" ? <SgList {...ctx} /> : view.page === "create" ? <CreateSg {...ctx} /> : <SgDetail {...ctx} id={view.id!} />)}
          {view.section === "keys" && <KeyPairs {...ctx} />}
        </>
      )}
    </section>
  );
}

// -------------------------------------------------------------------------------------- instances
function InstanceList(ctx: Ctx) {
  const [items, setItems] = useState<Instance[] | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [menu, setMenu] = useState(false);
  const load = useCallback(async () => { try { setItems((await api<{ instances: Instance[] }>(`${ctx.base}/instances`)).instances); } catch (e) { ctx.fail(e); } }, [ctx.base, ctx.fail]);
  useEffect(() => { void load(); }, [load]);
  async function act(action: "start" | "stop" | "terminate") {
    setMenu(false);
    if (action === "terminate" && !confirm("Terminate this instance? This can't be undone.")) return;
    try { await api(`${ctx.base}/instances/${sel}/state`, { method: "POST", body: { action } }); await load();
      ctx.notify("pass", `Successfully ${action === "stop" ? "stopped" : action === "start" ? "started" : "terminated"} ${sel}.`); } catch (e) { ctx.fail(e); }
  }
  const current = items?.find((i) => i.id === sel);
  return (
    <div className="panel">
      <div className="panel-head">
        <h3>Instances <span className="muted">({items?.length ?? "…"})</span></h3>
        <button className="small" onClick={() => void load()}>Refresh</button>
        <button className="small" disabled title="Connecting isn't available in the simulator">Connect</button>
        <div style={{ position: "relative" }}>
          <button className="small" disabled={!current || current.state === "terminated"} onClick={() => setMenu(!menu)} data-testid="instance-state-menu">Instance state ▾</button>
          {menu && current && (
            <div className="menu">
              <button className="small ghost" disabled={current.state === "stopped"} onClick={() => void act("stop")} data-testid="stop-instance">Stop instance</button>
              <button className="small ghost" disabled={current.state === "running"} onClick={() => void act("start")}>Start instance</button>
              <button className="small ghost danger" onClick={() => void act("terminate")} data-testid="terminate-instance">Terminate (delete) instance</button>
            </div>)}
        </div>
        <button className="small primary" onClick={() => ctx.go({ section: "instances", page: "launch" })} data-testid="open-launch">Launch instances</button>
      </div>
      <div className="panel-body" style={{ padding: 0, overflowX: "auto" }}>
        <table className="data">
          <thead><tr><th style={{ width: 36 }} /><th>Name</th><th>Instance ID</th><th>Instance state</th><th>Instance type</th><th>Key name</th><th>Security group</th></tr></thead>
          <tbody>
            {items?.length === 0 && <tr><td colSpan={7} className="muted">No instances. Choose <strong>Launch instances</strong>, or run <code>aws ec2 run-instances</code>.</td></tr>}
            {items?.map((i) => (
              <tr key={i.id} data-testid="instance-row">
                <td><input type="radio" name="inst" style={{ width: "auto" }} aria-label={`Select ${i.name || i.id}`} checked={sel === i.id} onChange={() => setSel(i.id)} /></td>
                <td className="small">{i.name || "-"}</td>
                <td><button className="linklike mono small" onClick={() => ctx.go({ section: "instances", page: "detail", id: i.id })}>{i.id}</button></td>
                <td><span className={`pill ${STATE_PILL[i.state] ?? ""}`}>{i.state[0].toUpperCase() + i.state.slice(1)}</span></td>
                <td className="mono small">{i.type}</td><td className="mono small">{i.key_name ?? "-"}</td>
                <td className="small">{i.security_groups.map((g) => g.name).join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <style>{`.menu { position: absolute; top: 34px; right: 0; background: #fff; border: 1px solid var(--line); border-radius: 8px; box-shadow: var(--shadow); display: flex; flex-direction: column; z-index: 5; min-width: 220px; padding: 4px; }
        .menu button { justify-content: flex-start; }`}</style>
    </div>
  );
}

function Launch(ctx: Ctx) {
  const [o, setO] = useState<Options | null>(null);
  const [name, setName] = useState("");
  const [tags, setTags] = useState<{ key: string; value: string }[]>([]);
  const [image, setImage] = useState("");
  const [itype, setItype] = useState("t2.micro");
  const [key, setKey] = useState("");
  const [newKey, setNewKey] = useState<{ name: string; pem: string } | null>(null);
  const [sgMode, setSgMode] = useState<"create" | "existing">("create");
  const [sgName, setSgName] = useState("launch-wizard-1");
  const [ssh, setSsh] = useState(true);
  const [sshFrom, setSshFrom] = useState("0.0.0.0/0");
  const [http, setHttp] = useState(false);
  const [https, setHttps] = useState(false);
  const [existing, setExisting] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try { const x = await api<Options>(`${ctx.base}/launch-options`); setO(x); setImage((v) => v || x.images[0]?.id || ""); } catch (e) { ctx.fail(e); }
  }, [ctx.base, ctx.fail]);
  useEffect(() => { void load(); }, [load]);

  async function createKey() {
    const kn = prompt("Key pair name");
    if (!kn) return;
    try { const r = await api<{ name: string; private_key: string }>(`${ctx.base}/key-pairs`, { method: "POST", body: { name: kn } });
      setNewKey({ name: r.name, pem: r.private_key }); setKey(r.name); await load(); } catch (e) { ctx.fail(e); }
  }
  async function launch() {
    setBusy(true);
    try {
      await api(`${ctx.base}/instances`, { method: "POST", body: {
        name, image_id: image, instance_type: itype, key_name: key || null, tags,
        security_group_ids: sgMode === "existing" ? existing : [],
        create_security_group: sgMode === "create" ? { name: sgName, ssh_cidr: ssh ? sshFrom : null, http, https } : null } });
      ctx.notify("pass", `Successfully initiated launch of instance ${name}.`); ctx.go({ section: "instances", page: "list" });
    } catch (e) { ctx.fail(e); } finally { setBusy(false); }
  }
  if (!o) return <p className="muted small">Loading launch options…</p>;
  return (
    <div className="launch">
      <div>
        <h2 style={{ marginBottom: 12 }}>Launch an instance</h2>
        <div className="panel"><div className="panel-head"><h3>Name and tags</h3></div><div className="panel-body">
          <label>Name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. My Web Server" style={{ maxWidth: 420 }} data-testid="instance-name" /></label>
          <details><summary className="small">Add additional tags</summary><div style={{ marginTop: 8 }}><TagRows tags={tags} setTags={setTags} /></div></details>
        </div></div>
        <div className="panel"><div className="panel-head"><h3>Application and OS Images (Amazon Machine Image)</h3></div><div className="panel-body">
          <span className="help">Quick Start: images available in your training cloud.</span>
          <select value={image} onChange={(e) => setImage(e.target.value)} data-testid="ami">
            {o.images.map((i) => <option key={i.id} value={i.id}>{i.name} ({i.platform}) - {i.id}</option>)}</select>
        </div></div>
        <div className="panel"><div className="panel-head"><h3>Instance type</h3></div><div className="panel-body">
          <select value={itype} onChange={(e) => setItype(e.target.value)} style={{ maxWidth: 320 }} data-testid="instance-type">
            {o.instance_types.map((t) => <option key={t.name} value={t.name}>{t.name}{t.free_tier ? "  (Free tier eligible)" : ""}</option>)}</select>
        </div></div>
        <div className="panel"><div className="panel-head"><h3>Key pair (login)</h3></div><div className="panel-body">
          <div className="row"><select value={key} onChange={(e) => setKey(e.target.value)} style={{ maxWidth: 320 }} aria-label="Key pair name" data-testid="key-select">
            <option value="">Proceed without a key pair (Not recommended)</option>
            {o.key_pairs.map((k) => <option key={k}>{k}</option>)}</select>
            <button className="small" onClick={() => void createKey()}>Create new key pair</button></div>
          {newKey && <PemNotice pem={newKey.pem} name={newKey.name} />}
        </div></div>
        <div className="panel"><div className="panel-head"><h3>Network settings</h3></div><div className="panel-body">
          <dl className="kv" style={{ margin: 0 }}><div><dt>VPC</dt><dd className="mono small">{o.vpc_id} (default)</dd></div>
            <div><dt>Subnet</dt><dd className="mono small">{o.subnet_id ?? "No preference"}</dd></div>
            <div><dt>Auto-assign public IP</dt><dd className="small">Enable <SimLabel note="Public IP addresses are not simulated." /></dd></div></dl>
          <span className="small" style={{ fontWeight: 600 }}>Firewall (security groups)</span>
          <label className="choice"><input type="radio" checked={sgMode === "create"} onChange={() => setSgMode("create")} /> Create security group</label>
          <label className="choice"><input type="radio" checked={sgMode === "existing"} onChange={() => setSgMode("existing")} data-testid="sg-existing" /> Select existing security group</label>
          {sgMode === "create" ? (
            <div className="stack" style={{ marginLeft: 22 }}>
              <label>Security group name<input className="mono" value={sgName} onChange={(e) => setSgName(e.target.value)} style={{ maxWidth: 320 }} /></label>
              <label className="choice"><input type="checkbox" checked={ssh} onChange={(e) => setSsh(e.target.checked)} /><span>Allow SSH traffic from
                <input className="mono" value={sshFrom} onChange={(e) => setSshFrom(e.target.value)} style={{ width: 170, marginLeft: 8 }} aria-label="SSH source CIDR" /></span></label>
              {ssh && sshFrom === "0.0.0.0/0" && <div className="banner warn small">Rules with source of 0.0.0.0/0 allow all IP addresses to access your instance. We recommend setting security group rules to allow access from known IP addresses only.</div>}
              <label className="choice"><input type="checkbox" checked={http} onChange={(e) => setHttp(e.target.checked)} /> Allow HTTP traffic from the internet</label>
              <label className="choice"><input type="checkbox" checked={https} onChange={(e) => setHttps(e.target.checked)} /> Allow HTTPS traffic from the internet</label>
            </div>
          ) : (
            <div className="stack" style={{ marginLeft: 22 }}>
              {o.security_groups.map((g) => <label key={g.id} className="choice"><input type="checkbox" aria-label={`Security group ${g.name}`} checked={existing.includes(g.id)}
                onChange={(e) => setExisting(e.target.checked ? [...existing, g.id] : existing.filter((x) => x !== g.id))} /><span className="mono small">{g.name} ({g.id})</span></label>)}
            </div>
          )}
        </div></div>
        <div className="panel disabled"><div className="panel-head"><h3>Configure storage</h3><SimLabel note={ctx.features.CreateVolume?.note} /></div>
          <div className="panel-body small muted">1x 8 GiB gp3 root volume (shown for reference only).</div></div>
      </div>
      <aside className="panel summary">
        <div className="panel-head"><h3>Summary</h3></div>
        <div className="panel-body small">
          <div>Number of instances: <strong>1</strong></div>
          <div>Software image: <span className="mono">{o.images.find((i) => i.id === image)?.name ?? "-"}</span></div>
          <div>Instance type: <span className="mono">{itype}</span></div>
          <div>Firewall: {sgMode === "create" ? `New security group (${sgName})` : `${existing.length} selected`}</div>
          <button className="primary" disabled={busy || !name || !image || (sgMode === "existing" && existing.length === 0)} onClick={() => void launch()} data-testid="launch-instance">
            {busy ? "Launching…" : "Launch instance"}</button>
        </div>
      </aside>
      <style>{`.launch { display: grid; grid-template-columns: minmax(0, 1fr) 260px; gap: 14px; align-items: start; }
        .summary { position: sticky; top: 0; } @media (max-width: 1000px) { .launch { grid-template-columns: 1fr; } }`}</style>
    </div>
  );
}

function PemNotice({ pem, name }: { pem: string; name: string }) {
  const href = `data:application/x-pem-file;charset=utf-8,${encodeURIComponent(pem)}`;
  return (
    <div className="banner info small">
      <div className="grow">Key pair <strong>{name}</strong> created. This is the only time you can save the private key file.</div>
      <a className="btn small" href={href} download={`${name}.pem`}>Download .pem</a>
    </div>
  );
}

function InstanceDetail({ id, ...ctx }: Ctx & { id: string }) {
  const [i, setI] = useState<Instance | null>(null);
  const [editTags, setEditTags] = useState<{ key: string; value: string }[] | null>(null);
  const load = useCallback(async () => { try { setI(await api<Instance>(`${ctx.base}/instances/${id}`)); } catch (e) { ctx.fail(e); } }, [ctx.base, id, ctx.fail]);
  useEffect(() => { void load(); }, [load]);
  async function saveTags() {
    try { await api(`${ctx.base}/instances/${id}/tags`, { method: "PUT", body: { tags: editTags } }); setEditTags(null); await load(); ctx.notify("pass", "Tags saved."); } catch (e) { ctx.fail(e); }
  }
  if (!i) return null;
  return (
    <div>
      <div className="row" style={{ marginBottom: 10 }}><h2 className="mono" style={{ fontSize: 20 }}>{i.id}</h2>
        <span className="small">({i.name || "no name"})</span><span className={`pill ${STATE_PILL[i.state] ?? ""}`}>{i.state}</span></div>
      <div className="panel"><div className="panel-head"><h3>Instance summary</h3><SimLabel note={ctx.features.ConnectToInstance?.note} /></div>
        <div className="panel-body"><dl className="kv" style={{ margin: 0 }}>
          <div><dt>Instance type</dt><dd className="mono">{i.type}</dd></div><div><dt>AMI ID</dt><dd className="mono small">{i.image_id}</dd></div>
          <div><dt>Key pair assigned at launch</dt><dd className="mono">{i.key_name ?? "-"}</dd></div>
          <div><dt>Private IPv4 address</dt><dd className="mono small">{i.private_ip ?? "-"}</dd></div>
          <div><dt>Launch time</dt><dd className="small">{fmtDate(i.launched_at)}</dd></div>
          <div><dt>Security groups</dt><dd className="small">{i.security_groups.map((g) => g.name).join(", ")}</dd></div></dl></div></div>
      <div className="panel"><div className="panel-head"><h3>Tags</h3>{editTags === null && <button className="small" onClick={() => setEditTags(i.tags)} data-testid="manage-tags">Manage tags</button>}</div>
        <div className="panel-body">{editTags === null ? (
          <table className="data"><tbody>{i.tags.map((t) => <tr key={t.key}><td className="mono small">{t.key}</td><td className="mono small">{t.value}</td></tr>)}</tbody></table>
        ) : (<><TagRows tags={editTags} setTags={setEditTags} /><div className="actions"><button className="small" onClick={() => setEditTags(null)}>Cancel</button>
          <button className="small primary" onClick={() => void saveTags()} data-testid="save-instance-tags">Save</button></div></>)}</div></div>
    </div>
  );
}

// -------------------------------------------------------------------------------- security groups
function SgList(ctx: Ctx) {
  const [items, setItems] = useState<Sg[] | null>(null);
  const load = useCallback(async () => { try { setItems((await api<{ security_groups: Sg[] }>(`${ctx.base}/security-groups`)).security_groups); } catch (e) { ctx.fail(e); } }, [ctx.base, ctx.fail]);
  useEffect(() => { void load(); }, [load]);
  async function del(id: string) {
    if (!confirm("Delete this security group?")) return;
    try { await api(`${ctx.base}/security-groups/${id}`, { method: "DELETE" }); await load(); ctx.notify("pass", "Security group deleted."); } catch (e) { ctx.fail(e); }
  }
  return (
    <div className="panel">
      <div className="panel-head"><h3>Security Groups <span className="muted">({items?.length ?? "…"})</span></h3>
        <button className="small" onClick={() => void load()}>Refresh</button>
        <button className="small primary" onClick={() => ctx.go({ section: "sgs", page: "create" })} data-testid="open-create-sg">Create security group</button></div>
      <div className="panel-body" style={{ padding: 0 }}>
        <table className="data"><thead><tr><th>Security group name</th><th>Security group ID</th><th>Description</th><th>Inbound rules</th><th /></tr></thead>
          <tbody>{items?.map((g) => (
            <tr key={g.id}><td className="mono small">{g.name}</td>
              <td><button className="linklike mono small" onClick={() => ctx.go({ section: "sgs", page: "detail", id: g.id })}>{g.id}</button></td>
              <td className="small">{g.description}</td><td className="small">{g.inbound_rules}</td>
              <td style={{ textAlign: "right" }}>{g.name !== "default" && <button className="small danger" onClick={() => void del(g.id)}>Delete</button>}</td></tr>))}</tbody></table>
      </div>
    </div>
  );
}

function RuleEditor({ rules, setRules }: { rules: Rule[]; setRules: (r: Rule[]) => void }) {
  function setType(i: number, t: string) {
    const d = RULE_TYPES[t];
    setRules(rules.map((r, j) => j === i ? { ...r, protocol: d.protocol, from_port: d.port ?? (d.protocol === "-1" ? -1 : r.from_port), to_port: d.port ?? (d.protocol === "-1" ? -1 : r.to_port) } : r));
  }
  return (
    <>
      <table className="data"><thead><tr><th>Type</th><th>Port range</th><th>Source</th><th>Description</th><th /></tr></thead>
        <tbody>{rules.map((r, i) => {
          const t = ruleType(r);
          return (
            <tr key={i} data-testid="rule-row">
              <td><select value={t} onChange={(e) => setType(i, e.target.value)} aria-label="Rule type">{Object.keys(RULE_TYPES).map((k) => <option key={k}>{k}</option>)}</select></td>
              <td>{t === "Custom TCP" ? <input className="mono" style={{ width: 90 }} value={r.from_port ?? ""} aria-label="Port"
                onChange={(e) => { const p = Number(e.target.value) || 0; setRules(rules.map((x, j) => j === i ? { ...x, from_port: p, to_port: p } : x)); }} />
                : <span className="mono small">{r.protocol === "-1" ? "All" : r.from_port}</span>}</td>
              <td><input className="mono" style={{ width: 160 }} value={r.cidr} aria-label="Source CIDR"
                onChange={(e) => setRules(rules.map((x, j) => j === i ? { ...x, cidr: e.target.value } : x))} /></td>
              <td><input value={r.description ?? ""} aria-label="Rule description" onChange={(e) => setRules(rules.map((x, j) => j === i ? { ...x, description: e.target.value } : x))} /></td>
              <td><button className="small ghost" onClick={() => setRules(rules.filter((_, j) => j !== i))}>Delete</button></td>
            </tr>);
        })}</tbody></table>
      <div><button className="small" onClick={() => setRules([...rules, { protocol: "tcp", from_port: 22, to_port: 22, cidr: "0.0.0.0/0", description: "" }])} data-testid="add-rule">Add rule</button></div>
    </>
  );
}

function toApi(r: Rule) {
  return { protocol: r.protocol, from_port: r.from_port ?? -1, to_port: r.to_port ?? -1, cidr: r.cidr, description: r.description ?? "" };
}

function CreateSg(ctx: Ctx) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [rules, setRules] = useState<Rule[]>([]);
  async function create() {
    try { await api(`${ctx.base}/security-groups`, { method: "POST", body: { name, description: description || name, rules: rules.map(toApi) } });
      ctx.notify("pass", `Security group ${name} created.`); ctx.go({ section: "sgs", page: "list" }); } catch (e) { ctx.fail(e); }
  }
  return (
    <div>
      <h2 style={{ marginBottom: 12 }}>Create security group</h2>
      <div className="panel"><div className="panel-head"><h3>Basic details</h3></div><div className="panel-body">
        <label>Security group name<input className="mono" value={name} onChange={(e) => setName(e.target.value)} style={{ maxWidth: 360 }} data-testid="new-sg-name" /></label>
        <label>Description<input value={description} onChange={(e) => setDescription(e.target.value)} style={{ maxWidth: 520 }} /></label>
      </div></div>
      <div className="panel"><div className="panel-head"><h3>Inbound rules</h3></div><div className="panel-body"><RuleEditor rules={rules} setRules={setRules} /></div></div>
      <div className="panel disabled"><div className="panel-head"><h3>Outbound rules</h3><span className="pill">All traffic allowed (default)</span></div></div>
      <div className="actions"><button onClick={() => ctx.go({ section: "sgs", page: "list" })}>Cancel</button>
        <button className="primary" disabled={!name} onClick={() => void create()} data-testid="create-sg">Create security group</button></div>
    </div>
  );
}

function SgDetail({ id, ...ctx }: Ctx & { id: string }) {
  const [g, setG] = useState<{ name: string; description: string; inbound_rules: Rule[] } | null>(null);
  const [edit, setEdit] = useState<Rule[] | null>(null);
  const load = useCallback(async () => { try { setG(await api(`${ctx.base}/security-groups/${id}`)); } catch (e) { ctx.fail(e); } }, [ctx.base, id, ctx.fail]);
  useEffect(() => { void load(); }, [load]);
  async function save() {
    try { await api(`${ctx.base}/security-groups/${id}/inbound-rules`, { method: "PUT", body: { rules: edit!.map(toApi) } });
      setEdit(null); await load(); ctx.notify("pass", "Inbound security group rules successfully modified."); } catch (e) { ctx.fail(e); }
  }
  if (!g) return null;
  return (
    <div>
      <h2 className="mono" style={{ fontSize: 20, marginBottom: 10 }}>{g.name} <span className="small muted">{id}</span></h2>
      <div className="panel"><div className="panel-head"><h3>Inbound rules <span className="muted">({g.inbound_rules.length})</span></h3>
        {edit === null && <button className="small" onClick={() => setEdit(g.inbound_rules)} data-testid="edit-inbound">Edit inbound rules</button>}</div>
        <div className="panel-body">{edit !== null ? (
          <><RuleEditor rules={edit} setRules={setEdit} />
            <div className="actions"><button className="small" onClick={() => setEdit(null)}>Cancel</button>
              <button className="small primary" onClick={() => void save()} data-testid="save-rules">Save rules</button></div></>
        ) : g.inbound_rules.length === 0 ? <p className="help" style={{ margin: 0 }}>No inbound rules. All inbound traffic is blocked.</p> : (
          <table className="data"><thead><tr><th>Type</th><th>Protocol</th><th>Port range</th><th>Source</th></tr></thead>
            <tbody>{g.inbound_rules.map((r, i) => <tr key={i}><td className="small">{ruleType(r)}</td><td className="mono small">{r.protocol === "-1" ? "All" : r.protocol.toUpperCase()}</td>
              <td className="mono small">{r.protocol === "-1" ? "All" : r.from_port === r.to_port ? r.from_port : `${r.from_port}-${r.to_port}`}</td><td className="mono small">{r.cidr}</td></tr>)}</tbody></table>
        )}</div></div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------- key pairs
function KeyPairs(ctx: Ctx) {
  const [items, setItems] = useState<{ name: string; fingerprint: string; type: string }[] | null>(null);
  const [name, setName] = useState("");
  const [created, setCreated] = useState<{ name: string; pem: string } | null>(null);
  const load = useCallback(async () => { try { setItems((await api<{ key_pairs: { name: string; fingerprint: string; type: string }[] }>(`${ctx.base}/key-pairs`)).key_pairs); } catch (e) { ctx.fail(e); } }, [ctx.base, ctx.fail]);
  useEffect(() => { void load(); }, [load]);
  async function create(e: React.FormEvent) {
    e.preventDefault();
    try { const r = await api<{ name: string; private_key: string }>(`${ctx.base}/key-pairs`, { method: "POST", body: { name } });
      setCreated({ name: r.name, pem: r.private_key }); setName(""); await load(); } catch (err) { ctx.fail(err); }
  }
  async function del(n: string) {
    try { await api(`${ctx.base}/key-pairs/${encodeURIComponent(n)}`, { method: "DELETE" }); await load(); ctx.notify("pass", `Key pair ${n} deleted.`); } catch (e) { ctx.fail(e); }
  }
  return (
    <div>
      <form className="panel" onSubmit={create}><div className="panel-head"><h3>Create key pair</h3></div><div className="panel-body">
        <div className="row"><input className="mono" placeholder="Key pair name" value={name} onChange={(e) => setName(e.target.value)} required style={{ maxWidth: 320 }} data-testid="new-key-name" />
          <button className="small primary" data-testid="create-key">Create key pair</button></div>
        {created && <PemNotice pem={created.pem} name={created.name} />}
      </div></form>
      <div className="panel"><div className="panel-head"><h3>Key pairs <span className="muted">({items?.length ?? "…"})</span></h3></div>
        <div className="panel-body" style={{ padding: 0 }}>
          <table className="data"><thead><tr><th>Name</th><th>Type</th><th>Fingerprint</th><th /></tr></thead>
            <tbody>{items?.map((k) => <tr key={k.name}><td className="mono small">{k.name}</td><td className="small">{k.type}</td>
              <td className="mono small" style={{ wordBreak: "break-all" }}>{k.fingerprint}</td>
              <td style={{ textAlign: "right" }}><button className="small danger" onClick={() => void del(k.name)}>Delete</button></td></tr>)}</tbody></table>
        </div></div>
    </div>
  );
}
