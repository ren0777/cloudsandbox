"use client";
// Form fields generated from a grader check's parameter JSON Schema (Pydantic model_json_schema()):
// strings, numbers, booleans, enums, key-value maps, lists, and a JSON editor for free-form values.
import { useState } from "react";
import { effective, type JsonSchema, parseScalar, showScalar } from "@/lib/builder";

type Obj = Record<string, unknown>;

export function SchemaForm({ schema, value, onChange, idPrefix }: {
  schema: JsonSchema; value: Obj; onChange: (v: Obj) => void; idPrefix: string;
}) {
  const props = Object.entries(schema.properties ?? {});
  if (props.length === 0) return <p className="small muted" style={{ margin: 0 }}>This check has no parameters.</p>;
  const required = new Set(schema.required ?? []);
  const set = (key: string, v: unknown) => {
    const next = { ...value };
    if (v === undefined) delete next[key];
    else next[key] = v;
    onChange(next);
  };
  return (
    <div className="sf-grid">
      {props.map(([key, raw]) => {
        const { schema: f, nullable } = effective(raw, schema);
        return (
          <Field key={key} name={key} schema={f} nullable={nullable} required={required.has(key)}
            value={value[key]} onChange={(v) => set(key, v)} id={`${idPrefix}-${key}`} />
        );
      })}
      <style>{`
        .sf-grid { display: grid; gap: 10px 14px; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); }
        .sf-wide { grid-column: 1 / -1; }
        .sf-hint { font-weight: 400; color: var(--muted); font-size: 12px; }
        .sf-rows { display: flex; flex-direction: column; gap: 6px; }
        .sf-rows .row { flex-wrap: nowrap; }
        .sf-err { color: var(--fail); font-weight: 400; font-size: 12px; }
        .sf-check { flex-direction: row !important; align-items: center; gap: 8px !important; }
        .sf-check input { width: auto; }
      `}</style>
    </div>
  );
}

function Label({ name, schema, required }: { name: string; schema: JsonSchema; required: boolean }) {
  return <>{schema.title ?? name}{required && <span aria-hidden style={{ color: "var(--fail)" }}> *</span>}
    <span className="sf-hint mono"> {name}</span></>;
}

function Field({ name, schema, nullable, required, value, onChange, id }: {
  name: string; schema: JsonSchema; nullable: boolean; required: boolean; value: unknown;
  onChange: (v: unknown) => void; id: string;
}) {
  const hint = schema.description ?? (schema.pattern ? `Format: ${schema.pattern}` : undefined);
  const placeholder = schema.default !== undefined && schema.default !== null ? `default: ${showScalar(schema.default)}` : undefined;
  const optional = !required;

  if (schema.enum) {
    return (
      <label>
        <Label name={name} schema={schema} required={required} />
        <select id={id} value={value === undefined || value === null ? "" : String(value)} data-testid={`param-${name}`}
          onChange={(e) => onChange(e.target.value === "" ? undefined : schema.enum!.find((x) => String(x) === e.target.value))}>
          {(optional || nullable) && <option value="">{placeholder ?? "(not set)"}</option>}
          {schema.enum.map((x) => <option key={String(x)} value={String(x)}>{String(x)}</option>)}
        </select>
      </label>
    );
  }
  if (schema.type === "boolean") {
    const checked = value === undefined ? Boolean(schema.default) : Boolean(value);
    return (
      <label className="sf-check">
        <input id={id} type="checkbox" checked={checked} data-testid={`param-${name}`}
          onChange={(e) => onChange(e.target.checked === Boolean(schema.default) && optional ? undefined : e.target.checked)} />
        <span><Label name={name} schema={schema} required={required} /></span>
      </label>
    );
  }
  if (schema.type === "integer" || schema.type === "number") {
    return (
      <label>
        <Label name={name} schema={schema} required={required} />
        <input id={id} type="number" step={schema.type === "integer" ? 1 : "any"} min={schema.minimum} max={schema.maximum}
          value={value === undefined || value === null ? "" : String(value)} placeholder={placeholder} data-testid={`param-${name}`}
          onChange={(e) => onChange(e.target.value === "" ? (nullable && required ? null : undefined) : Number(e.target.value))} />
      </label>
    );
  }
  if (schema.type === "string") {
    return (
      <label className={(schema.maxLength ?? 0) > 300 ? "sf-wide" : undefined}>
        <Label name={name} schema={schema} required={required} />
        <input id={id} value={value === undefined || value === null ? "" : String(value)} placeholder={placeholder}
          maxLength={schema.maxLength} data-testid={`param-${name}`}
          onChange={(e) => onChange(e.target.value === "" && optional ? undefined : e.target.value)} />
        {hint && <span className="sf-hint">{hint}</span>}
      </label>
    );
  }
  if (schema.type === "array" && schema.items && ["string", "integer", "number"].includes(schema.items.type ?? "")) {
    const numeric = schema.items.type !== "string";
    return (
      <div className="sf-wide">
        <label htmlFor={id}><span><Label name={name} schema={schema} required={required} /></span></label>
        <ListEditor id={id} values={Array.isArray(value) ? value.map(showScalar) : []}
          onChange={(rows) => onChange(rows.length || required ? rows.map((r) => (numeric ? Number(r) : r)) : undefined)} />
      </div>
    );
  }
  if (schema.type === "object" && typeof schema.additionalProperties === "object") {
    const valueSchema = schema.additionalProperties;
    const typed = valueSchema.type !== "string";  // e.g. anyOf string/number/bool: values are parsed as JSON scalars
    return (
      <div className="sf-wide">
        <label htmlFor={id}><span><Label name={name} schema={schema} required={required} />
          {typed && <span className="sf-hint"> (values: text, numbers or true/false)</span>}</span></label>
        <KeyValueEditor id={id} value={(value ?? {}) as Record<string, unknown>}
          onChange={(m) => onChange(Object.keys(m).length || required ? m : undefined)} typed={typed} />
      </div>
    );
  }
  if (schema.anyOf && schema.anyOf.every((b) => ["string", "integer", "number", "boolean"].includes(b.type ?? ""))) {
    return (
      <label>
        <Label name={name} schema={schema} required={required} />
        <input id={id} value={showScalar(value)} placeholder={placeholder ?? "text, number or true/false"} data-testid={`param-${name}`}
          onChange={(e) => onChange(e.target.value === "" ? (required ? "" : undefined) : parseScalar(e.target.value))} />
      </label>
    );
  }
  return (
    <div className="sf-wide">
      <label htmlFor={id}><span><Label name={name} schema={schema} required={required} />
        <span className="sf-hint"> (JSON)</span></span></label>
      <JsonEditor id={id} value={value} onChange={onChange} optional={optional} />
    </div>
  );
}

export function ListEditor({ id, values, onChange, placeholder, testId }: {
  id?: string; values: string[]; onChange: (rows: string[]) => void; placeholder?: string; testId?: string;
}) {
  const set = (i: number, v: string) => onChange(values.map((x, j) => (i === j ? v : x)));
  return (
    <div className="sf-rows" id={id} data-testid={testId}>
      {values.map((v, i) => (
        <div key={i} className="row">
          <input value={v} onChange={(e) => set(i, e.target.value)} placeholder={placeholder} aria-label={`Item ${i + 1}`} />
          <button type="button" className="small ghost" aria-label={`Remove item ${i + 1}`}
            onClick={() => onChange(values.filter((_, j) => j !== i))}>✕</button>
        </div>
      ))}
      <div><button type="button" className="small" onClick={() => onChange([...values, ""])}>+ Add</button></div>
    </div>
  );
}

/** Key-value rows. Rows are local state so a half-typed or duplicate key doesn't lose text; the parent gets
 * the map of non-empty keys. Remount (key prop) to load a new value. */
export function KeyValueEditor({ id, value, onChange, typed = false, keyPlaceholder = "key", testId }: {
  id?: string; value: Record<string, unknown>; onChange: (m: Record<string, unknown>) => void; typed?: boolean;
  keyPlaceholder?: string; testId?: string;
}) {
  const [rows, setRows] = useState<[string, string][]>(() => Object.entries(value).map(([k, v]) => [k, showScalar(v)]));
  const push = (next: [string, string][]) => {
    setRows(next);
    const m: Record<string, unknown> = {};
    for (const [k, v] of next) if (k.trim()) m[k.trim()] = typed ? parseScalar(v) : v;
    onChange(m);
  };
  const keys = rows.map(([k]) => k.trim()).filter(Boolean);
  const dup = keys.find((k, i) => keys.indexOf(k) !== i);
  return (
    <div className="sf-rows" id={id} data-testid={testId}>
      {rows.map(([k, v], i) => (
        <div key={i} className="row">
          <input value={k} placeholder={keyPlaceholder} aria-label={`Key ${i + 1}`} style={{ maxWidth: 220 }}
            onChange={(e) => push(rows.map((r, j) => (i === j ? [e.target.value, r[1]] : r)))} />
          <input value={v} placeholder="value" aria-label={`Value ${i + 1}`}
            onChange={(e) => push(rows.map((r, j) => (i === j ? [r[0], e.target.value] : r)))} />
          <button type="button" className="small ghost" aria-label={`Remove ${k || `row ${i + 1}`}`}
            onClick={() => push(rows.filter((_, j) => j !== i))}>✕</button>
        </div>
      ))}
      {dup && <span className="sf-err">“{dup}” appears twice; only the last value is kept.</span>}
      <div><button type="button" className="small" onClick={() => setRows([...rows, ["", ""]])}>+ Add</button></div>
    </div>
  );
}

function JsonEditor({ id, value, onChange, optional }: { id: string; value: unknown; onChange: (v: unknown) => void; optional: boolean }) {
  const [text, setText] = useState(() => (value === undefined ? "" : JSON.stringify(value, null, 2)));
  const [err, setErr] = useState<string | null>(null);
  return (
    <>
      <textarea id={id} className="mono" rows={4} value={text} spellCheck={false}
        onChange={(e) => {
          setText(e.target.value);
          if (!e.target.value.trim()) { setErr(null); onChange(optional ? undefined : null); return; }
          try { onChange(JSON.parse(e.target.value)); setErr(null); } catch { setErr("Not valid JSON yet; the last valid value is kept."); }
        }} />
      {err && <span className="sf-err">{err}</span>}
    </>
  );
}
