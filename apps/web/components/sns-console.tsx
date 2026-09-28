"use client";
// Student SNS console (PLAN console fidelity principle): topics, subscriptions (in-sandbox SQS queues
// only - there is no egress) and publishing. Talks only to the CloudLabs FastAPI SNS endpoints.
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { type Feature, FlashBanner, type Notify, useFlash } from "./console-kit";

type Topic = { name: string; arn: string; display_name: string; subscriptions: number; attributes: Record<string, string> };
type Subscription = { arn: string; protocol: string; endpoint: string; queue: string; raw_delivery: boolean };
type Detail = Topic & { subscriptions_list: Subscription[] };
type Queue = { name: string; fifo: boolean };
type View = { page: "list" | "detail"; name?: string };
type Ctx = { base: string; fail: (e: unknown) => void; notify: Notify; go: (v: View) => void; readOnly: boolean };

export function SnsConsole({ sessionId, readOnly, features }: { sessionId: string; readOnly: boolean;
  features: Record<string, Feature> }) {
  const base = `/api/sessions/${sessionId}/console/sns`;
  const [view, setView] = useState<View>({ page: "list" });
  const { flash, notify, fail, clear } = useFlash();
  const ctx: Ctx = { base, fail, notify, go: setView, readOnly };
  void features;
  return (
    <section className="svc-main">
      <div className="crumbs small" aria-label="Breadcrumb">
        <button className="linklike" onClick={() => setView({ page: "list" })}>SNS</button><span>›</span>
        {view.page === "list" ? <span>Topics</span> : <span className="mono">{view.name}</span>}
      </div>
      <FlashBanner flash={flash} onClose={clear} />
      {readOnly ? <div className="banner info">This lab is submitted or not running, so the console is read-only.</div> : null}
      {view.page === "list" ? <TopicList {...ctx} /> : <TopicDetailView {...ctx} name={view.name!} />}
    </section>
  );
}

function TopicList(ctx: Ctx) {
  const [topics, setTopics] = useState<Topic[] | null>(null);
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [display, setDisplay] = useState("");
  const load = useCallback(async () => {
    try { setTopics((await api<{ topics: Topic[] }>(`${ctx.base}/topics`)).topics); } catch (e) { ctx.fail(e); }
  }, [ctx.base, ctx.fail]);
  useEffect(() => { void load(); }, [load]);
  async function create() {
    try {
      await api(`${ctx.base}/topics`, { method: "POST", body: { name, display_name: display } });
      ctx.notify("pass", `Successfully created topic ${name}.`); setOpen(false); setName(""); setDisplay(""); await load();
    } catch (e) { ctx.fail(e); }
  }
  return (
    <div className="panel">
      <div className="panel-head">
        <h3>Topics <span className="muted">({topics?.length ?? "…"})</span></h3>
        <button className="small" onClick={() => void load()}>Refresh</button>
        <button className="small primary" disabled={ctx.readOnly} onClick={() => setOpen(!open)} data-testid="sns-open-create">Create topic</button>
      </div>
      <div className="panel-body" style={{ padding: 0, overflowX: "auto" }}>
        <table className="data">
          <thead><tr><th>Name</th><th>Display name</th><th>Subscriptions</th></tr></thead>
          <tbody>
            {topics?.length === 0 && <tr><td colSpan={3} className="muted">No topics. Create one to fan out alerts to a queue.</td></tr>}
            {topics?.map((t) => (
              <tr key={t.arn} data-testid="sns-row">
                <td><button className="linklike mono small" onClick={() => ctx.go({ page: "detail", name: t.name })} data-testid="sns-open-detail">{t.name}</button></td>
                <td className="small">{t.display_name || "-"}</td>
                <td className="small">{t.subscriptions}</td>
              </tr>))}
          </tbody>
        </table>
      </div>
      {open && !ctx.readOnly && (
        <div className="panel-body" style={{ borderTop: "1px solid var(--line)" }}>
          <h4 style={{ margin: 0 }}>Create topic</h4>
          <div className="row" style={{ flexWrap: "wrap", gap: 12, alignItems: "flex-end" }}>
            <label style={{ maxWidth: 260 }}>Name
              <input className="mono" value={name} onChange={(e) => setName(e.target.value)} placeholder="cafe-alerts" data-testid="sns-name" /></label>
            <label style={{ maxWidth: 260 }}>Display name (optional)
              <input value={display} onChange={(e) => setDisplay(e.target.value)} placeholder="CloudCafé alerts" data-testid="sns-display-name" /></label>
            <button className="small primary" disabled={!name} onClick={() => void create()} data-testid="sns-create-save">Create topic</button>
          </div>
        </div>)}
    </div>
  );
}

function TopicDetailView(ctx: Ctx & { name: string }) {
  const [t, setT] = useState<Detail | null>(null);
  const [queues, setQueues] = useState<Queue[]>([]);
  const [queue, setQueue] = useState("");
  const [raw, setRaw] = useState(false);
  const [tab, setTab] = useState<"subscriptions" | "publish">("subscriptions");
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const base = ctx.base;
  const name = ctx.name;
  const fail = ctx.fail;
  const load = useCallback(async () => {
    try { setT(await api<Detail>(`${base}/topics/${name}`)); } catch (e) { fail(e); }
  }, [base, name, fail]);
  useEffect(() => { void load(); }, [load]);
  const loadQueues = useCallback(async () => {
    try {
      const sid = base.split("/")[3];
      setQueues((await api<{ queues: Queue[] }>(`/api/sessions/${sid}/console/sqs/queues`)).queues);
    } catch { /* the SQS page may be unavailable on this engine; the form says so */ }
  }, [base]);
  useEffect(() => { void loadQueues(); }, [loadQueues]);

  async function subscribe() {
    try {
      await api(`${base}/topics/${name}/subscriptions`, { method: "POST", body: { queue, raw_delivery: raw } });
      ctx.notify("pass", `Successfully subscribed ${queue}.`); await load();
    } catch (e) { ctx.fail(e); }
  }
  async function unsubscribe(sub: Subscription) {
    if (!confirm(`Remove the subscription of ${sub.queue}?`)) return;
    try { await api(`${base}/topics/${name}/subscriptions/delete`, { method: "POST", body: { subscription_arn: sub.arn } });
      ctx.notify("pass", `Removed the subscription of ${sub.queue}.`); await load(); } catch (e) { ctx.fail(e); }
  }
  async function publish() {
    try {
      await api(`${base}/topics/${name}/publish`, { method: "POST", body: { subject, message } });
      ctx.notify("pass", "Message published. Delivery to subscribed queues is immediate in the sandbox.");
      setMessage(""); setSubject("");
    } catch (e) { ctx.fail(e); }
  }
  async function remove() {
    if (!confirm(`Delete topic ${name}?`)) return;
    try { await api(`${base}/topics/${name}`, { method: "DELETE" });
      ctx.notify("pass", `Deleted topic ${name}.`); ctx.go({ page: "list" }); } catch (e) { ctx.fail(e); }
  }
  if (!t) return <p className="muted small">Loading topic…</p>;
  return (
    <div className="panel">
      <div className="panel-head">
        <h3 className="mono">{t.name}</h3>
        {t.display_name && <span className="pill info">{t.display_name}</span>}
        <button className="small" disabled={ctx.readOnly} onClick={() => void remove()} data-testid="sns-delete">Delete</button>
      </div>
      <div className="panel-body">
        <dl className="kv">
          <div><dt>Subscriptions</dt><dd data-testid="sns-subscription-count">{t.subscriptions}</dd></div>
          <div><dt>Display name</dt><dd>{t.display_name || "-"}</dd></div>
        </dl>
        <div className="tabs" role="tablist" aria-label="Topic" style={{ marginBottom: 0 }}>
          {(["subscriptions", "publish"] as const).map((x) => (
            <button key={x} role="tab" aria-selected={tab === x} className={tab === x ? "tab on" : "tab"}
              onClick={() => setTab(x)} data-testid={`sns-tab-${x}`}>{x === "subscriptions" ? "Subscriptions" : "Publish"}</button>))}
        </div>
        {tab === "subscriptions" && (
          <div className="stack" style={{ gap: 10 }}>
            <table className="data">
              <thead><tr><th>Protocol</th><th>Endpoint</th><th>Raw delivery</th><th /></tr></thead>
              <tbody>
                {t.subscriptions_list.length === 0 && <tr><td colSpan={4} className="muted">No subscriptions. An SQS queue must be subscribed before anything is delivered.</td></tr>}
                {t.subscriptions_list.map((s) => (
                  <tr key={s.arn} data-testid="sns-subscription-row">
                    <td className="small">{s.protocol.toUpperCase()}</td><td className="mono small">{s.queue}</td>
                    <td className="small">{s.raw_delivery ? "Yes" : "No"}</td>
                    <td style={{ textAlign: "right" }}>{!ctx.readOnly &&
                      <button className="small" onClick={() => void unsubscribe(s)} data-testid="sns-unsubscribe">Unsubscribe</button>}</td>
                  </tr>))}
              </tbody>
            </table>
            {!ctx.readOnly && (queues.length === 0 ? (
              <p className="help" style={{ margin: 0 }}>No queues in this sandbox yet — create one on the SQS page first, then come back to subscribe it.</p>
            ) : (
              <div className="row" style={{ flexWrap: "wrap", gap: 12, alignItems: "flex-end" }}>
                <label style={{ maxWidth: 280 }}>Queue
                  <select value={queue} onChange={(e) => setQueue(e.target.value)} data-testid="sns-subscribe-queue">
                    <option value="">Select a queue…</option>
                    {queues.map((q) => <option key={q.name} value={q.name}>{q.name}</option>)}
                  </select></label>
                <label className="choice" style={{ maxWidth: 180 }}><input type="checkbox" checked={raw}
                  onChange={(e) => setRaw(e.target.checked)} data-testid="sns-subscribe-raw" /> Raw message delivery</label>
                <button className="small primary" disabled={!queue} onClick={() => void subscribe()} data-testid="sns-subscribe-add">Subscribe</button>
              </div>))}
          </div>)}
        {tab === "publish" && (
          <div className="stack" style={{ gap: 10 }}>
            <p className="help" style={{ margin: 0 }}>Messages are delivered only to queues inside your sandbox: SNS has no internet access here.</p>
            <label style={{ maxWidth: 420 }}>Subject (optional)
              <input value={subject} onChange={(e) => setSubject(e.target.value)} data-testid="sns-publish-subject" /></label>
            <label>Message
              <textarea className="mono" rows={4} value={message} onChange={(e) => setMessage(e.target.value)}
                placeholder='{"alert": "latte order waiting"}' data-testid="sns-publish-message" /></label>
            <div className="actions"><button className="small primary" disabled={ctx.readOnly || !message} onClick={() => void publish()}
              data-testid="sns-publish">Publish message</button></div>
          </div>)}
      </div>
    </div>
  );
}
