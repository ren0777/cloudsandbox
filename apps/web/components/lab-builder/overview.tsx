"use client";
import { KeyValueEditor, ListEditor } from "@/components/schema-form";
import type { Catalogue, Lab, Validation } from "@/lib/builder";
import { FieldErrors } from "./validation";

const ENGINE_HELP: Record<string, string> = {
  default: "Platform default (the lab must work on every primary engine)",
};

export function OverviewTab({ lab, catalogue, validation, onChange }: {
  lab: Lab; catalogue: Catalogue | null; validation: Validation | null; onChange: (lab: Lab) => void;
}) {
  const set = <K extends keyof Lab>(k: K, v: Lab[K]) => onChange({ ...lab, [k]: v });
  const num = (v: string) => (v === "" ? undefined : Number(v));
  const services = catalogue?.services ?? ["s3", "iam", "ec2", "lambda", "dynamodb"];
  const engines = ["default", ...(catalogue?.engines.primary ?? []), ...(catalogue?.engines.specialised ?? [])];
  return (
    <div className="stack" style={{ gap: 16 }}>
      <div className="lb-grid">
        <label className="lb-wide">Title<input value={lab.title ?? ""} maxLength={200} data-testid="lab-title"
          onChange={(e) => set("title", e.target.value)} /><FieldErrors v={validation} loc="title" /></label>
        <label>Lab id<input className="mono" value={lab.id ?? ""} maxLength={80} data-testid="lab-id"
          onChange={(e) => set("id", e.target.value)} />
          <span className="lb-hint">Lowercase letters, digits and dashes. Published versions share this id.</span>
          <FieldErrors v={validation} loc="id" /></label>
        <label>Version<input className="mono" value={lab.version ?? ""} maxLength={40} data-testid="lab-version"
          onChange={(e) => set("version", e.target.value)} />
          <span className="lb-hint">Each publish needs a new version, e.g. 1.1.0.</span><FieldErrors v={validation} loc="version" /></label>
        <label className="lb-wide">Summary<input value={lab.summary ?? ""} maxLength={1000}
          onChange={(e) => set("summary", e.target.value)} placeholder="One sentence shown on the lab card" />
          <FieldErrors v={validation} loc="summary" /></label>
        <label className="lb-wide">Story<textarea rows={6} value={lab.story ?? ""} maxLength={8000} data-testid="lab-story"
          onChange={(e) => set("story", e.target.value)} />
          <span className="lb-hint">Shown to students before they start. Supports **bold**, `code` and variables such as {"{{ bucket }}"}.</span>
          <FieldErrors v={validation} loc="story" /></label>
      </div>

      <fieldset className="lb-fieldset">
        <legend>Services</legend>
        <div className="row">
          {services.map((s) => (
            <label key={s} className="lb-inline">
              <input type="checkbox" checked={lab.services?.includes(s) ?? false}
                onChange={(e) => set("services", e.target.checked ? [...(lab.services ?? []), s] : (lab.services ?? []).filter((x) => x !== s))} />
              {s.toUpperCase()}
            </label>
          ))}
        </div>
        <FieldErrors v={validation} loc="services" />
      </fieldset>

      <div className="lb-grid">
        <label>Engine<select value={lab.runtime?.emulator ?? "default"} data-testid="lab-engine"
          onChange={(e) => set("runtime", { ...(lab.runtime ?? {}), emulator: e.target.value })}>
          {engines.map((e) => <option key={e} value={e}>{ENGINE_HELP[e] ?? e}</option>)}
        </select><FieldErrors v={validation} loc="runtime" /></label>
        <label>Duration (minutes)<input type="number" min={5} max={240} value={lab.duration_minutes ?? ""}
          onChange={(e) => set("duration_minutes", num(e.target.value) as number)} /><FieldErrors v={validation} loc="duration_minutes" /></label>
        <label>Idle timeout (minutes)<input type="number" min={1} max={240} value={lab.idle_minutes ?? ""} placeholder="platform default"
          onChange={(e) => set("idle_minutes", num(e.target.value))} /><FieldErrors v={validation} loc="idle_minutes" /></label>
        <label>Attempts per student<input type="number" min={1} max={20} value={lab.max_attempts ?? ""} placeholder="3"
          onChange={(e) => set("max_attempts", num(e.target.value))} /><FieldErrors v={validation} loc="max_attempts" /></label>
      </div>

      <fieldset className="lb-fieldset">
        <legend>Variables</legend>
        <p className="lb-hint" style={{ margin: "0 0 8px" }}>Per-student values, e.g. <code>bucket</code> = <code>{"cafe-{{ student_short_id }}"}</code>.
          Use them in text and checks as {"{{ name }}"}; scripts get them as upper-case environment variables ($BUCKET).</p>
        <KeyValueEditor value={lab.variables ?? {}} keyPlaceholder="name" testId="lab-variables"
          onChange={(m) => set("variables", m as Record<string, string>)} />
        <FieldErrors v={validation} loc="variables" />
      </fieldset>

      <fieldset className="lb-fieldset">
        <legend>Required operations</legend>
        <p className="lb-hint" style={{ margin: "0 0 8px" }}>Emulator operations students need (e.g. <code>s3:CreateBucket</code>). The lab is refused on engines that lack them.</p>
        <ListEditor values={lab.requires ?? []} placeholder="service:Operation" onChange={(rows) => set("requires", rows)} />
        <FieldErrors v={validation} loc="requires" />
      </fieldset>

      {(lab.kind === "break_fix" || lab.setup) && (
        <div className="banner info small">
          <div>This is a <strong>{lab.kind === "break_fix" ? "break-fix" : "guided"}</strong> lab
            {lab.setup && <> with the setup script <code>{lab.setup.script}</code></>}. Setup scripts are kept unchanged and can&apos;t be edited in the builder.</div>
        </div>
      )}
    </div>
  );
}
