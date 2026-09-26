"use client";
// Student DynamoDB console (PLAN console fidelity principle): Tables → Create table → table tabs →
// Explore table items → Create item, with AWS terminology. Talks only to CloudLabs FastAPI endpoints.
//
// Adapted from Floci UI (MIT, https://github.com/floci-io/floci-ui — see THIRD_PARTY_NOTICES.md):
// table-name validation rule, partition/sort key form model, 100-item explore cap and attribute
// type handling follow AwsDynamoDbAdapter.ts / DynamoDbTableExplorer.tsx. UI, layout, wording and the
// API boundary are CloudLabs' own.
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { type Feature, FlashBanner, type Notify, SimLabel, TagRows, useFlash } from "./console-kit";

type KeyAttr = { name: string; type: "S" | "N" | "B" };
type TableRow = { name: string; status: string; partition_key: KeyAttr; sort_key: KeyAttr | null;
  billing_mode: string; item_count: number };
type TableDetail = TableRow & { arn: string; created_at: string | null; read_capacity: number | null;
  write_capacity: number | null; tags: Record<string, string> };
type Attr = { name: string; type: "S" | "N" | "BOOL" | "NULL" | "L" | "M" | "SS" | "NS" | "B"; value: unknown };
type Item = Attr[];
type Items = { items: Item[]; key_names: string[]; count: number; truncated: boolean };

// Floci UI rule: 3–255 characters of letters, numbers, underscores, dots or hyphens.
const TABLE_NAME = "[A-Za-z0-9_.\\-]{3,255}";
const TYPE_LABEL: Record<string, string> = { S: "String", N: "Number", B: "Binary", BOOL: "Boolean", NULL: "Null",
  L: "List", M: "Map", SS: "String set", NS: "Number set" };
const billingLabel = (m: string) => (m === "PAY_PER_REQUEST" ? "On-demand" : "Provisioned");

function show(a: Attr): string {
  if (a.type === "S" || a.type === "N") return String(a.value);
  return JSON.stringify(a.value);
}

export function DynamoDbConsole({ sessionId, readOnly, features }: {
  sessionId: string; readOnly: boolean; features: Record<string, Feature>;
}) {
  const base = `/api/sessions/${sessionId}/console/dynamodb`;
  const [view, setView] = useState<{ page: "list" } | { page: "create" } | { page: "table"; name: string }>({ page: "list" });
  const { flash, notify, fail, clear } = useFlash();

  return (
    <section className="svc-main">
      <div className="crumbs small" aria-label="Breadcrumb">
        <button className="linklike" onClick={() => setView({ page: "list" })}>DynamoDB</button><span>›</span>
        <button className="linklike" onClick={() => setView({ page: "list" })}>Tables</button>
        {view.page === "create" && <><span>›</span><span>Create table</span></>}
        {view.page === "table" && <><span>›</span><span className="mono">{view.name}</span></>}
      </div>
      <FlashBanner flash={flash} onClose={clear} />
      {readOnly ? (
        <div className="banner info">This lab is submitted or not running, so the console is read-only.</div>
      ) : view.page === "list" ? (
        <TableList base={base} onOpen={(name) => setView({ page: "table", name })} onCreate={() => setView({ page: "create" })}
          fail={fail} notify={notify} />
      ) : view.page === "create" ? (
        <CreateTable base={base} features={features} fail={fail} onCancel={() => setView({ page: "list" })}
          onDone={(name) => { notify("pass", `The ${name} table was created successfully.`); setView({ page: "list" }); }} />
      ) : (
        <TableView base={base} name={view.name} features={features} fail={fail} notify={notify} />
      )}
    </section>
  );
}

function TableList({ base, onOpen, onCreate, fail, notify }: {
  base: string; onOpen: (n: string) => void; onCreate: () => void; fail: (e: unknown) => void; notify: Notify;
}) {
  const [tables, setTables] = useState<TableRow[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [confirm, setConfirm] = useState("");
  const [deleting, setDeleting] = useState(false);
  const load = useCallback(async () => {
    try { setTables((await api<{ tables: TableRow[] }>(`${base}/tables`)).tables); } catch (e) { fail(e); }
  }, [base, fail]);
  useEffect(() => { void load(); }, [load]);

  async function del() {
    try { await api(`${base}/tables/${encodeURIComponent(selected!)}`, { method: "DELETE" });
      setDeleting(false); setConfirm(""); setSelected(null); await load(); notify("pass", "The table was deleted."); }
    catch (e) { fail(e); }
  }

  return (
    <div>
      <h2 style={{ marginBottom: 12 }}>DynamoDB</h2>
      <div className="panel">
        <div className="panel-head">
          <h3>Tables <span className="muted">({tables?.length ?? "…"})</span></h3>
          <button className="small" onClick={() => void load()}>Refresh</button>
          <button className="small" disabled={!selected} onClick={() => setDeleting(true)}>Delete</button>
          <button className="small primary" onClick={onCreate} data-testid="open-create-table">Create table</button>
        </div>
        <div className="panel-body" style={{ padding: 0 }}>
          <table className="data">
            <thead><tr><th style={{ width: 36 }} /><th>Name</th><th>Status</th><th>Partition key</th><th>Sort key</th><th>Read/write capacity mode</th></tr></thead>
            <tbody>
              {tables?.length === 0 && <tr><td colSpan={6} className="muted">You have no tables. Choose <strong>Create table</strong>, or run <code>aws dynamodb create-table</code> in the terminal.</td></tr>}
              {tables?.map((t) => (
                <tr key={t.name}>
                  <td><input type="radio" name="table-select" style={{ width: "auto" }} aria-label={`Select ${t.name}`} checked={selected === t.name} onChange={() => setSelected(t.name)} /></td>
                  <td><button className="linklike mono" onClick={() => onOpen(t.name)}>{t.name}</button></td>
                  <td><span className={`pill ${t.status === "ACTIVE" ? "pass" : ""}`}>{t.status === "ACTIVE" ? "Active" : t.status}</span></td>
                  <td className="mono small">{t.partition_key.name} ({t.partition_key.type})</td>
                  <td className="mono small">{t.sort_key ? `${t.sort_key.name} (${t.sort_key.type})` : "-"}</td>
                  <td className="small">{billingLabel(t.billing_mode)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {deleting && selected && (
        <div className="panel"><div className="panel-head"><h3>Delete table</h3></div>
          <div className="panel-body">
            <p className="small" style={{ margin: 0 }}>All items in the table are deleted. To confirm, type <strong>confirm</strong>.</p>
            <input value={confirm} onChange={(e) => setConfirm(e.target.value)} aria-label="Type confirm" style={{ maxWidth: 240 }} />
            <div className="actions"><button className="small" onClick={() => { setDeleting(false); setConfirm(""); }}>Cancel</button>
              <button className="small danger" disabled={confirm !== "confirm"} onClick={() => void del()}>Delete</button></div>
          </div></div>
      )}
    </div>
  );
}

function KeyInput({ label, help, value, onChange, testid, optional = false }: {
  label: string; help: string; value: KeyAttr; onChange: (k: KeyAttr) => void; testid: string; optional?: boolean;
}) {
  return (
    <label>{label}{optional && <span className="help"> - optional</span>}
      <div className="row">
        <input className="mono" style={{ maxWidth: 300 }} value={value.name} required={!optional} placeholder="Enter the attribute name"
          onChange={(e) => onChange({ ...value, name: e.target.value })} data-testid={testid} />
        <select value={value.type} onChange={(e) => onChange({ ...value, type: e.target.value as KeyAttr["type"] })} style={{ width: 130 }}
          aria-label={`${label} type`}>
          <option value="S">String</option><option value="N">Number</option><option value="B">Binary</option>
        </select>
      </div>
      <span className="help">{help}</span>
    </label>
  );
}

function CreateTable({ base, features, fail, onDone, onCancel }: {
  base: string; features: Record<string, Feature>; fail: (e: unknown) => void; onDone: (n: string) => void; onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [pk, setPk] = useState<KeyAttr>({ name: "", type: "S" });
  const [sk, setSk] = useState<KeyAttr>({ name: "", type: "S" });
  const [custom, setCustom] = useState(false);
  const [mode, setMode] = useState<"PAY_PER_REQUEST" | "PROVISIONED">("PROVISIONED");
  const [rcu, setRcu] = useState(5);
  const [wcu, setWcu] = useState(5);
  const [tags, setTags] = useState<{ key: string; value: string }[]>([]);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      // AWS "Default settings" = provisioned 5/5; "Customize settings" exposes the capacity mode.
      await api(`${base}/tables`, { method: "POST", body: {
        name: name.trim(), partition_key: pk, sort_key: sk.name.trim() ? sk : null,
        billing_mode: custom ? mode : "PROVISIONED", read_capacity: custom && mode === "PAY_PER_REQUEST" ? null : rcu,
        write_capacity: custom && mode === "PAY_PER_REQUEST" ? null : wcu, tags: tags.filter((t) => t.key.trim()) } });
      onDone(name.trim());
    } catch (err) { fail(err); } finally { setBusy(false); }
  }

  return (
    <form onSubmit={submit}>
      <h2 style={{ marginBottom: 12 }}>Create table</h2>
      <div className="panel"><div className="panel-head"><h3>Table details</h3></div>
        <div className="panel-body">
          <p className="help" style={{ margin: 0 }}>DynamoDB is a schemaless database that only requires a table name and a primary key when you create the table.</p>
          <label>Table name
            <input className="mono" value={name} onChange={(e) => setName(e.target.value)} required pattern={TABLE_NAME} style={{ maxWidth: 420 }}
              title="3–255 characters: letters, numbers, underscores (_), hyphens (-) and periods (.)" data-testid="new-table-name" />
            <span className="help">Between 3 and 255 characters, containing only letters, numbers, underscores (_), hyphens (-), and periods (.).</span>
          </label>
          <KeyInput label="Partition key" value={pk} onChange={setPk} testid="partition-key"
            help="The partition key is part of the table's primary key. It is a hash value used to retrieve items and allocate data across hosts." />
          <KeyInput label="Sort key" value={sk} onChange={setSk} testid="sort-key" optional
            help="You can use a sort key as the second part of a table's primary key." />
        </div></div>

      <div className="panel"><div className="panel-head"><h3>Table settings</h3></div>
        <div className="panel-body">
          <label className="choice"><input type="radio" name="settings" checked={!custom} onChange={() => setCustom(false)} />
            <span>Default settings<br /><span className="help">The fastest way to create your table. Provisioned capacity with 5 read and 5 write units.</span></span></label>
          <label className="choice"><input type="radio" name="settings" checked={custom} onChange={() => setCustom(true)} data-testid="customize-settings" />
            <span>Customize settings<br /><span className="help">Choose the capacity mode and other options.</span></span></label>
        </div></div>

      {custom && (
        <div className="panel"><div className="panel-head"><h3>Read/write capacity settings</h3></div>
          <div className="panel-body">
            <label className="choice"><input type="radio" name="mode" checked={mode === "PAY_PER_REQUEST"} onChange={() => setMode("PAY_PER_REQUEST")} data-testid="mode-on-demand" />
              <span>On-demand<br /><span className="help">Simplify billing by paying for the actual reads and writes your application performs.</span></span></label>
            <label className="choice"><input type="radio" name="mode" checked={mode === "PROVISIONED"} onChange={() => setMode("PROVISIONED")} />
              <span>Provisioned<br /><span className="help">Manage and optimize your costs by allocating read/write capacity in advance.</span></span></label>
            {mode === "PROVISIONED" && (
              <div className="row">
                <label style={{ width: 160 }}>Read capacity units<input type="number" min={1} max={1000} value={rcu} onChange={(e) => setRcu(Number(e.target.value))} /></label>
                <label style={{ width: 160 }}>Write capacity units<input type="number" min={1} max={1000} value={wcu} onChange={(e) => setWcu(Number(e.target.value))} /></label>
              </div>
            )}
          </div></div>
      )}

      <div className="panel"><div className="panel-head"><h3>Tags <span className="help">- optional</span></h3></div>
        <div className="panel-body"><TagRows tags={tags} setTags={setTags} /></div></div>
      <div className="panel disabled"><div className="panel-head"><h3>Secondary indexes</h3><SimLabel note={features.CreateGlobalSecondaryIndex?.note} /></div></div>
      <div className="panel disabled"><div className="panel-head"><h3>Encryption at rest</h3><SimLabel note={features.UpdateTableEncryption?.note} /></div></div>

      <div className="actions">
        <button type="button" onClick={onCancel}>Cancel</button>
        <button className="primary" disabled={busy} data-testid="create-table">{busy ? "Creating…" : "Create table"}</button>
      </div>
    </form>
  );
}

type Tab = "overview" | "items" | "indexes" | "monitor" | "backups";
const TABS: [Tab, string][] = [["overview", "Overview"], ["items", "Explore items"], ["indexes", "Indexes"],
  ["monitor", "Monitor"], ["backups", "Backups"]];

function TableView({ base, name, features, fail, notify }: {
  base: string; name: string; features: Record<string, Feature>; fail: (e: unknown) => void; notify: Notify;
}) {
  const [tab, setTab] = useState<Tab>("overview");
  const [d, setD] = useState<TableDetail | null>(null);
  const t = `${base}/tables/${encodeURIComponent(name)}`;
  const load = useCallback(async () => { try { setD(await api<TableDetail>(t)); } catch (e) { fail(e); } }, [t, fail]);
  useEffect(() => { void load(); }, [load]);

  return (
    <div>
      <div className="row" style={{ marginBottom: 10 }}>
        <h2 className="mono" style={{ fontSize: 20 }}>{name}</h2>
        {d && <span className="pill pass">Active</span>}
        <span className="grow" />
        <button className="small primary" onClick={() => setTab("items")} data-testid="explore-items">Explore table items</button>
      </div>
      <div className="tabs" role="tablist">
        {TABS.map(([k, label]) => <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "tab on" : "tab"} onClick={() => setTab(k)}>{label}</button>)}
      </div>
      {tab === "overview" && d && <Overview t={t} d={d} fail={fail} notify={notify} reload={load} />}
      {tab === "items" && d && <ItemsTab t={t} d={d} fail={fail} notify={notify} />}
      {tab === "indexes" && <div className="panel disabled"><div className="panel-head"><h3>Global secondary indexes</h3><SimLabel note={features.CreateGlobalSecondaryIndex?.note} /></div>
        <div className="panel-body small muted">In AWS, indexes let you query the table by other attributes.</div></div>}
      {tab === "monitor" && <div className="panel disabled"><div className="panel-head"><h3>CloudWatch metrics and alarms</h3><SimLabel /></div>
        <div className="panel-body small muted">In AWS, this tab shows consumed capacity, throttled requests and latency.</div></div>}
      {tab === "backups" && <div className="panel disabled"><div className="panel-head"><h3>Point-in-time recovery and on-demand backups</h3><SimLabel /></div></div>}
    </div>
  );
}

function Overview({ t, d, fail, notify, reload }: { t: string; d: TableDetail; fail: (e: unknown) => void; notify: Notify; reload: () => Promise<void> }) {
  const [edit, setEdit] = useState(false);
  const [mode, setMode] = useState(d.billing_mode);
  const [rcu, setRcu] = useState(d.read_capacity ?? 5);
  const [wcu, setWcu] = useState(d.write_capacity ?? 5);

  async function save() {
    try {
      await api(`${t}/capacity`, { method: "PUT", body: { billing_mode: mode,
        read_capacity: mode === "PROVISIONED" ? rcu : null, write_capacity: mode === "PROVISIONED" ? wcu : null } });
      setEdit(false); await reload(); notify("pass", "The capacity settings were updated.");
    } catch (e) { fail(e); }
  }

  return (
    <div>
      <div className="panel"><div className="panel-head"><h3>General information</h3></div>
        <div className="panel-body"><dl className="kv" style={{ margin: 0 }}>
          <div><dt>Partition key</dt><dd className="mono">{d.partition_key.name} ({TYPE_LABEL[d.partition_key.type]})</dd></div>
          <div><dt>Sort key</dt><dd className="mono">{d.sort_key ? `${d.sort_key.name} (${TYPE_LABEL[d.sort_key.type]})` : "-"}</dd></div>
          <div><dt>Capacity mode</dt><dd data-testid="capacity-mode">{billingLabel(d.billing_mode)}</dd></div>
          <div><dt>Item count</dt><dd>{d.item_count}</dd></div>
          <div><dt>Amazon Resource Name (ARN)</dt><dd className="mono small">{d.arn}</dd></div>
          <div><dt>Creation date</dt><dd>{fmtDate(d.created_at)}</dd></div>
        </dl></div></div>
      <div className="panel"><div className="panel-head"><h3>Read/write capacity</h3>
        {!edit && <button className="small" onClick={() => setEdit(true)} data-testid="edit-capacity">Edit</button>}</div>
        <div className="panel-body">
          {!edit ? (
            <div className="small">Capacity mode: <strong>{billingLabel(d.billing_mode)}</strong>
              {d.billing_mode === "PROVISIONED" && <> · {d.read_capacity} read / {d.write_capacity} write units</>}</div>
          ) : (
            <>
              <label className="choice"><input type="radio" name="edit-mode" checked={mode === "PAY_PER_REQUEST"} onChange={() => setMode("PAY_PER_REQUEST")} data-testid="edit-mode-on-demand" /> On-demand</label>
              <label className="choice"><input type="radio" name="edit-mode" checked={mode === "PROVISIONED"} onChange={() => setMode("PROVISIONED")} /> Provisioned</label>
              {mode === "PROVISIONED" && <div className="row">
                <label style={{ width: 160 }}>Read capacity units<input type="number" min={1} value={rcu} onChange={(e) => setRcu(Number(e.target.value))} /></label>
                <label style={{ width: 160 }}>Write capacity units<input type="number" min={1} value={wcu} onChange={(e) => setWcu(Number(e.target.value))} /></label></div>}
              <div className="actions"><button className="small" onClick={() => setEdit(false)}>Cancel</button>
                <button className="small primary" onClick={() => void save()} data-testid="save-capacity">Save changes</button></div>
            </>
          )}
        </div></div>
    </div>
  );
}

function ItemsTab({ t, d, fail, notify }: { t: string; d: TableDetail; fail: (e: unknown) => void; notify: Notify }) {
  const [data, setData] = useState<Items | null>(null);
  const [creating, setCreating] = useState(false);
  const [attrs, setAttrs] = useState<{ name: string; type: "S" | "N" | "BOOL"; value: string }[]>([]);
  const keys = [d.partition_key, ...(d.sort_key ? [d.sort_key] : [])];
  const load = useCallback(async () => { try { setData(await api<Items>(`${t}/items`)); } catch (e) { fail(e); } }, [t, fail]);
  useEffect(() => { void load(); }, [load]);

  function startCreate() {
    setAttrs(keys.map((k) => ({ name: k.name, type: k.type === "N" ? "N" : "S", value: "" })));
    setCreating(true);
  }

  async function save(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api(`${t}/items`, { method: "POST", body: { attributes: attrs.filter((a) => a.name.trim()) } });
      setCreating(false); await load(); notify("pass", "The item has been saved successfully.");
    } catch (err) { fail(err); }
  }

  async function del(item: Item) {
    const key = Object.fromEntries(item.filter((a) => data!.key_names.includes(a.name)).map((a) => [a.name, { type: a.type, value: a.value }]));
    try { await api(`${t}/items/delete`, { method: "POST", body: { key } }); await load(); notify("pass", "The item was deleted."); }
    catch (err) { fail(err); }
  }

  if (creating) {
    return (
      <form className="panel" onSubmit={save}>
        <div className="panel-head"><h3>Create item</h3></div>
        <div className="panel-body">
          <p className="help" style={{ margin: 0 }}>Add attributes. The primary key attributes are required.</p>
          <table className="data">
            <thead><tr><th>Attribute name</th><th>Value</th><th>Type</th><th /></tr></thead>
            <tbody>{attrs.map((a, i) => {
              const isKey = i < keys.length;
              return (
                <tr key={i}>
                  <td>{isKey ? <span className="mono">{a.name} <span className="pill">{i === 0 ? "Partition key" : "Sort key"}</span></span>
                    : <input className="mono" value={a.name} aria-label="Attribute name" onChange={(e) => setAttrs(attrs.map((x, j) => j === i ? { ...x, name: e.target.value } : x))} />}</td>
                  <td>{a.type === "BOOL"
                    ? <select value={a.value || "true"} aria-label={`Value of ${a.name || "attribute"}`} onChange={(e) => setAttrs(attrs.map((x, j) => j === i ? { ...x, value: e.target.value } : x))}><option>true</option><option>false</option></select>
                    : <input className="mono" value={a.value} required={isKey} aria-label={`Value of ${a.name || "attribute"}`} inputMode={a.type === "N" ? "decimal" : undefined}
                        onChange={(e) => setAttrs(attrs.map((x, j) => j === i ? { ...x, value: e.target.value } : x))} />}</td>
                  <td>{isKey ? TYPE_LABEL[a.type] : (
                    <select value={a.type} aria-label={`Type of ${a.name || "attribute"}`} onChange={(e) => setAttrs(attrs.map((x, j) => j === i ? { ...x, type: e.target.value as "S" | "N" | "BOOL" } : x))}>
                      <option value="S">String</option><option value="N">Number</option><option value="BOOL">Boolean</option></select>)}</td>
                  <td>{!isKey && <button type="button" className="small ghost" onClick={() => setAttrs(attrs.filter((_, j) => j !== i))}>Remove</button>}</td>
                </tr>);
            })}</tbody>
          </table>
          <div><button type="button" className="small" onClick={() => setAttrs([...attrs, { name: "", type: "S", value: "" }])} data-testid="add-attribute">Add new attribute</button></div>
          <div className="actions"><button type="button" className="small" onClick={() => setCreating(false)}>Cancel</button>
            <button className="small primary" data-testid="save-item">Create item</button></div>
        </div>
      </form>
    );
  }

  const columns = data ? Array.from(new Set(data.items.flatMap((it) => it.map((a) => a.name))))
    .sort((a, b) => (data.key_names.indexOf(a) + 1 || 99) - (data.key_names.indexOf(b) + 1 || 99)) : [];
  return (
    <div className="panel">
      <div className="panel-head">
        <h3>Items returned <span className="muted">({data?.count ?? "…"}{data?.truncated ? "+" : ""})</span></h3>
        <button className="small" onClick={() => void load()}>Refresh</button>
        <button className="small primary" onClick={startCreate} data-testid="create-item">Create item</button>
      </div>
      <div className="panel-body" style={{ padding: 0, overflowX: "auto" }}>
        <table className="data">
          <thead><tr>{columns.map((c) => <th key={c} className="mono" style={{ textTransform: "none" }}>{c}</th>)}<th /></tr></thead>
          <tbody>
            {data?.items.length === 0 && <tr><td colSpan={columns.length + 1} className="muted">The table is empty. Choose <strong>Create item</strong>.</td></tr>}
            {data?.items.map((it, i) => (
              <tr key={i} data-testid="item-row">
                {columns.map((c) => { const a = it.find((x) => x.name === c); return (
                  <td key={c} className="mono small">{a ? <>{show(a)} <span className="muted" title={TYPE_LABEL[a.type]}>{a.type}</span></> : ""}</td>); })}
                <td style={{ textAlign: "right" }}><button className="small danger" onClick={() => void del(it)}>Delete</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        {data?.truncated && <p className="help" style={{ padding: "8px 12px", margin: 0 }}>Showing the first 100 items.</p>}
      </div>
    </div>
  );
}
