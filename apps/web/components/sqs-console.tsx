"use client";
// Student SQS console (PLAN console fidelity principle): queues, attributes, tags, send/poll/delete
// messages and purge. Queues are configuration records in the simulator; there is no background worker.
// Talks only to the CloudLabs FastAPI SQS endpoints; resources are addressed by queue name.
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { type Feature, FlashBanner, type Notify, TagRows, useFlash } from "./console-kit";

type Queue = { name: string; fifo: boolean; visibility_timeout: string; retention_period: string;
  delay_seconds: string; messages: string; in_flight: string };
type QueueDetail = Queue & { url: string; arn: string; created: boolean; tags: Record<string, string>;
  attributes: Record<string, string> };
type Message = { id: string; body: string; receipt_handle: string; attributes: Record<string, string>;
  receive_count: string };
type View = { page: "list" | "detail"; name?: string };
type Ctx = { base: string; fail: (e: unknown) => void; notify: Notify; go: (v: View) => void; readOnly: boolean };

export function SqsConsole({ sessionId, readOnly, features }: { sessionId: string; readOnly: boolean;
  features: Record<string, Feature> }) {
  const base = `/api/sessions/${sessionId}/console/sqs`;
  const [view, setView] = useState<View>({ page: "list" });
  const { flash, notify, fail, clear } = useFlash();
  const ctx: Ctx = { base, fail, notify, go: setView, readOnly };
  void features;
  return (
    <section className="svc-main">
      <div className="crumbs small" aria-label="Breadcrumb">
        <button className="linklike" onClick={() => setView({ page: "list" })}>SQS</button><span>›</span>
        {view.page === "list" ? <span>Queues</span> : <span className="mono">{view.name}</span>}
      </div>
      <FlashBanner flash={flash} onClose={clear} />
      {readOnly ? <div className="banner info">This lab is submitted or not running, so the console is read-only.</div> : null}
      {view.page === "list" ? <QueueList {...ctx} /> : <QueueDetailView {...ctx} name={view.name!} />}
    </section>
  );
}

// ------------------------------------------------------------------------------------- queue list
function QueueList(ctx: Ctx) {
  const [queues, setQueues] = useState<Queue[] | null>(null);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [fifo, setFifo] = useState(false);
  const [visibility, setVisibility] = useState("30");
  const [retention, setRetention] = useState("345600");
  const load = useCallback(async () => {
    try { setQueues((await api<{ queues: Queue[] }>(`${ctx.base}/queues`)).queues); } catch (e) { ctx.fail(e); }
  }, [ctx.base, ctx.fail]);
  useEffect(() => { void load(); }, [load]);
  async function create() {
    try {
      await api(`${ctx.base}/queues`, { method: "POST", body: {
        name, fifo, visibility_timeout: Number(visibility), retention_period: Number(retention) } });
      ctx.notify("pass", `Successfully created queue ${name}.`); setOpen(false); setName(""); await load();
    } catch (e) { ctx.fail(e); }
  }
  return (
    <div className="panel">
      <div className="panel-head">
        <h3>Queues <span className="muted">({queues?.length ?? "…"})</span></h3>
        <button className="small" onClick={() => void load()}>Refresh</button>
        <button className="small primary" disabled={ctx.readOnly} onClick={() => setOpen(!open)} data-testid="sqs-open-create">Create queue</button>
      </div>
      <div className="panel-body" style={{ padding: 0, overflowX: "auto" }}>
        <table className="data">
          <thead><tr><th>Name</th><th>Type</th><th>Messages available</th><th>Messages in flight</th><th>Visibility timeout</th><th>Retention</th></tr></thead>
          <tbody>
            {queues?.length === 0 && <tr><td colSpan={6} className="muted">No queues. Create one, or run <code>aws sqs create-queue</code>.</td></tr>}
            {queues?.map((q) => (
              <tr key={q.name} data-testid="sqs-row">
                <td><button className="linklike mono small" onClick={() => ctx.go({ page: "detail", name: q.name })} data-testid="sqs-open-detail">{q.name}</button></td>
                <td className="small">{q.fifo ? "FIFO" : "Standard"}</td>
                <td className="small">{q.messages}</td><td className="small">{q.in_flight}</td>
                <td className="small">{q.visibility_timeout} s</td><td className="small">{q.retention_period} s</td>
              </tr>))}
          </tbody>
        </table>
      </div>
      {open && !ctx.readOnly && (
        <div className="panel-body" style={{ borderTop: "1px solid var(--line)" }}>
          <h4 style={{ margin: 0 }}>Create queue</h4>
          <div className="row" style={{ flexWrap: "wrap", gap: 12, alignItems: "flex-end" }}>
            <label style={{ maxWidth: 280 }}>Name
              <input className="mono" value={name} onChange={(e) => setName(e.target.value)}
                placeholder={fifo ? "orders.fifo" : "orders"} data-testid="sqs-name" /></label>
            <label style={{ maxWidth: 140 }}>Visibility timeout (s)
              <input className="mono" type="number" min={0} max={43200} value={visibility}
                onChange={(e) => setVisibility(e.target.value)} data-testid="sqs-visibility" /></label>
            <label style={{ maxWidth: 160 }}>Message retention (s)
              <input className="mono" type="number" min={60} max={1209600} value={retention}
                onChange={(e) => setRetention(e.target.value)} data-testid="sqs-retention" /></label>
            <label className="choice" style={{ maxWidth: 160 }}><input type="checkbox" checked={fifo}
              onChange={(e) => setFifo(e.target.checked)} data-testid="sqs-fifo" /> FIFO queue</label>
            <button className="small primary" disabled={!name || (fifo && !name.endsWith(".fifo"))} onClick={() => void create()}
              data-testid="sqs-create-save">Create queue</button>
            {fifo && !name.endsWith(".fifo") && <span className="help">A FIFO queue name must end in .fifo</span>}
          </div>
        </div>)}
    </div>
  );
}

// ----------------------------------------------------------------------------------- queue detail
function QueueDetailView(ctx: Ctx & { name: string }) {
  const [q, setQ] = useState<QueueDetail | null>(null);
  const [tab, setTab] = useState<"messages" | "attributes" | "tags" | "send">("messages");
  const [messages, setMessages] = useState<Message[] | null>(null);
  const [body, setBody] = useState("");
  const [visibility, setVisibility] = useState("");
  const [retention, setRetention] = useState("");
  const [delay, setDelay] = useState("");
  const [tags, setTags] = useState<{ key: string; value: string }[]>([]);
  const load = useCallback(async () => {
    try {
      const d = await api<QueueDetail>(`${ctx.base}/queues/${ctx.name}`);
      setQ(d); setVisibility(d.visibility_timeout); setRetention(d.retention_period); setDelay(d.delay_seconds);
      setTags(Object.entries(d.tags).map(([key, value]) => ({ key, value })));
    } catch (e) { ctx.fail(e); }
  }, [ctx.base, ctx.fail, ctx.name]);
  useEffect(() => { void load(); }, [load]);

  async function poll() {
    try { setMessages((await api<{ messages: Message[] }>(`${ctx.base}/queues/${ctx.name}/poll`, { method: "POST",
      body: { max: 10, wait_seconds: 1 } })).messages); } catch (e) { ctx.fail(e); }
  }
  async function send() {
    try { await api(`${ctx.base}/queues/${ctx.name}/messages`, { method: "POST", body: { body } });
      ctx.notify("pass", "Message sent."); setBody(""); await load(); } catch (e) { ctx.fail(e); }
  }
  async function deleteMessage(m: Message) {
    try { await api(`${ctx.base}/queues/${ctx.name}/messages/delete`, { method: "POST", body: { receipt_handle: m.receipt_handle } });
      setMessages((ms) => ms?.filter((x) => x.receipt_handle !== m.receipt_handle) ?? null); await load(); } catch (e) { ctx.fail(e); }
  }
  async function saveAttributes() {
    try { await api(`${ctx.base}/queues/${ctx.name}/attributes`, { method: "PUT", body: {
      visibility_timeout: Number(visibility), retention_period: Number(retention), delay_seconds: Number(delay) } });
      ctx.notify("pass", "Queue attributes saved."); await load(); } catch (e) { ctx.fail(e); }
  }
  async function saveTags() {
    try { await api(`${ctx.base}/queues/${ctx.name}/tags`, { method: "PUT", body: {
      tags: tags.filter((t) => t.key.trim()) } }); ctx.notify("pass", "Queue tags saved."); await load(); } catch (e) { ctx.fail(e); }
  }
  async function purge() {
    if (!confirm(`Purge every message from ${ctx.name}?`)) return;
    try { await api(`${ctx.base}/queues/${ctx.name}/purge`, { method: "POST" });
      ctx.notify("pass", "Queue purged."); setMessages([]); await load(); } catch (e) { ctx.fail(e); }
  }
  async function remove() {
    if (!confirm(`Delete queue ${ctx.name}? This can't be undone.`)) return;
    try { await api(`${ctx.base}/queues/${ctx.name}`, { method: "DELETE" });
      ctx.notify("pass", `Deleted queue ${ctx.name}.`); ctx.go({ page: "list" }); } catch (e) { ctx.fail(e); }
  }
  if (!q) return <p className="muted small">Loading queue…</p>;
  return (
    <div className="panel">
      <div className="panel-head">
        <h3 className="mono">{q.name}</h3>
        <span className="pill info">{q.fifo ? "FIFO" : "Standard"}</span>
        <button className="small" onClick={() => void purge()} data-testid="sqs-purge">Purge</button>
        <button className="small" disabled={ctx.readOnly} onClick={() => void remove()} data-testid="sqs-delete">Delete</button>
      </div>
      <div className="panel-body">
        <dl className="kv">
          <div><dt>Messages available</dt><dd data-testid="sqs-count">{q.messages}</dd></div>
          <div><dt>Messages in flight</dt><dd>{q.in_flight}</dd></div>
          <div><dt>Visibility timeout</dt><dd>{q.visibility_timeout} s</dd></div>
          <div><dt>Message retention</dt><dd>{q.retention_period} s</dd></div>
        </dl>
        <div className="tabs" role="tablist" aria-label="Queue" style={{ marginBottom: 0 }}>
          {(["messages", "send", "attributes", "tags"] as const).map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "tab on" : "tab"}
              onClick={() => setTab(t)} data-testid={`sqs-tab-${t}`}>{ { messages: "Messages", send: "Send message", attributes: "Attributes", tags: "Tags" }[t] }</button>))}
        </div>
        {tab === "messages" && (
          <div className="stack" style={{ gap: 10 }}>
            <div className="row" style={{ gap: 8 }}>
              <button className="small primary" onClick={() => void poll()} data-testid="sqs-poll">Poll for messages</button>
              <span className="help">Polling shows up to 10 messages without consuming them (visibility timeout 0). Delete a message to remove it.</span>
            </div>
            {messages && messages.length === 0 && <p className="muted small">No messages received.</p>}
            {messages?.map((m) => (
              <div className="panel" key={m.receipt_handle} data-testid="sqs-message">
                <div className="panel-head"><h4 className="mono" style={{ flex: 1, margin: 0 }}>{m.id}</h4>
                  <span className="small muted">received {m.receive_count}×</span>
                  <button className="small danger" onClick={() => void deleteMessage(m)} data-testid="sqs-message-delete">Delete</button></div>
                <div className="panel-body"><pre className="mono small" style={{ margin: 0, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>{m.body}</pre>
                  {Object.entries(m.attributes).length > 0 && <div className="small muted">{Object.entries(m.attributes).map(([k, v]) => `${k}=${v}`).join(", ")}</div>}
                </div>
              </div>))}
          </div>)}
        {tab === "send" && (
          <div className="stack" style={{ gap: 10 }}>
            <label>Message body
              <textarea className="mono" rows={4} value={body} onChange={(e) => setBody(e.target.value)}
                placeholder='{"orderId": 1001, "drink": "latte"}' data-testid="sqs-message-body" /></label>
            <div className="actions"><button className="small primary" disabled={ctx.readOnly || !body} onClick={() => void send()}
              data-testid="sqs-send">Send message</button></div>
          </div>)}
        {tab === "attributes" && (
          <div className="stack" style={{ gap: 10 }}>
            <div className="row" style={{ flexWrap: "wrap", gap: 12, alignItems: "flex-end" }}>
              <label style={{ maxWidth: 170 }}>Visibility timeout (s)
                <input className="mono" type="number" min={0} max={43200} value={visibility} disabled={ctx.readOnly}
                  onChange={(e) => setVisibility(e.target.value)} data-testid="sqs-attr-visibility" /></label>
              <label style={{ maxWidth: 190 }}>Message retention (s)
                <input className="mono" type="number" min={60} max={1209600} value={retention} disabled={ctx.readOnly}
                  onChange={(e) => setRetention(e.target.value)} data-testid="sqs-attr-retention" /></label>
              <label style={{ maxWidth: 150 }}>Delivery delay (s)
                <input className="mono" type="number" min={0} max={900} value={delay} disabled={ctx.readOnly}
                  onChange={(e) => setDelay(e.target.value)} data-testid="sqs-attr-delay" /></label>
            </div>
            {!ctx.readOnly && <div className="actions"><button className="small primary" onClick={() => void saveAttributes()}
              data-testid="sqs-save-attributes">Save attributes</button></div>}
          </div>)}
        {tab === "tags" && (
          <div className="stack" style={{ gap: 10 }}>
            {ctx.readOnly ? <p className="muted small">{Object.entries(q.tags).map(([k, v]) => `${k}=${v}`).join(", ") || "No tags."}</p> : (
              <>
                <TagRows tags={tags} setTags={setTags} />
                <div className="actions"><button className="small primary" onClick={() => void saveTags()}
                  data-testid="sqs-save-tags">Save tags</button></div>
              </>)}
          </div>)}
      </div>
    </div>
  );
}
