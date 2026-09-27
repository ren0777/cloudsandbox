"use client";
// Student VPC console (PLAN console fidelity principle): Your VPCs, Subnets, Route tables, Internet
// gateways and Security groups. The network is configuration-level in the simulator (no real traffic).
// Talks only to the CloudLabs FastAPI VPC endpoints; resource names are Name tags.
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { type Feature, FlashBanner, type Notify, useFlash } from "./console-kit";

type Vpc = { id: string; name: string; cidr: string; is_default: boolean; state: string; subnet_count: number };
type Subnet = { id: string; name: string; cidr: string; vpc_id: string; vpc_name: string; az: string | null;
  public: boolean; available_ips: number | null };
type Route = { destination: string; target_kind: "local" | "internet_gateway"; target: string; state: string };
type Association = { id: string | null; subnet_id: string | null; subnet_name: string; main: boolean };
type RouteTable = { id: string; name: string; vpc_id: string; vpc_name: string; routes: Route[]; associations: Association[] };
type Igw = { id: string; name: string; vpc_id: string | null; vpc_name: string };
type Rule = { protocol: string; from_port: number | null; to_port: number | null; cidr: string; description?: string };
type Sg = { id: string; name: string; description: string; vpc_id: string; vpc_name: string; ingress: Rule[]; egress: Rule[] };
type Overview = { vpcs: Vpc[]; subnets: Subnet[]; route_tables: RouteTable[]; internet_gateways: Igw[]; security_groups: Sg[] };
type Section = "vpcs" | "subnets" | "rtbs" | "igws" | "sgs";
type Ctx = { base: string; data: Overview | null; load: () => Promise<void>; fail: (e: unknown) => void;
  notify: Notify; readOnly: boolean };

const CIDR = /^\d{1,3}(\.\d{1,3}){3}\/\d{1,2}$/;
const SECTION_LABEL: Record<Section, string> = { vpcs: "Your VPCs", subnets: "Subnets", rtbs: "Route tables",
  igws: "Internet gateways", sgs: "Security groups" };

export function VpcConsole({ sessionId, readOnly, features }: { sessionId: string; readOnly: boolean;
  features: Record<string, Feature> }) {
  const base = `/api/sessions/${sessionId}/console/vpc`;
  const [tab, setTab] = useState<Section>("vpcs");
  const [data, setData] = useState<Overview | null>(null);
  const { flash, notify, fail, clear } = useFlash();
  const load = useCallback(async () => {
    try { setData(await api<Overview>(`${base}/overview`)); } catch (e) { fail(e); }
  }, [base, fail]);
  useEffect(() => { void load(); }, [load]);
  const ctx: Ctx = { base, data, load, fail, notify, readOnly };
  void features;
  return (
    <section className="svc-main">
      <div className="crumbs small" aria-label="Breadcrumb"><span>VPC</span><span>›</span><span>{SECTION_LABEL[tab]}</span></div>
      <FlashBanner flash={flash} onClose={clear} />
      {readOnly ? <div className="banner info">This lab is submitted or not running, so the console is read-only.</div> : (
        <>
          <div className="tabs" role="tablist" aria-label="VPC">
            {(Object.keys(SECTION_LABEL) as Section[]).map((s) => (
              <button key={s} role="tab" aria-selected={tab === s} className={tab === s ? "tab on" : "tab"}
                onClick={() => setTab(s)} data-testid={`vpc-tab-${s}`}>{SECTION_LABEL[s]}</button>))}
          </div>
          {tab === "vpcs" && <Vpcs ctx={ctx} />}
          {tab === "subnets" && <Subnets ctx={ctx} />}
          {tab === "rtbs" && <RouteTables ctx={ctx} />}
          {tab === "igws" && <InternetGateways ctx={ctx} />}
          {tab === "sgs" && <SecurityGroups ctx={ctx} />}
        </>
      )}
    </section>
  );
}

function Panel({ title, count, children, actions }: { title: string; count?: number; actions: React.ReactNode;
  children: React.ReactNode }) {
  return (
    <div className="panel">
      <div className="panel-head"><h3>{title} {count !== undefined && <span className="muted">({count})</span>}</h3>{actions}</div>
      <div className="panel-body" style={{ padding: 0, overflowX: "auto" }}>{children}</div>
    </div>
  );
}

function CidrInput({ value, onChange, testId }: { value: string; onChange: (v: string) => void; testId: string }) {
  const bad = value.length > 0 && !CIDR.test(value);
  return (
    <label>IPv4 CIDR block
      <input className="mono" style={{ maxWidth: 280 }} value={value} onChange={(e) => onChange(e.target.value)}
        placeholder="10.0.0.0/16" data-testid={testId} />
      {bad && <span className="help" style={{ color: "var(--fail)" }}>Use CIDR notation, e.g. 10.0.0.0/16</span>}
    </label>
  );
}

// -------------------------------------------------------------------------------------------- VPCs
function Vpcs({ ctx }: { ctx: Ctx }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [cidr, setCidr] = useState("10.0.0.0/16");
  async function create() {
    try {
      await api(`${ctx.base}/vpcs`, { method: "POST", body: { name, cidr } });
      ctx.notify("pass", `Successfully created VPC ${name}.`); setOpen(false); setName(""); await ctx.load();
    } catch (e) { ctx.fail(e); }
  }
  async function remove(v: Vpc) {
    if (!confirm(`Delete ${v.name || v.id}? Subnets and other resources in it must be deleted first.`)) return;
    try { await api(`${ctx.base}/vpcs/${v.id}/delete`, { method: "POST" });
      ctx.notify("pass", `Deleted VPC ${v.name || v.id}.`); await ctx.load(); } catch (e) { ctx.fail(e); }
  }
  return (
    <>
      <Panel title="Your VPCs" count={ctx.data?.vpcs.length} actions={
        <button className="small primary" disabled={ctx.readOnly} onClick={() => setOpen(!open)} data-testid="vpc-open-create">Create VPC</button>}>
        <table className="data">
          <thead><tr><th>Name</th><th>VPC ID</th><th>IPv4 CIDR</th><th>Default</th><th>Subnets</th><th /></tr></thead>
          <tbody>
            {ctx.data?.vpcs.length === 0 && <tr><td colSpan={6} className="muted">No VPCs. Create one, or use the default VPC.</td></tr>}
            {ctx.data?.vpcs.map((v) => (
              <tr key={v.id} data-testid="vpc-row">
                <td className="small">{v.name || "-"}</td>
                <td className="mono small">{v.id}</td>
                <td className="mono small">{v.cidr}</td>
                <td className="small">{v.is_default ? "Yes" : "No"}</td>
                <td className="small">{v.subnet_count}</td>
                <td style={{ textAlign: "right" }}>{!ctx.readOnly && !v.is_default &&
                  <button className="small" onClick={() => void remove(v)} data-testid="vpc-delete">Delete</button>}</td>
              </tr>))}
          </tbody>
        </table>
      </Panel>
      {open && !ctx.readOnly && (
        <div className="panel"><div className="panel-head"><h3>Create VPC</h3></div>
          <div className="panel-body">
            <label>Name tag<input value={name} onChange={(e) => setName(e.target.value)} placeholder="cafe-vpc-1" data-testid="vpc-name" /></label>
            <CidrInput value={cidr} onChange={setCidr} testId="vpc-cidr" />
            <div className="actions">
              <button className="small" onClick={() => setOpen(false)}>Cancel</button>
              <button className="small primary" disabled={!name || !CIDR.test(cidr)} onClick={() => void create()}
                data-testid="vpc-create-save">Create VPC</button>
            </div>
          </div>
        </div>)}
    </>
  );
}

// ------------------------------------------------------------------------------------------ subnets
function Subnets({ ctx }: { ctx: Ctx }) {
  const [open, setOpen] = useState(false);
  const [vpcId, setVpcId] = useState("");
  const [name, setName] = useState("");
  const [cidr, setCidr] = useState("10.0.1.0/24");
  const [isPublic, setPublic] = useState(true);
  const vpcs = ctx.data?.vpcs ?? [];
  async function create() {
    try {
      await api(`${ctx.base}/subnets`, { method: "POST",
        body: { vpc_id: vpcId || vpcs[0]?.id, name, cidr, public: isPublic } });
      ctx.notify("pass", `Successfully created subnet ${name}.`); setOpen(false); setName(""); await ctx.load();
    } catch (e) { ctx.fail(e); }
  }
  async function remove(s: Subnet) {
    if (!confirm(`Delete subnet ${s.name || s.id}?`)) return;
    try { await api(`${ctx.base}/subnets/${s.id}/delete`, { method: "POST" });
      ctx.notify("pass", `Deleted subnet ${s.name || s.id}.`); await ctx.load(); } catch (e) { ctx.fail(e); }
  }
  return (
    <>
      <Panel title="Subnets" count={ctx.data?.subnets.length} actions={
        <button className="small primary" disabled={ctx.readOnly || vpcs.length === 0} onClick={() => setOpen(!open)}
          data-testid="subnet-open-create">Create subnet</button>}>
        <table className="data">
          <thead><tr><th>Name</th><th>Subnet ID</th><th>VPC</th><th>IPv4 CIDR</th><th>Availability Zone</th><th>Public</th><th /></tr></thead>
          <tbody>
            {ctx.data?.subnets.length === 0 && <tr><td colSpan={7} className="muted">No subnets.</td></tr>}
            {ctx.data?.subnets.map((s) => (
              <tr key={s.id} data-testid="subnet-row">
                <td className="small">{s.name || "-"}</td>
                <td className="mono small">{s.id}</td>
                <td className="small">{s.vpc_name || s.vpc_id}</td>
                <td className="mono small">{s.cidr}</td>
                <td className="small">{s.az ?? "-"}</td>
                <td className="small">{s.public ? "Yes" : "No"}</td>
                <td style={{ textAlign: "right" }}>{!ctx.readOnly &&
                  <button className="small" onClick={() => void remove(s)} data-testid="subnet-delete">Delete</button>}</td>
              </tr>))}
          </tbody>
        </table>
      </Panel>
      {open && !ctx.readOnly && (
        <div className="panel"><div className="panel-head"><h3>Create subnet</h3></div>
          <div className="panel-body">
            <label>VPC
              <select value={vpcId || vpcs[0]?.id || ""} onChange={(e) => setVpcId(e.target.value)} data-testid="subnet-vpc-select">
                {vpcs.map((v) => <option key={v.id} value={v.id}>{v.name || v.id} ({v.cidr})</option>)}</select></label>
            <label>Subnet name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="public-1" data-testid="subnet-name" /></label>
            <CidrInput value={cidr} onChange={setCidr} testId="subnet-cidr" />
            <label className="choice"><input type="checkbox" checked={isPublic} onChange={(e) => setPublic(e.target.checked)}
              data-testid="subnet-public" /> Auto-assign public IPv4 address (a public subnet also needs a route to an internet gateway)</label>
            <div className="actions">
              <button className="small" onClick={() => setOpen(false)}>Cancel</button>
              <button className="small primary" disabled={!name || !CIDR.test(cidr)} onClick={() => void create()}
                data-testid="subnet-create-save">Create subnet</button>
            </div>
          </div>
        </div>)}
    </>
  );
}

// ----------------------------------------------------------------------------------- route tables
function RouteTables({ ctx }: { ctx: Ctx }) {
  const [open, setOpen] = useState(false);
  const [vpcId, setVpcId] = useState("");
  const [name, setName] = useState("");
  const [detail, setDetail] = useState<string | null>(null);
  const [dest, setDest] = useState("0.0.0.0/0");
  const [igwId, setIgwId] = useState("");
  const [subnetId, setSubnetId] = useState("");
  const vpcs = ctx.data?.vpcs ?? [];
  const igws = ctx.data?.internet_gateways ?? [];
  const subnets = ctx.data?.subnets ?? [];
  const selected = ctx.data?.route_tables.find((t) => t.id === detail) ?? null;

  async function create() {
    try {
      await api(`${ctx.base}/route-tables`, { method: "POST", body: { vpc_id: vpcId || vpcs[0]?.id, name } });
      ctx.notify("pass", `Successfully created route table ${name}.`); setOpen(false); setName(""); await ctx.load();
    } catch (e) { ctx.fail(e); }
  }
  async function addRoute(t: RouteTable) {
    try {
      await api(`${ctx.base}/route-tables/${t.id}/routes`, { method: "POST",
        body: { destination_cidr: dest, internet_gateway_id: igwId || igws[0]?.id } });
      ctx.notify("pass", `Successfully added route ${dest}.`); await ctx.load();
    } catch (e) { ctx.fail(e); }
  }
  async function deleteRoute(t: RouteTable, r: Route) {
    try { await api(`${ctx.base}/route-tables/${t.id}/routes/delete`, { method: "POST",
      body: { destination_cidr: r.destination } }); ctx.notify("pass", `Removed route ${r.destination}.`); await ctx.load();
    } catch (e) { ctx.fail(e); }
  }
  async function associate(t: RouteTable) {
    try {
      await api(`${ctx.base}/route-tables/${t.id}/associate`, { method: "POST", body: { subnet_id: subnetId || subnets[0]?.id } });
      ctx.notify("pass", "Successfully associated the subnet."); await ctx.load();
    } catch (e) { ctx.fail(e); }
  }
  async function disassociate(t: RouteTable, a: Association) {
    try { await api(`${ctx.base}/route-tables/${t.id}/disassociate`, { method: "POST", body: { association_id: a.id } });
      ctx.notify("pass", "Disassociated the subnet."); await ctx.load(); } catch (e) { ctx.fail(e); }
  }
  async function remove(t: RouteTable) {
    if (!confirm(`Delete route table ${t.name}?`)) return;
    try { await api(`${ctx.base}/route-tables/${t.id}/delete`, { method: "POST" });
      ctx.notify("pass", `Deleted route table ${t.name}.`); setDetail(null); await ctx.load(); } catch (e) { ctx.fail(e); }
  }
  return (
    <>
      <Panel title="Route tables" count={ctx.data?.route_tables.length} actions={
        <button className="small primary" disabled={ctx.readOnly || vpcs.length === 0} onClick={() => setOpen(!open)}
          data-testid="rtb-open-create">Create route table</button>}>
        <table className="data">
          <thead><tr><th>Name</th><th>Route table ID</th><th>VPC</th><th>Routes</th><th>Subnet associations</th><th /></tr></thead>
          <tbody>
            {ctx.data?.route_tables.length === 0 && <tr><td colSpan={6} className="muted">No route tables.</td></tr>}
            {ctx.data?.route_tables.map((t) => (
              <tr key={t.id} data-testid="rtb-row">
                <td className="small"><button className="linklike" onClick={() => setDetail(t.id)} data-testid="rtb-open-detail">{t.name}</button></td>
                <td className="mono small">{t.id}</td>
                <td className="small">{t.vpc_name || t.vpc_id}</td>
                <td className="small">{t.routes.map((r) => `${r.destination}→${r.target}`).join(", ") || "-"}</td>
                <td className="small">{t.associations.filter((a) => !a.main).map((a) => a.subnet_name).join(", ") || (t.associations.some((a) => a.main) ? "main" : "-")}</td>
                <td style={{ textAlign: "right" }}><button className="small" onClick={() => setDetail(t.id)}>Details</button></td>
              </tr>))}
          </tbody>
        </table>
      </Panel>
      {open && !ctx.readOnly && (
        <div className="panel"><div className="panel-head"><h3>Create route table</h3></div>
          <div className="panel-body">
            <label>VPC
              <select value={vpcId || vpcs[0]?.id || ""} onChange={(e) => setVpcId(e.target.value)} data-testid="rtb-vpc-select">
                {vpcs.map((v) => <option key={v.id} value={v.id}>{v.name || v.id} ({v.cidr})</option>)}</select></label>
            <label>Name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="public-rtb-1" data-testid="rtb-name" /></label>
            <div className="actions">
              <button className="small" onClick={() => setOpen(false)}>Cancel</button>
              <button className="small primary" disabled={!name} onClick={() => void create()} data-testid="rtb-create-save">Create route table</button>
            </div>
          </div>
        </div>)}
      {selected && (
        <div className="panel" data-testid="rtb-detail">
          <div className="panel-head"><h3>{selected.name}</h3>
            <button className="small" onClick={() => setDetail(null)}>Close</button>
            <button className="small" onClick={() => void remove(selected)} data-testid="rtb-delete">Delete route table</button>
          </div>
          <div className="panel-body">
            <h4 style={{ margin: 0 }}>Routes</h4>
            <table className="data"><thead><tr><th>Destination</th><th>Target</th><th>State</th><th /></tr></thead>
              <tbody>
                {selected.routes.map((r) => (
                  <tr key={r.destination}><td className="mono small">{r.destination}</td><td className="small">{r.target}</td>
                    <td className="small">{r.state}</td>
                    <td style={{ textAlign: "right" }}>{!ctx.readOnly && r.target_kind !== "local" &&
                      <button className="small" onClick={() => void deleteRoute(selected, r)} data-testid="rtb-route-delete">Remove</button>}</td></tr>))}
              </tbody></table>
            {!ctx.readOnly && (
              <div className="row" style={{ flexWrap: "wrap", gap: 8, alignItems: "flex-end" }}>
                <label style={{ maxWidth: 220 }}>Destination<input className="mono" value={dest} onChange={(e) => setDest(e.target.value)}
                  data-testid="rtb-route-destination" /></label>
                <label style={{ maxWidth: 280 }}>Target (internet gateway)
                  <select value={igwId || igws[0]?.id || ""} onChange={(e) => setIgwId(e.target.value)} data-testid="rtb-route-igw">
                    {igws.map((g) => <option key={g.id} value={g.id}>{g.name || g.id}</option>)}</select></label>
                <button className="small primary" disabled={!CIDR.test(dest) || igws.length === 0} onClick={() => void addRoute(selected)}
                  data-testid="rtb-route-add">Add route</button>
              </div>)}
            <h4 style={{ margin: 0 }}>Subnet associations</h4>
            <table className="data"><thead><tr><th>Subnet</th><th>Main</th><th /></tr></thead>
              <tbody>
                {selected.associations.map((a) => (
                  <tr key={a.id ?? "main"}><td className="small">{a.main ? "Every subnet (main)" : a.subnet_name}</td>
                    <td className="small">{a.main ? "Yes" : "No"}</td>
                    <td style={{ textAlign: "right" }}>{!ctx.readOnly && !a.main &&
                      <button className="small" onClick={() => void disassociate(selected, a)} data-testid="rtb-disassociate">Disassociate</button>}</td></tr>))}
              </tbody></table>
            {!ctx.readOnly && (
              <div className="row" style={{ flexWrap: "wrap", gap: 8, alignItems: "flex-end" }}>
                <label style={{ maxWidth: 320 }}>Subnet
                  <select value={subnetId || subnets[0]?.id || ""} onChange={(e) => setSubnetId(e.target.value)} data-testid="rtb-associate-subnet">
                    {subnets.filter((s) => s.vpc_id === selected.vpc_id).map((s) =>
                      <option key={s.id} value={s.id}>{s.name || s.id} ({s.cidr})</option>)}</select></label>
                <button className="small primary" disabled={subnets.length === 0} onClick={() => void associate(selected)}
                  data-testid="rtb-associate-add">Associate subnet</button>
              </div>)}
          </div>
        </div>)}
      {open && !ctx.readOnly && vpcs.length === 0 && <p className="muted small">Create a VPC first.</p>}
    </>
  );
}

// ------------------------------------------------------------------------------- internet gateways
function InternetGateways({ ctx }: { ctx: Ctx }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [vpcId, setVpcId] = useState("");
  const vpcs = ctx.data?.vpcs ?? [];
  async function create() {
    try {
      await api(`${ctx.base}/internet-gateways`, { method: "POST", body: { name } });
      ctx.notify("pass", `Successfully created internet gateway ${name}.`); setOpen(false); setName(""); await ctx.load();
    } catch (e) { ctx.fail(e); }
  }
  async function attach(g: Igw) {
    try { await api(`${ctx.base}/internet-gateways/${g.id}/attach`, { method: "POST", body: { vpc_id: vpcId || vpcs[0]?.id } });
      ctx.notify("pass", `Attached ${g.name} to the VPC.`); await ctx.load(); } catch (e) { ctx.fail(e); }
  }
  async function detach(g: Igw) {
    try { await api(`${ctx.base}/internet-gateways/${g.id}/detach`, { method: "POST" });
      ctx.notify("pass", `Detached ${g.name}.`); await ctx.load(); } catch (e) { ctx.fail(e); }
  }
  async function remove(g: Igw) {
    if (!confirm(`Delete internet gateway ${g.name}?`)) return;
    try { await api(`${ctx.base}/internet-gateways/${g.id}/delete`, { method: "POST" });
      ctx.notify("pass", `Deleted ${g.name}.`); await ctx.load(); } catch (e) { ctx.fail(e); }
  }
  return (
    <>
      <Panel title="Internet gateways" count={ctx.data?.internet_gateways.length} actions={
        <button className="small primary" disabled={ctx.readOnly} onClick={() => setOpen(!open)} data-testid="igw-open-create">Create internet gateway</button>}>
        <table className="data">
          <thead><tr><th>Name</th><th>Internet gateway ID</th><th>State</th><th>VPC</th><th /></tr></thead>
          <tbody>
            {ctx.data?.internet_gateways.length === 0 && <tr><td colSpan={5} className="muted">No internet gateways.</td></tr>}
            {ctx.data?.internet_gateways.map((g) => (
              <tr key={g.id} data-testid="igw-row">
                <td className="small">{g.name}</td>
                <td className="mono small">{g.id}</td>
                <td className="small"><span className="pill pass">{g.vpc_id ? "Attached" : "Detached"}</span></td>
                <td className="small">{g.vpc_name || "-"}</td>
                <td style={{ textAlign: "right" }}>{!ctx.readOnly && (g.vpc_id
                  ? <button className="small" onClick={() => void detach(g)} data-testid="igw-detach">Detach</button>
                  : <>
                      <select style={{ width: 170, marginRight: 6 }} value={vpcId} onChange={(e) => setVpcId(e.target.value)} data-testid="igw-attach-vpc">
                        <option value="">Select a VPC…</option>
                        {vpcs.map((v) => <option key={v.id} value={v.id}>{v.name || v.id}</option>)}</select>
                      <button className="small primary" disabled={!vpcId} onClick={() => void attach(g)} data-testid="igw-attach">Attach</button>
                      <button className="small" style={{ marginLeft: 6 }} onClick={() => void remove(g)} data-testid="igw-delete">Delete</button>
                    </>)}</td>
              </tr>))}
          </tbody>
        </table>
      </Panel>
      {open && !ctx.readOnly && (
        <div className="panel"><div className="panel-head"><h3>Create internet gateway</h3></div>
          <div className="panel-body">
            <label>Name tag<input value={name} onChange={(e) => setName(e.target.value)} placeholder="cafe-igw-1" data-testid="igw-name" /></label>
            <p className="help" style={{ margin: 0 }}>After creating it, attach it to your VPC (a gateway does nothing while detached).</p>
            <div className="actions">
              <button className="small" onClick={() => setOpen(false)}>Cancel</button>
              <button className="small primary" disabled={!name} onClick={() => void create()} data-testid="igw-create-save">Create internet gateway</button>
            </div>
          </div>
        </div>)}
    </>
  );
}

// --------------------------------------------------------------------------------- security groups
function RuleEditor({ rules, setRules, direction, testIdPrefix }:
  { rules: Rule[]; setRules: (r: Rule[]) => void; direction: "ingress" | "egress"; testIdPrefix: string }) {
  return (
    <>
      {rules.map((r, i) => (
        <div className="row" key={i} style={{ flexWrap: "wrap", gap: 8, alignItems: "flex-end" }}>
          <label style={{ maxWidth: 150 }}>Type
            <select value={r.protocol === "-1" ? "all" : r.protocol} data-testid={`${testIdPrefix}-protocol`}
              onChange={(e) => {
                const v = e.target.value;
                const next = [...rules];
                next[i] = v === "all" ? { protocol: "-1", from_port: null, to_port: null, cidr: r.cidr }
                  : { protocol: v, from_port: v === "icmp" ? -1 : 0, to_port: v === "icmp" ? -1 : 0, cidr: r.cidr };
                setRules(next);
              }}>
              <option value="tcp">TCP</option><option value="udp">UDP</option><option value="icmp">ICMP</option>
              <option value="all">All traffic</option></select></label>
          <label style={{ maxWidth: 110 }}>From port
            <input type="number" min={-1} max={65535} className="mono"
              disabled={r.protocol === "-1" || r.protocol === "icmp"}
              value={r.protocol === "-1" || r.protocol === "icmp" ? "" : (r.from_port ?? 0)}
              onChange={(e) => {
                const next = [...rules]; next[i] = { ...r, from_port: Number(e.target.value) }; setRules(next);
              }} data-testid={`${testIdPrefix}-from-port`} /></label>
          <label style={{ maxWidth: 110 }}>To port
            <input type="number" min={-1} max={65535} className="mono"
              disabled={r.protocol === "-1" || r.protocol === "icmp"}
              value={r.protocol === "-1" || r.protocol === "icmp" ? "" : (r.to_port ?? 0)}
              onChange={(e) => {
                const next = [...rules]; next[i] = { ...r, to_port: Number(e.target.value) }; setRules(next);
              }} data-testid={`${testIdPrefix}-to-port`} /></label>
          <label style={{ maxWidth: 200 }}>Source/Destination
            <input className="mono" value={r.cidr} onChange={(e) => {
              const next = [...rules]; next[i] = { ...r, cidr: e.target.value }; setRules(next);
            }} data-testid={`${testIdPrefix}-cidr`} /></label>
          <button type="button" className="small" onClick={() => setRules(rules.filter((_, j) => j !== i))}>Remove</button>
          <span className="sr-only">{direction}</span>
        </div>))}
      <div><button type="button" className="small" onClick={() => setRules([...rules, { protocol: "tcp", from_port: 80, to_port: 80, cidr: "0.0.0.0/0" }])}
        data-testid={`${testIdPrefix}-add`}>Add rule</button></div>
    </>
  );
}

function SecurityGroups({ ctx }: { ctx: Ctx }) {
  const [open, setOpen] = useState(false);
  const [vpcId, setVpcId] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("Managed by the Stackora console");
  const [detail, setDetail] = useState<string | null>(null);
  const [ingress, setIngress] = useState<Rule[]>([]);
  const [egress, setEgress] = useState<Rule[]>([]);
  const [dir, setDir] = useState<"ingress" | "egress">("ingress");
  const vpcs = ctx.data?.vpcs ?? [];
  const selected = ctx.data?.security_groups.find((g) => g.id === detail) ?? null;
  function openDetail(g: Sg) { setDetail(g.id); setIngress(g.ingress); setEgress(g.egress); setDir("ingress"); }
  async function create() {
    try {
      await api(`${ctx.base}/security-groups`, { method: "POST", body: { vpc_id: vpcId || vpcs[0]?.id, name, description } });
      ctx.notify("pass", `Successfully created security group ${name}.`); setOpen(false); setName(""); await ctx.load();
    } catch (e) { ctx.fail(e); }
  }
  async function saveRules(g: Sg) {
    try {
      // The API takes numbers; "All traffic"/ICMP rules come back with null ports.
      const payload = (rules: Rule[]) => rules.map((r) => ({ ...r, from_port: r.from_port ?? -1, to_port: r.to_port ?? -1 }));
      await api(`${ctx.base}/security-groups/${g.id}/rules`, { method: "PUT",
        body: { ingress: payload(ingress), egress: payload(egress) } });
      ctx.notify("pass", "Successfully saved the security group rules."); await ctx.load();
    } catch (e) { ctx.fail(e); }
  }
  async function remove(g: Sg) {
    if (!confirm(`Delete security group ${g.name}?`)) return;
    try { await api(`${ctx.base}/security-groups/${g.id}`, { method: "DELETE" });
      ctx.notify("pass", `Deleted security group ${g.name}.`); setDetail(null); await ctx.load(); } catch (e) { ctx.fail(e); }
  }
  return (
    <>
      <Panel title="Security groups" count={ctx.data?.security_groups.length} actions={
        <button className="small primary" disabled={ctx.readOnly || vpcs.length === 0} onClick={() => setOpen(!open)}
          data-testid="sg-open-create">Create security group</button>}>
        <table className="data">
          <thead><tr><th>Name</th><th>Security group ID</th><th>VPC</th><th>Inbound rules</th><th>Outbound rules</th><th /></tr></thead>
          <tbody>
            {ctx.data?.security_groups.length === 0 && <tr><td colSpan={6} className="muted">No security groups.</td></tr>}
            {ctx.data?.security_groups.map((g) => (
              <tr key={g.id} data-testid="sg-row">
                <td className="small"><button className="linklike" onClick={() => openDetail(g)} data-testid="sg-open-detail">{g.name}</button></td>
                <td className="mono small">{g.id}</td>
                <td className="small">{g.vpc_name || g.vpc_id}</td>
                <td className="small">{g.ingress.length}</td>
                <td className="small">{g.egress.length}</td>
                <td style={{ textAlign: "right" }}><button className="small" onClick={() => openDetail(g)}>Edit rules</button></td>
              </tr>))}
          </tbody>
        </table>
      </Panel>
      {open && !ctx.readOnly && (
        <div className="panel"><div className="panel-head"><h3>Create security group</h3></div>
          <div className="panel-body">
            <label>VPC
              <select value={vpcId || vpcs[0]?.id || ""} onChange={(e) => setVpcId(e.target.value)} data-testid="sg-vpc-select">
                {vpcs.map((v) => <option key={v.id} value={v.id}>{v.name || v.id} ({v.cidr})</option>)}</select></label>
            <label>Security group name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="web-sg" data-testid="sg-name" /></label>
            <label>Description<input value={description} onChange={(e) => setDescription(e.target.value)} data-testid="sg-description" /></label>
            <div className="actions">
              <button className="small" onClick={() => setOpen(false)}>Cancel</button>
              <button className="small primary" disabled={!name || !description} onClick={() => void create()}
                data-testid="sg-create-save">Create security group</button>
            </div>
          </div>
        </div>)}
      {selected && (
        <div className="panel" data-testid="sg-detail">
          <div className="panel-head"><h3>{selected.name}</h3>
            <button className="small" onClick={() => setDetail(null)}>Close</button>
            <button className="small" onClick={() => void remove(selected)} data-testid="sg-delete">Delete security group</button>
          </div>
          <div className="panel-body">
            <div className="tabs" role="tablist" aria-label="Rule direction" style={{ marginBottom: 0 }}>
              <button role="tab" aria-selected={dir === "ingress"} className={dir === "ingress" ? "tab on" : "tab"}
                onClick={() => setDir("ingress")} data-testid="sg-ingress">Inbound rules</button>
              <button role="tab" aria-selected={dir === "egress"} className={dir === "egress" ? "tab on" : "tab"}
                onClick={() => setDir("egress")} data-testid="sg-egress">Outbound rules</button>
            </div>
            {!ctx.readOnly && (dir === "ingress"
              ? <RuleEditor rules={ingress} setRules={setIngress} direction="ingress" testIdPrefix="sg-ingress-rule" />
              : <RuleEditor rules={egress} setRules={setEgress} direction="egress" testIdPrefix="sg-egress-rule" />)}
            {ctx.readOnly && <table className="data"><thead><tr><th>Protocol</th><th>Ports</th><th>Source/Destination</th></tr></thead>
              <tbody>{(dir === "ingress" ? ingress : egress).map((r, i) =>
                <tr key={i}><td className="small">{r.protocol}</td><td className="small">{r.from_port}-{r.to_port}</td><td className="mono small">{r.cidr}</td></tr>)}
              </tbody></table>}
            {!ctx.readOnly && <div className="actions">
              <button className="small primary" onClick={() => void saveRules(selected)} data-testid="sg-save-rules">Save rules</button></div>}
          </div>
        </div>)}
    </>
  );
}
