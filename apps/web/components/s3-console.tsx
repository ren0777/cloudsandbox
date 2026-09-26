"use client";
// Student S3 console. Follows PLAN's console fidelity principle: AWS terminology, resource hierarchy and
// workflows (Buckets → Create bucket → bucket tabs → Edit → Save changes), in CloudLabs' own visual
// style. Anything the simulator can't do is shown and labelled, never silently hidden.
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { type Feature, FlashBanner, fmtSize, type Notify, SimLabel, TagRows, useFlash } from "./console-kit";
import { fmtDate } from "@/lib/format";

type Bucket = { name: string; created_at: string | null; region: string; access: string };
type Obj = { key: string; size: number; last_modified: string | null };
type PAB = { BlockPublicAcls: boolean; IgnorePublicAcls: boolean; BlockPublicPolicy: boolean; RestrictPublicBuckets: boolean };
type Details = { name: string; region: string; arn: string; versioning: string; tags: Record<string, string>;
  object_ownership: string; public_access_block: PAB; policy: string | null; access: string };

const REGIONS = [
  ["us-east-1", "US East (N. Virginia) us-east-1"], ["us-west-2", "US West (Oregon) us-west-2"],
  ["eu-west-1", "Europe (Ireland) eu-west-1"], ["ap-south-1", "Asia Pacific (Mumbai) ap-south-1"],
];

export function S3Console({ sessionId, readOnly, features }: {
  sessionId: string; readOnly: boolean; features: Record<string, Feature>;
}) {
  const base = `/api/sessions/${sessionId}/console/s3`;
  const [view, setView] = useState<{ page: "list" } | { page: "create" } | { page: "bucket"; name: string }>({ page: "list" });
  const { flash, notify, fail, clear } = useFlash();

  return (
    <>
      <section className="svc-main">
        <div className="crumbs small" aria-label="Breadcrumb">
          <button className="linklike" onClick={() => setView({ page: "list" })}>Amazon S3</button>
          <span>›</span>
          <button className="linklike" onClick={() => setView({ page: "list" })}>Buckets</button>
          {view.page === "create" && <><span>›</span><span>Create bucket</span></>}
          {view.page === "bucket" && <><span>›</span><span className="mono">{view.name}</span></>}
        </div>
        <FlashBanner flash={flash} onClose={clear} />
        {readOnly ? (
          <div className="banner info">This lab is submitted or not running, so the console is read-only.</div>
        ) : view.page === "list" ? (
          <BucketList base={base} onOpen={(name) => setView({ page: "bucket", name })}
            onCreate={() => setView({ page: "create" })} fail={fail} notify={notify} />
        ) : view.page === "create" ? (
          <CreateBucket base={base} features={features} fail={fail}
            onDone={(name) => { notify("pass", `Successfully created bucket "${name}".`); setView({ page: "list" }); }}
            onCancel={() => setView({ page: "list" })} />
        ) : (
          <BucketView base={base} name={view.name} features={features} fail={fail} notify={notify} />
        )}
      </section>
    </>
  );
}

// ------------------------------------------------------------------------------------ bucket list
function BucketList({ base, onOpen, onCreate, fail, notify }: {
  base: string; onOpen: (n: string) => void; onCreate: () => void; fail: (e: unknown) => void; notify: Notify;
}) {
  const [buckets, setBuckets] = useState<Bucket[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [confirmName, setConfirmName] = useState("");
  const refresh = useCallback(async () => {
    try { setBuckets((await api<{ buckets: Bucket[] }>(`${base}/buckets`)).buckets); } catch (e) { fail(e); }
  }, [base, fail]);
  useEffect(() => { void refresh(); }, [refresh]);

  async function del() {
    try {
      await api(`${base}/buckets/${selected}`, { method: "DELETE" });
      notify("pass", `Successfully deleted bucket "${selected}".`);
      setSelected(null); setDeleting(false); setConfirmName("");
      await refresh();
    } catch (e) { fail(e); }
  }

  return (
    <div>
      <h2 style={{ marginBottom: 12 }}>Amazon S3</h2>
      <div className="panel">
        <div className="panel-head">
          <h3>General purpose buckets <span className="muted">({buckets?.length ?? "…"})</span></h3>
          <button className="small" onClick={() => void refresh()}>Refresh</button>
          <button className="small" disabled={!selected} onClick={() => setDeleting(true)}>Delete</button>
          <button className="small primary" onClick={onCreate} data-testid="open-create-bucket">Create bucket</button>
        </div>
        <div className="panel-body" style={{ padding: 0 }}>
          <table className="data">
            <thead><tr><th style={{ width: 36 }} /><th>Name</th><th>AWS Region</th><th>Access</th><th>Creation date</th></tr></thead>
            <tbody>
              {buckets?.length === 0 && <tr><td colSpan={5} className="muted">You don't have any buckets. Choose <strong>Create bucket</strong>, or run <code>aws s3 mb</code> in the terminal.</td></tr>}
              {buckets?.map((b) => (
                <tr key={b.name}>
                  <td><input type="radio" name="bucket-select" aria-label={`Select ${b.name}`} checked={selected === b.name}
                    onChange={() => setSelected(b.name)} style={{ width: "auto" }} /></td>
                  <td><button className="linklike mono" onClick={() => onOpen(b.name)}>{b.name}</button></td>
                  <td className="small">US East (N. Virginia) {b.region}</td>
                  <td className="small">{b.access}</td>
                  <td className="small muted">{fmtDate(b.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {deleting && selected && (
        <div className="panel">
          <div className="panel-head"><h3>Delete bucket</h3></div>
          <div className="panel-body">
            <p className="small" style={{ margin: 0 }}>The bucket must be empty. To confirm, type <strong className="mono">{selected}</strong>.</p>
            <input className="mono" value={confirmName} onChange={(e) => setConfirmName(e.target.value)} aria-label="Confirm bucket name" style={{ maxWidth: 360 }} />
            <div className="actions">
              <button className="small" onClick={() => { setDeleting(false); setConfirmName(""); }}>Cancel</button>
              <button className="small danger" disabled={confirmName !== selected} onClick={() => void del()}>Delete bucket</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------- create bucket
function CreateBucket({ base, features, fail, onDone, onCancel }: {
  base: string; features: Record<string, Feature>; fail: (e: unknown) => void;
  onDone: (name: string) => void; onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [region, setRegion] = useState("us-east-1");
  const [blockAll, setBlockAll] = useState(true);
  const [ack, setAck] = useState(false);
  const [versioning, setVersioning] = useState<"Disabled" | "Enabled">("Disabled");
  const [tags, setTags] = useState<{ key: string; value: string }[]>([]);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api(`${base}/buckets`, { method: "POST", body: {
        name: name.trim(), region, object_ownership: "BucketOwnerEnforced", block_public_access: blockAll,
        versioning, tags: tags.filter((t) => t.key.trim()) } });
      onDone(name.trim());
    } catch (err) { fail(err); } finally { setBusy(false); }
  }

  return (
    <form onSubmit={submit}>
      <h2 style={{ marginBottom: 4 }}>Create bucket</h2>
      <p className="small muted" style={{ marginTop: 0 }}>Buckets are containers for data stored in S3.</p>

      <div className="panel"><div className="panel-head"><h3>General configuration</h3></div>
        <div className="panel-body">
          <label>AWS Region
            <select value={region} onChange={(e) => setRegion(e.target.value)} style={{ maxWidth: 360 }}>
              {REGIONS.map(([v, l]) => <option key={v} value={v} disabled={v !== "us-east-1"}>{l}{v !== "us-east-1" ? " (not in simulator)" : ""}</option>)}
            </select>
          </label>
          <div className="row small"><span className="muted">Bucket type:</span> <strong>General purpose</strong>
            <span className="muted">· Directory buckets</span> <SimLabel /></div>
          <label>Bucket name
            <input className="mono" value={name} onChange={(e) => setName(e.target.value)} required placeholder="myawsbucket"
              pattern="[a-z0-9][a-z0-9.\-]{1,61}[a-z0-9]" style={{ maxWidth: 420 }} data-testid="new-bucket-name"
              title="3–63 characters: lowercase letters, numbers, dots and hyphens" />
            <span className="help">Bucket names must be 3 to 63 characters, unique across all AWS accounts, and use only lowercase letters, numbers, dots and hyphens.</span>
          </label>
        </div>
      </div>

      <div className="panel"><div className="panel-head"><h3>Object Ownership</h3></div>
        <div className="panel-body">
          <label className="choice"><input type="radio" checked readOnly name="own" />
            <span>ACLs disabled (recommended)<br /><span className="help">All objects in this bucket are owned by this account. Access is specified only through policies.</span></span></label>
          <label className="choice off"><input type="radio" disabled name="own" />
            <span>ACLs enabled <SimLabel note={features.PutBucketAcl?.note} /></span></label>
        </div>
      </div>

      <div className="panel"><div className="panel-head"><h3>Block Public Access settings for this bucket</h3></div>
        <div className="panel-body">
          <label className="choice"><input type="checkbox" checked={blockAll} onChange={(e) => { setBlockAll(e.target.checked); setAck(false); }} data-testid="block-all" />
            <span>Block <em>all</em> public access<br /><span className="help">Turning this on is the same as turning on all four settings below it.</span></span></label>
          {!blockAll && (
            <div className="banner warn small">
              <div className="grow">Turning off Block all public access might make this bucket and its objects public.
                <label className="choice" style={{ marginTop: 8 }}><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
                  <span>I acknowledge that the current settings might make this bucket and its objects public.</span></label></div>
            </div>
          )}
        </div>
      </div>

      <div className="panel"><div className="panel-head"><h3>Bucket Versioning</h3></div>
        <div className="panel-body">
          <p className="help" style={{ margin: 0 }}>Versioning keeps multiple variants of an object in the same bucket, so you can recover from unintended actions and failures.</p>
          <label className="choice"><input type="radio" name="ver" checked={versioning === "Disabled"} onChange={() => setVersioning("Disabled")} /> Disable</label>
          <label className="choice"><input type="radio" name="ver" checked={versioning === "Enabled"} onChange={() => setVersioning("Enabled")} /> Enable</label>
        </div>
      </div>

      <div className="panel"><div className="panel-head"><h3>Tags <span className="help">- optional</span></h3></div>
        <div className="panel-body">
          <TagRows tags={tags} setTags={setTags} />
        </div>
      </div>

      <div className="panel disabled"><div className="panel-head"><h3>Default encryption</h3><SimLabel note={features.PutBucketEncryption?.note} /></div>
        <div className="panel-body small muted">Server-side encryption with Amazon S3 managed keys (SSE-S3) is the AWS default. The simulator doesn't model encryption.</div>
      </div>

      <div className="actions">
        <button type="button" onClick={onCancel}>Cancel</button>
        <button className="primary" disabled={busy || (!blockAll && !ack)} data-testid="create-bucket">{busy ? "Creating…" : "Create bucket"}</button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------------------- bucket
type Tab = "objects" | "properties" | "permissions" | "management" | "metrics";
const TABS: [Tab, string][] = [["objects", "Objects"], ["properties", "Properties"], ["permissions", "Permissions"],
  ["management", "Management"], ["metrics", "Metrics"]];

function BucketView({ base, name, features, fail, notify }: {
  base: string; name: string; features: Record<string, Feature>; fail: (e: unknown) => void; notify: Notify;
}) {
  const [tab, setTab] = useState<Tab>("objects");
  const [d, setD] = useState<Details | null>(null);
  const b = `${base}/buckets/${encodeURIComponent(name)}`;
  const load = useCallback(async () => { try { setD(await api<Details>(b)); } catch (e) { fail(e); } }, [b, fail]);
  useEffect(() => { void load(); }, [load]);

  return (
    <div>
      <div className="row" style={{ marginBottom: 10 }}>
        <h2 className="mono" style={{ fontSize: 20 }}>{name}</h2>
        {d && <span className="pill">{d.access}</span>}
      </div>
      <div className="tabs" role="tablist">
        {TABS.map(([t, label]) => (
          <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "tab on" : "tab"} onClick={() => setTab(t)}>{label}</button>
        ))}
      </div>
      {tab === "objects" && <ObjectsTab b={b} fail={fail} notify={notify} />}
      {tab === "properties" && d && <PropertiesTab b={b} d={d} features={features} fail={fail} notify={notify} reload={load} />}
      {tab === "permissions" && d && <PermissionsTab b={b} d={d} features={features} fail={fail} notify={notify} reload={load} />}
      {tab === "management" && (
        <div className="panel disabled"><div className="panel-head"><h3>Lifecycle rules, replication rules and inventory configurations</h3>
          <SimLabel note={features.PutBucketLifecycleConfiguration?.note} /></div>
          <div className="panel-body small muted">{features.PutBucketLifecycleConfiguration?.note ?? "Not simulated."} In AWS, this tab manages object lifecycle transitions and expiration, cross-Region replication and inventory reports.</div></div>
      )}
      {tab === "metrics" && (
        <div className="panel disabled"><div className="panel-head"><h3>Bucket metrics</h3><SimLabel note={features.GetMetricsConfiguration?.note} /></div>
          <div className="panel-body small muted">{features.GetMetricsConfiguration?.note ?? "Not simulated."} In AWS, this tab shows total bucket size, number of objects and request metrics from Amazon CloudWatch.</div></div>
      )}
    </div>
  );
}

function ObjectsTab({ b, fail, notify }: { b: string; fail: (e: unknown) => void; notify: Notify }) {
  const [objs, setObjs] = useState<Obj[] | null>(null);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [uploading, setUploading] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try { setObjs((await api<{ objects: Obj[] }>(`${b}/objects`)).objects); } catch (e) { fail(e); }
  }, [b, fail]);
  useEffect(() => { void load(); }, [load]);

  async function upload() {
    setBusy(true);
    let ok = 0;
    for (const f of files) {
      const form = new FormData();
      form.append("file", f, f.name);
      try { await api(`${b}/objects`, { method: "POST", form }); ok++; } catch (e) { fail(e); }
    }
    setBusy(false);
    if (ok) notify("pass", `Upload succeeded: ${ok} file${ok > 1 ? "s" : ""}.`);
    setFiles([]); setUploading(false);
    await load();
  }

  async function del() {
    for (const key of sel) {
      try { await api(`${b}/objects?key=${encodeURIComponent(key)}`, { method: "DELETE" }); } catch (e) { fail(e); }
    }
    notify("pass", `Deleted ${sel.size} object${sel.size > 1 ? "s" : ""}.`);
    setSel(new Set());
    await load();
  }

  if (uploading) {
    return (
      <div className="panel"><div className="panel-head"><h3>Upload</h3></div>
        <div className="panel-body">
          <p className="help" style={{ margin: 0 }}>Add the files to upload. Each file can be up to 5 MB in the simulator.</p>
          <input type="file" multiple onChange={(e) => setFiles(Array.from(e.target.files ?? []))} data-testid="upload-input" aria-label="Add files" style={{ maxWidth: 420 }} />
          {files.length > 0 && (
            <table className="data"><thead><tr><th>Name</th><th>Type</th><th>Size</th></tr></thead>
              <tbody>{files.map((f) => <tr key={f.name}><td className="mono">{f.name}</td><td className="small">{f.type || "—"}</td><td className="small">{fmtSize(f.size)}</td></tr>)}</tbody></table>
          )}
          <div className="actions">
            <button className="small" onClick={() => { setUploading(false); setFiles([]); }}>Cancel</button>
            <button className="small primary" disabled={!files.length || busy} onClick={() => void upload()} data-testid="confirm-upload">{busy ? "Uploading…" : "Upload"}</button>
          </div>
        </div>
      </div>
    );
  }

  const one = sel.size === 1 ? [...sel][0] : null;
  return (
    <div className="panel">
      <div className="panel-head">
        <h3>Objects <span className="muted">({objs?.length ?? "…"})</span></h3>
        <button className="small" onClick={() => void load()}>Refresh</button>
        {one ? <a className="btn small" href={`${b}/objects/download?key=${encodeURIComponent(one)}`}>Download</a>
          : <button className="small" disabled>Download</button>}
        <button className="small" disabled={!sel.size} onClick={() => void del()}>Delete</button>
        <button className="small primary" onClick={() => setUploading(true)} data-testid="open-upload">Upload</button>
      </div>
      <div className="panel-body" style={{ padding: 0 }}>
        <table className="data">
          <thead><tr><th style={{ width: 36 }} /><th>Name</th><th>Type</th><th>Last modified</th><th>Size</th></tr></thead>
          <tbody>
            {objs?.length === 0 && <tr><td colSpan={5} className="muted">No objects. Choose <strong>Upload</strong> to add files.</td></tr>}
            {objs?.map((o) => (
              <tr key={o.key}>
                <td><input type="checkbox" style={{ width: "auto" }} aria-label={`Select ${o.key}`} checked={sel.has(o.key)}
                  onChange={(e) => { const n = new Set(sel); if (e.target.checked) n.add(o.key); else n.delete(o.key); setSel(n); }} /></td>
                <td className="mono">{o.key}</td>
                <td className="small">{o.key.includes(".") ? o.key.split(".").pop() : "—"}</td>
                <td className="small muted">{fmtDate(o.last_modified)}</td>
                <td className="small">{fmtSize(o.size)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PropertiesTab({ b, d, features, fail, notify, reload }: {
  b: string; d: Details; features: Record<string, Feature>; fail: (e: unknown) => void; notify: Notify; reload: () => Promise<void>;
}) {
  const [editVer, setEditVer] = useState(false);
  const [ver, setVer] = useState<"Enabled" | "Suspended">(d.versioning === "Enabled" ? "Enabled" : "Suspended");
  const [editTags, setEditTags] = useState(false);
  const [tags, setTags] = useState(Object.entries(d.tags).map(([key, value]) => ({ key, value })));

  async function saveVer() {
    try { await api(`${b}/versioning`, { method: "PUT", body: { status: ver } }); setEditVer(false); await reload(); notify("pass", "Successfully edited Bucket Versioning."); }
    catch (e) { fail(e); }
  }
  async function saveTags() {
    const clean = tags.filter((t) => t.key.trim());
    try { await api(`${b}/tags`, { method: "PUT", body: { tags: Object.fromEntries(clean.map((t) => [t.key, t.value])) } });
      setEditTags(false); await reload(); notify("pass", "Successfully edited tags."); }
    catch (e) { fail(e); }
  }

  return (
    <div>
      <div className="panel"><div className="panel-head"><h3>Bucket overview</h3></div>
        <div className="panel-body"><dl className="kv" style={{ margin: 0 }}>
          <div><dt>AWS Region</dt><dd>US East (N. Virginia) {d.region}</dd></div>
          <div><dt>Amazon Resource Name (ARN)</dt><dd className="mono">{d.arn}</dd></div>
        </dl></div></div>

      <div className="panel"><div className="panel-head"><h3>Bucket Versioning</h3>
        {!editVer && <button className="small" onClick={() => setEditVer(true)} data-testid="edit-versioning">Edit</button>}</div>
        <div className="panel-body">
          <div className="small">Bucket Versioning: <span className={`pill ${d.versioning === "Enabled" ? "pass" : ""}`} data-testid="versioning-status">{d.versioning}</span></div>
          {editVer && (
            <>
              <label className="choice"><input type="radio" name="bv" checked={ver === "Suspended"} onChange={() => setVer("Suspended")} /> Suspend</label>
              <label className="choice"><input type="radio" name="bv" checked={ver === "Enabled"} onChange={() => setVer("Enabled")} data-testid="versioning-enable" /> Enable</label>
              <div className="actions"><button className="small" onClick={() => setEditVer(false)}>Cancel</button>
                <button className="small primary" onClick={() => void saveVer()} data-testid="save-versioning">Save changes</button></div>
            </>
          )}
        </div></div>

      <div className="panel"><div className="panel-head"><h3>Tags <span className="muted">({Object.keys(d.tags).length})</span></h3>
        {!editTags && <button className="small" onClick={() => { setTags(Object.entries(d.tags).map(([key, value]) => ({ key, value }))); setEditTags(true); }} data-testid="edit-tags">Edit</button>}</div>
        <div className="panel-body">
          {editTags ? (
            <>
              <TagRows tags={tags} setTags={setTags} />
              <div className="actions"><button className="small" onClick={() => setEditTags(false)}>Cancel</button>
                <button className="small primary" onClick={() => void saveTags()} data-testid="save-tags">Save changes</button></div>
            </>
          ) : Object.keys(d.tags).length === 0 ? <p className="help" style={{ margin: 0 }}>No tags associated with this resource.</p> : (
            <table className="data"><thead><tr><th>Key</th><th>Value</th></tr></thead>
              <tbody>{Object.entries(d.tags).map(([k, v]) => <tr key={k}><td className="mono">{k}</td><td className="mono">{v}</td></tr>)}</tbody></table>
          )}
        </div></div>

      <div className="panel disabled"><div className="panel-head"><h3>Default encryption</h3><SimLabel note={features.PutBucketEncryption?.note} /></div></div>
      <div className="panel disabled"><div className="panel-head"><h3>Static website hosting</h3><SimLabel note={features.PutBucketWebsite?.note} /></div>
        <div className="panel-body small muted">{features.PutBucketWebsite?.note}</div></div>
    </div>
  );
}

function PermissionsTab({ b, d, features, fail, notify, reload }: {
  b: string; d: Details; features: Record<string, Feature>; fail: (e: unknown) => void; notify: Notify; reload: () => Promise<void>;
}) {
  const [editPab, setEditPab] = useState(false);
  const [pab, setPab] = useState<PAB>(d.public_access_block);
  const [editPolicy, setEditPolicy] = useState(false);
  const [policy, setPolicy] = useState(d.policy ?? "");
  const all = Object.values(pab).every(Boolean);
  const LABELS: [keyof PAB, string][] = [
    ["BlockPublicAcls", "Block public access to buckets and objects granted through new access control lists (ACLs)"],
    ["IgnorePublicAcls", "Block public access to buckets and objects granted through any access control lists (ACLs)"],
    ["BlockPublicPolicy", "Block public access to buckets and objects granted through new public bucket or access point policies"],
    ["RestrictPublicBuckets", "Block public and cross-account access to buckets and objects through any public bucket or access point policies"],
  ];

  async function savePab() {
    try {
      await api(`${b}/public-access-block`, { method: "PUT", body: { block_public_acls: pab.BlockPublicAcls,
        ignore_public_acls: pab.IgnorePublicAcls, block_public_policy: pab.BlockPublicPolicy, restrict_public_buckets: pab.RestrictPublicBuckets } });
      setEditPab(false); await reload(); notify("pass", "Successfully edited Block Public Access settings for this bucket.");
    } catch (e) { fail(e); }
  }
  async function savePolicy() {
    try { await api(`${b}/policy`, { method: "PUT", body: { policy } }); setEditPolicy(false); await reload(); notify("pass", "Successfully edited bucket policy."); }
    catch (e) { fail(e); }
  }
  async function deletePolicy() {
    try { await api(`${b}/policy`, { method: "DELETE" }); setPolicy(""); setEditPolicy(false); await reload(); notify("pass", "Successfully deleted bucket policy."); }
    catch (e) { fail(e); }
  }

  return (
    <div>
      <div className="panel"><div className="panel-head"><h3>Block public access (bucket settings)</h3>
        {!editPab && <button className="small" onClick={() => { setPab(d.public_access_block); setEditPab(true); }}>Edit</button>}</div>
        <div className="panel-body">
          {editPab ? (
            <>
              <label className="choice"><input type="checkbox" checked={all} onChange={(e) => setPab({ BlockPublicAcls: e.target.checked,
                IgnorePublicAcls: e.target.checked, BlockPublicPolicy: e.target.checked, RestrictPublicBuckets: e.target.checked })} />
                <strong>Block <em>all</em> public access</strong></label>
              {LABELS.map(([k, l]) => (
                <label key={k} className="choice" style={{ marginLeft: 22 }}><input type="checkbox" checked={pab[k]} onChange={(e) => setPab({ ...pab, [k]: e.target.checked })} />
                  <span className="small">{l}</span></label>
              ))}
              <div className="actions"><button className="small" onClick={() => setEditPab(false)}>Cancel</button>
                <button className="small primary" onClick={() => void savePab()}>Save changes</button></div>
            </>
          ) : (
            <div className="small">Block <em>all</em> public access: <span className={`pill ${Object.values(d.public_access_block).every(Boolean) ? "pass" : "warn"}`}>
              {Object.values(d.public_access_block).every(Boolean) ? "On" : "Off"}</span></div>
          )}
        </div></div>

      <div className="panel"><div className="panel-head"><h3>Bucket policy</h3>
        {!editPolicy && <button className="small" onClick={() => { setPolicy(d.policy ?? ""); setEditPolicy(true); }}>Edit</button>}
        {!editPolicy && d.policy && <button className="small danger" onClick={() => void deletePolicy()}>Delete</button>}</div>
        <div className="panel-body">
          <p className="help" style={{ margin: 0 }}>The bucket policy, written in JSON, provides access to the objects stored in the bucket.</p>
          {editPolicy ? (
            <>
              <textarea className="mono" rows={12} value={policy} onChange={(e) => setPolicy(e.target.value)} aria-label="Bucket policy JSON"
                placeholder={'{\n  "Version": "2012-10-17",\n  "Statement": []\n}'} />
              <div className="actions"><button className="small" onClick={() => setEditPolicy(false)}>Cancel</button>
                <button className="small primary" onClick={() => void savePolicy()}>Save changes</button></div>
            </>
          ) : d.policy ? <pre className="mono small" style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(JSON.parse(d.policy), null, 2)}</pre>
            : <p className="small muted" style={{ margin: 0 }}>No policy to display.</p>}
        </div></div>

      <div className="panel"><div className="panel-head"><h3>Object Ownership</h3></div>
        <div className="panel-body small">Bucket owner enforced. ACLs are disabled and all objects are owned by this account.
          <div className="row">ACLs enabled <SimLabel note={features.PutBucketAcl?.note} /></div></div></div>
    </div>
  );
}
