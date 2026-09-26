"use client";
// Student Lambda console (PLAN console fidelity principle): Functions, Create function (Author from
// scratch), and a function page with Code (editor + Deploy), Test, Configuration and Monitor tabs.
// Test needs an engine that executes code (feature Invoke); otherwise it is labelled unavailable.
// Talks only to CloudLabs FastAPI endpoints.
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { type Feature, FlashBanner, type Notify, SimLabel, fmtSize, useFlash } from "./console-kit";

type Fn = { name: string; runtime: string | null; handler: string | null; role: string | null; memory: number | null;
  timeout: number | null; architecture: string; last_modified: string | null; env: Record<string, string>; code_size: number | null };
type FnDetail = Fn & { files: Record<string, string> | null; code_available: boolean };
type InvokeOut = { status_code: number | null; function_error: string | null; response: unknown; duration_ms: number };
type View = { page: "list" | "create" | "detail"; name?: string };
type Ctx = { base: string; fail: (e: unknown) => void; notify: Notify; go: (v: View) => void; features: Record<string, Feature> };

const RUNTIMES = [{ id: "python3.12", label: "Python 3.12" }, { id: "nodejs20.x", label: "Node.js 20.x" }];
const usable = (f: Record<string, Feature>, op: string) => ["supported", "simulated"].includes(f[op]?.level ?? "");

export function LambdaConsole({ sessionId, readOnly, features }: { sessionId: string; readOnly: boolean; features: Record<string, Feature> }) {
  const base = `/api/sessions/${sessionId}/console/lambda`;
  const [view, setView] = useState<View>({ page: "list" });
  const { flash, notify, fail, clear } = useFlash();
  const ctx: Ctx = { base, fail, notify, go: setView, features };
  return (
    <section className="svc-main">
      <div className="crumbs small" aria-label="Breadcrumb">
        <button className="linklike" onClick={() => setView({ page: "list" })}>Lambda</button><span>›</span>
        <button className="linklike" onClick={() => setView({ page: "list" })}>Functions</button>
        {view.page === "create" && <><span>›</span><span>Create function</span></>}
        {view.page === "detail" && <><span>›</span><span className="mono">{view.name}</span></>}
      </div>
      <FlashBanner flash={flash} onClose={clear} />
      {readOnly ? <div className="banner info">This lab is submitted or not running, so the console is read-only.</div>
        : view.page === "list" ? <FunctionList {...ctx} />
        : view.page === "create" ? <CreateFunction {...ctx} />
        : <FunctionPage {...ctx} name={view.name!} />}
    </section>
  );
}

// -------------------------------------------------------------------------------------- functions
function FunctionList(ctx: Ctx) {
  const [items, setItems] = useState<Fn[] | null>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const load = useCallback(async () => { try { setItems((await api<{ functions: Fn[] }>(`${ctx.base}/functions`)).functions); } catch (e) { ctx.fail(e); } }, [ctx.base, ctx.fail]);
  useEffect(() => { void load(); }, [load]);
  async function remove() {
    if (!sel || prompt(`Delete ${sel}? To confirm deletion, type confirm.`) !== "confirm") return;
    try { await api(`${ctx.base}/functions/${sel}`, { method: "DELETE" }); ctx.notify("pass", `Successfully deleted function ${sel}.`); setSel(null); await load(); } catch (e) { ctx.fail(e); }
  }
  const shown = items?.filter((f) => f.name.toLowerCase().includes(filter.toLowerCase()));
  return (
    <div className="panel">
      <div className="panel-head">
        <h3>Functions <span className="muted">({items?.length ?? "…"})</span></h3>
        <button className="small" onClick={() => void load()}>Refresh</button>
        <button className="small" disabled={!sel} onClick={() => void remove()} data-testid="delete-function">Delete</button>
        <button className="small primary" onClick={() => ctx.go({ page: "create" })} data-testid="open-create-function">Create function</button>
      </div>
      <div className="panel-body" style={{ paddingBottom: 0 }}>
        <input placeholder="Filter by function name" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter functions" style={{ maxWidth: 360 }} />
      </div>
      <div className="panel-body" style={{ padding: 0, overflowX: "auto" }}>
        <table className="data">
          <thead><tr><th style={{ width: 36 }} /><th>Function name</th><th>Package type</th><th>Runtime</th><th>Memory</th><th>Last modified</th></tr></thead>
          <tbody>
            {shown?.length === 0 && <tr><td colSpan={6} className="muted">There are no functions. Choose <strong>Create function</strong>, or run <code>aws lambda create-function</code>.</td></tr>}
            {shown?.map((f) => (
              <tr key={f.name} data-testid="function-row">
                <td><input type="radio" name="fn" style={{ width: "auto" }} aria-label={`Select ${f.name}`} checked={sel === f.name} onChange={() => setSel(f.name)} /></td>
                <td><button className="linklike mono small" onClick={() => ctx.go({ page: "detail", name: f.name })}>{f.name}</button></td>
                <td className="small">Zip</td>
                <td className="small">{RUNTIMES.find((r) => r.id === f.runtime)?.label ?? f.runtime}</td>
                <td className="small">{f.memory} MB</td>
                <td className="small">{f.last_modified ? fmtDate(f.last_modified) : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CreateFunction(ctx: Ctx) {
  const [name, setName] = useState("");
  const [runtime, setRuntime] = useState("python3.12");
  const [roleMode, setRoleMode] = useState<"create" | "existing">("create");
  const [roles, setRoles] = useState<{ name: string; arn: string }[]>([]);
  const [role, setRole] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    void api<{ roles: { name: string; arn: string }[] }>(`${ctx.base}/execution-roles`).then((r) => { setRoles(r.roles); setRole(r.roles[0]?.arn ?? ""); }).catch(() => undefined);
  }, [ctx.base]);
  const valid = /^[A-Za-z0-9_-]{1,64}$/.test(name) && (roleMode === "create" || role);
  async function create() {
    setBusy(true);
    try {
      await api(`${ctx.base}/functions`, { method: "POST", body: { name, runtime, architecture: "x86_64", role_mode: roleMode, role_arn: roleMode === "existing" ? role : null } });
      ctx.notify("pass", `Successfully created the function ${name}. You can now change its code and configuration.`);
      ctx.go({ page: "detail", name });
    } catch (e) { ctx.fail(e); } finally { setBusy(false); }
  }
  return (
    <div style={{ maxWidth: 760 }}>
      <h2 style={{ marginBottom: 12 }}>Create function</h2>
      <div className="panel"><div className="panel-body">
        <label className="choice"><input type="radio" checked readOnly /> <span>Author from scratch<div className="help">Start with a simple Hello World example.</div></span></label>
        <label className="choice off"><input type="radio" disabled /> <span>Use a blueprint <SimLabel note="Blueprints are not available in the simulator." /></span></label>
        <label className="choice off"><input type="radio" disabled /> <span>Container image <SimLabel note="Container image functions are not available in the simulator." /></span></label>
      </div></div>
      <div className="panel"><div className="panel-head"><h3>Basic information</h3></div><div className="panel-body">
        <label>Function name<input className="mono" value={name} onChange={(e) => setName(e.target.value)} placeholder="myFunctionName" style={{ maxWidth: 420 }} data-testid="function-name" />
          <span className="help">Function names can contain letters, numbers, hyphens and underscores, up to 64 characters.</span></label>
        <label>Runtime<select value={runtime} onChange={(e) => setRuntime(e.target.value)} style={{ maxWidth: 320 }} data-testid="function-runtime">
          {RUNTIMES.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}</select>
          <span className="help">Choose the language to use to write your function.</span></label>
        <div className="small" style={{ fontWeight: 600 }}>Architecture</div>
        <label className="choice"><input type="radio" checked readOnly /> x86_64</label>
        <label className="choice off"><input type="radio" disabled /> <span>arm64 <SimLabel note="Only x86_64 is simulated." /></span></label>
      </div></div>
      <div className="panel"><div className="panel-head"><h3>Change default execution role</h3></div><div className="panel-body">
        <span className="help">The execution role defines the permissions your function has when it runs.</span>
        <label className="choice"><input type="radio" checked={roleMode === "create"} onChange={() => setRoleMode("create")} /> Create a new role with basic Lambda permissions</label>
        <label className="choice"><input type="radio" checked={roleMode === "existing"} onChange={() => setRoleMode("existing")} disabled={roles.length === 0} /> Use an existing role</label>
        {roleMode === "existing" && (
          <select value={role} onChange={(e) => setRole(e.target.value)} style={{ maxWidth: 420, marginLeft: 22 }} aria-label="Existing role">
            {roles.map((r) => <option key={r.arn} value={r.arn}>{r.name}</option>)}</select>)}
        {roleMode === "create" && <span className="help" style={{ marginLeft: 22 }}>Lambda will create an execution role named <span className="mono">{name || "<function-name>"}-role-xxxxxxxx</span>.</span>}
      </div></div>
      <div className="actions">
        <button onClick={() => ctx.go({ page: "list" })}>Cancel</button>
        <button className="primary" disabled={!valid || busy} onClick={() => void create()} data-testid="create-function">{busy ? "Creating…" : "Create function"}</button>
      </div>
    </div>
  );
}

// -------------------------------------------------------------------------------------- function page
type Tab = "code" | "test" | "config" | "monitor";

function FunctionPage(ctx: Ctx & { name: string }) {
  const [fn, setFn] = useState<FnDetail | null>(null);
  const [tab, setTab] = useState<Tab>("code");
  const load = useCallback(async () => {
    try { setFn(await api<FnDetail>(`${ctx.base}/functions/${ctx.name}`)); } catch (e) { ctx.fail(e); }
  }, [ctx.base, ctx.name, ctx.fail]);
  useEffect(() => { void load(); }, [load]);
  if (!fn) return <p className="muted small">Loading function…</p>;
  return (
    <div>
      <h2 style={{ marginBottom: 12 }} className="mono">{fn.name}</h2>
      <div className="panel"><div className="panel-head"><h3>Function overview</h3></div><div className="panel-body">
        <dl className="kv" style={{ margin: 0 }}>
          <div><dt>Runtime</dt><dd>{RUNTIMES.find((r) => r.id === fn.runtime)?.label ?? fn.runtime}</dd></div>
          <div><dt>Handler</dt><dd className="mono small">{fn.handler}</dd></div>
          <div><dt>Last modified</dt><dd className="small">{fn.last_modified ? fmtDate(fn.last_modified) : "-"}</dd></div>
          <div><dt>Function ARN</dt><dd className="mono small">arn:aws:lambda:us-east-1:000000000000:function:{fn.name}</dd></div>
        </dl>
      </div></div>
      <div className="tabs" role="tablist" aria-label="Function">
        {(["code", "test", "config", "monitor"] as Tab[]).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "tab on" : "tab"} onClick={() => { setTab(t); void load(); }} data-testid={`lambda-tab-${t}`}>
            {{ code: "Code", test: "Test", config: "Configuration", monitor: "Monitor" }[t]}</button>))}
      </div>
      {tab === "code" && <CodeTab {...ctx} fn={fn} reload={load} />}
      {tab === "test" && <TestTab {...ctx} fn={fn} />}
      {tab === "config" && <ConfigTab key={`${fn.last_modified}|${fn.memory}|${fn.timeout}|${JSON.stringify(fn.env)}`} {...ctx} fn={fn} reload={load} />}
      {tab === "monitor" && (
        <div className="panel disabled"><div className="panel-head"><h3>Metrics and logs</h3><SimLabel note="CloudWatch metrics and logs are not simulated." /></div>
          <div className="panel-body small muted">Invocation metrics and CloudWatch Logs aren&apos;t part of the training cloud. Use the Test tab to see your function&apos;s result.</div></div>)}
    </div>
  );
}

function CodeTab(ctx: Ctx & { fn: FnDetail; reload: () => Promise<void> }) {
  const [files, setFiles] = useState<Record<string, string>>(ctx.fn.files ?? {});
  const [open, setOpen] = useState(Object.keys(ctx.fn.files ?? {})[0] ?? "");
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  async function deploy() {
    setBusy(true);
    try { await api(`${ctx.base}/functions/${ctx.fn.name}/code`, { method: "PUT", body: { files } });
      setDirty(false); ctx.notify("pass", `Successfully updated the function ${ctx.fn.name}.`); await ctx.reload(); } catch (e) { ctx.fail(e); } finally { setBusy(false); }
  }
  function newFile() {
    const n = prompt("File name (for example utils.py)");
    if (!n || n in files) return;
    setFiles({ ...files, [n]: "" }); setOpen(n); setDirty(true);
  }
  function onKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key !== "Tab" || e.shiftKey) return;
    e.preventDefault();
    const t = e.currentTarget; const { selectionStart: a, selectionEnd: b } = t;
    const v = files[open].slice(0, a) + "    " + files[open].slice(b);
    setFiles({ ...files, [open]: v }); setDirty(true);
    requestAnimationFrame(() => { t.selectionStart = t.selectionEnd = a + 4; });
  }
  return (
    <div className="panel">
      <div className="panel-head">
        <h3>Code source</h3>
        {dirty && <span className="pill warn" data-testid="undeployed">Changes not deployed</span>}
        <button className="small" onClick={newFile}>New file</button>
        <button className="small primary" disabled={!dirty || busy} onClick={() => void deploy()} data-testid="deploy">{busy ? "Deploying…" : "Deploy"}</button>
      </div>
      {!ctx.fn.code_available ? (
        <div className="panel-body small muted">This function&apos;s code can&apos;t be shown in the editor. Update it from the terminal with <code>aws lambda update-function-code</code>.</div>
      ) : (
        <div className="ide">
          <div className="files" role="tablist" aria-label="Files">
            <div className="eyebrow" style={{ padding: "0 8px 6px" }}>{ctx.fn.name}</div>
            {Object.keys(files).sort().map((f) => (
              <button key={f} className={`file ${f === open ? "on" : ""}`} onClick={() => setOpen(f)} role="tab" aria-selected={f === open}>{f}</button>))}
          </div>
          <div className="editor">
            {open ? <textarea className="mono" spellCheck={false} value={files[open] ?? ""} aria-label={`Edit ${open}`} data-testid="code-editor"
              onKeyDown={onKey} onChange={(e) => { setFiles({ ...files, [open]: e.target.value }); setDirty(true); }} />
              : <p className="muted small" style={{ padding: 12 }}>No files. Choose <strong>New file</strong>.</p>}
            <div className="status small">{open} · {fmtSize(new Blob([files[open] ?? ""]).size)} · Handler <span className="mono">{ctx.fn.handler}</span></div>
          </div>
        </div>
      )}
      <style>{`.ide { display: grid; grid-template-columns: 170px minmax(0, 1fr); min-height: 340px; }
        .ide .files { border-right: 1px solid var(--line); padding: 10px 4px; background: #f7f9fc; display: flex; flex-direction: column; gap: 2px; }
        .ide .file { justify-content: flex-start; border: 0; background: transparent; padding: 5px 8px; font-family: var(--mono, monospace); font-size: 12px; }
        .ide .file.on { background: var(--signal-soft); color: var(--signal-strong); }
        .ide .editor { display: flex; flex-direction: column; background: #0f1b2d; }
        .ide textarea { flex: 1; min-height: 320px; border: 0; border-radius: 0; resize: vertical; background: #0f1b2d; color: #e3ebf7; font-size: 13px; line-height: 1.55; padding: 12px 14px; tab-size: 4; }
        .ide textarea:focus { outline: 2px solid var(--signal); outline-offset: -2px; }
        .ide .status { padding: 4px 12px; color: #9fb0c9; border-top: 1px solid #22324b; }
        @media (max-width: 700px) { .ide { grid-template-columns: 1fr; } }`}</style>
    </div>
  );
}

function TestTab(ctx: Ctx & { fn: FnDetail }) {
  const canInvoke = usable(ctx.features, "Invoke");
  const [eventName, setEventName] = useState("test-event");
  const [event, setEvent] = useState('{\n  "key1": "value1",\n  "key2": "value2",\n  "key3": "value3"\n}');
  const [out, setOut] = useState<InvokeOut | null>(null);
  const [busy, setBusy] = useState(false);
  let parsed: unknown = null; let invalid = false;
  try { parsed = JSON.parse(event); } catch { invalid = true; }
  async function test() {
    setBusy(true); setOut(null);
    try { setOut(await api<InvokeOut>(`${ctx.base}/functions/${ctx.fn.name}/invoke`, { method: "POST", body: { event: parsed } })); } catch (e) { ctx.fail(e); } finally { setBusy(false); }
  }
  if (!canInvoke) {
    return (
      <div className="panel disabled"><div className="panel-head"><h3>Test event</h3><SimLabel note={ctx.features.Invoke?.note} /></div>
        <div className="panel-body small muted">Running function code isn&apos;t available in this lab&apos;s training cloud. You can still create, edit, deploy and configure functions.</div></div>);
  }
  return (
    <div>
      <div className="panel">
        <div className="panel-head"><h3>Test event</h3>
          <button className="small primary" disabled={invalid || busy} onClick={() => void test()} data-testid="run-test">{busy ? "Running…" : "Test"}</button></div>
        <div className="panel-body">
          <span className="help">Invoke your function with a JSON event. The simulator starts a fresh runtime, so the first run can take several seconds.</span>
          <label>Event name<input value={eventName} onChange={(e) => setEventName(e.target.value)} style={{ maxWidth: 320 }} /></label>
          <label>Event JSON<textarea className="mono" rows={8} value={event} onChange={(e) => setEvent(e.target.value)} spellCheck={false} data-testid="test-event" /></label>
          {invalid && <span className="small" style={{ color: "var(--fail)" }}>The event must be valid JSON.</span>}
        </div>
      </div>
      {out && (
        <div className={`banner ${out.function_error ? "fail" : "pass"}`} role="status" data-testid="test-result" style={{ display: "block" }}>
          <strong>{out.function_error ? `Executing function: failed (${out.function_error})` : "Executing function: succeeded"}</strong>
          <div className="small muted" style={{ margin: "4px 0 8px" }}>Status code {out.status_code ?? "-"} · Duration {out.duration_ms} ms (including simulator start-up)</div>
          <pre className="mono small result">{JSON.stringify(out.response, null, 2)}</pre>
        </div>)}
      <style>{`.result { background: #fff; border: 1px solid var(--line); border-radius: 6px; padding: 10px; margin: 0; white-space: pre-wrap; word-break: break-word; max-height: 260px; overflow: auto; }`}</style>
    </div>
  );
}

function ConfigTab(ctx: Ctx & { fn: FnDetail; reload: () => Promise<void> }) {
  const [memory, setMemory] = useState(ctx.fn.memory ?? 128);
  const [timeout, setTimeout_] = useState(ctx.fn.timeout ?? 3);
  const [handler, setHandler] = useState(ctx.fn.handler ?? "");
  const [env, setEnv] = useState(Object.entries(ctx.fn.env).map(([key, value]) => ({ key, value })));
  const [busy, setBusy] = useState(false);
  const keys = env.map((e) => e.key.trim());
  const envOk = keys.every((k) => /^[A-Za-z][A-Za-z0-9_]*$/.test(k)) && new Set(keys).size === keys.length;
  const ok = envOk && memory >= 128 && memory <= 10240 && timeout >= 1 && timeout <= 900 && handler.trim() !== "";
  async function save() {
    setBusy(true);
    try {
      await api(`${ctx.base}/functions/${ctx.fn.name}/configuration`, { method: "PUT", body: {
        memory, timeout, handler: handler.trim(), env: Object.fromEntries(env.map((e) => [e.key.trim(), e.value])) } });
      ctx.notify("pass", `Successfully updated the function ${ctx.fn.name}.`); await ctx.reload();
    } catch (e) { ctx.fail(e); } finally { setBusy(false); }
  }
  return (
    <div style={{ maxWidth: 760 }}>
      <div className="panel"><div className="panel-head"><h3>General configuration</h3></div><div className="panel-body">
        <label>Memory<span className="help">Your function is allocated CPU proportional to the memory configured.</span>
          <div className="row"><input type="number" min={128} max={10240} value={memory} onChange={(e) => setMemory(Number(e.target.value))} style={{ width: 140 }} data-testid="memory" /> <span className="small">MB</span></div></label>
        <label>Timeout<div className="row"><input type="number" min={1} max={900} value={timeout} onChange={(e) => setTimeout_(Number(e.target.value))} style={{ width: 140 }} data-testid="timeout" /> <span className="small">sec</span></div></label>
        <label>Handler<input className="mono" value={handler} onChange={(e) => setHandler(e.target.value)} style={{ maxWidth: 420 }} />
          <span className="help">file name (without extension) . function name, for example lambda_function.lambda_handler</span></label>
        <div className="small" style={{ fontWeight: 600 }}>Ephemeral storage</div><div className="small">512 MB <SimLabel note="Ephemeral storage size is fixed in the simulator." /></div>
      </div></div>
      <div className="panel"><div className="panel-head"><h3>Environment variables <span className="muted">({env.length})</span></h3></div><div className="panel-body">
        <span className="help">Key/value pairs your code can read at run time, for settings you don&apos;t want to hard-code.</span>
        {env.map((e, i) => (
          <div className="row" key={i}>
            <input className="mono" style={{ width: 200 }} placeholder="Key" aria-label="Environment variable key" value={e.key} data-testid="env-key"
              onChange={(x) => setEnv(env.map((y, j) => (j === i ? { ...y, key: x.target.value } : y)))} />
            <input className="mono" style={{ width: 240 }} placeholder="Value" aria-label="Environment variable value" value={e.value} data-testid="env-value"
              onChange={(x) => setEnv(env.map((y, j) => (j === i ? { ...y, value: x.target.value } : y)))} />
            <button type="button" className="small" onClick={() => setEnv(env.filter((_, j) => j !== i))}>Remove</button>
          </div>))}
        <div><button type="button" className="small" onClick={() => setEnv([...env, { key: "", value: "" }])} data-testid="add-env">Add environment variable</button></div>
        {!envOk && <span className="small" style={{ color: "var(--fail)" }}>Keys must start with a letter, contain only letters, numbers and underscores, and be unique.</span>}
      </div></div>
      <div className="actions"><button className="primary" disabled={!ok || busy} onClick={() => void save()} data-testid="save-config">{busy ? "Saving…" : "Save"}</button></div>
    </div>
  );
}
