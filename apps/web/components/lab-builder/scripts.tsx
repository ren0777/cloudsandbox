"use client";
import { type Content, maxScore, readExpected, type Validation, writeExpected } from "@/lib/builder";
import { ErrorList } from "./validation";

const fileErrors = (v: Validation | null, name: string) => (v?.errors ?? []).filter((e) => e.loc === name || e.message.startsWith(`${name}:`));

export function ScriptsTab({ content, readOnlyFiles, validation, onFile }: {
  content: Content; readOnlyFiles: string[]; validation: Validation | null; onFile: (name: string, text: string) => void;
}) {
  const files = content.files ?? {};
  const exp = readExpected(files["private/expected.yaml"]);
  const full = maxScore(content.lab);
  return (
    <div className="stack" style={{ gap: 18 }}>
      <div className="banner info small"><div>Scripts are <strong>private</strong>: they run only in test sandboxes and are never shown to students.
        They run with the AWS CLI configured for the sandbox, and each lab variable as an upper-case environment variable (e.g. <code>$BUCKET</code>).</div></div>

      <label>Reference solution <span className="lb-hint mono">private/solution.sh</span>
        <textarea className="mono lb-code" rows={12} spellCheck={false} value={files["private/solution.sh"] ?? ""} data-testid="script-solution"
          onChange={(e) => onFile("private/solution.sh", e.target.value)} />
        <span className="lb-hint">Required. The test run expects it to score full marks ({full}).</span>
        <ErrorList rows={fileErrors(validation, "private/solution.sh")} /></label>

      <label>Partial solution (optional) <span className="lb-hint mono">private/partial.sh</span>
        <textarea className="mono lb-code" rows={8} spellCheck={false} value={files["private/partial.sh"] ?? ""} data-testid="script-partial"
          onChange={(e) => onFile("private/partial.sh", e.target.value)} placeholder="#!/bin/bash&#10;# Completes some tasks, to prove partial credit works" />
        <ErrorList rows={fileErrors(validation, "private/partial.sh")} /></label>

      {exp.simple ? (
        <label style={{ maxWidth: 320 }}>Expected partial score
          <input type="number" min={0} max={full} step="any" value={exp.partial} data-testid="expected-partial"
            placeholder={files["private/partial.sh"]?.trim() ? "required with a partial script" : "no partial scenario"}
            onChange={(e) => onFile("private/expected.yaml", writeExpected(e.target.value))} />
          <span className="lb-hint">Between 0 and {full}. The untouched sandbox must score 0.</span>
        </label>
      ) : <p className="small muted">private/expected.yaml has a custom format; edit it below.</p>}
      <details>
        <summary className="small">private/expected.yaml</summary>
        <textarea className="mono lb-code" rows={5} spellCheck={false} value={files["private/expected.yaml"] ?? ""}
          onChange={(e) => onFile("private/expected.yaml", e.target.value)} />
      </details>
      <ErrorList rows={fileErrors(validation, "private/expected.yaml")} />

      <label>Teaching notes <span className="lb-hint mono">private/notes.md</span>
        <textarea rows={5} value={files["private/notes.md"] ?? ""} data-testid="notes"
          onChange={(e) => onFile("private/notes.md", e.target.value)} placeholder="Answers, common mistakes, marking notes (instructors only)" /></label>

      {readOnlyFiles.length > 0 && (
        <section>
          <div className="lb-sub">Read-only files</div>
          <p className="lb-hint" style={{ margin: "0 0 8px" }}>Kept unchanged from the cloned or imported pack (setup scripts can&apos;t be authored in the builder yet).</p>
          {readOnlyFiles.map((n) => (
            <details key={n} className="lb-ro">
              <summary className="mono small">{n}</summary>
              <pre className="mono lb-code">{files[n]}</pre>
            </details>
          ))}
        </section>
      )}
    </div>
  );
}
