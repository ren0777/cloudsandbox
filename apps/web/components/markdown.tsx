// Tiny, safe renderer for lab text: paragraphs, **bold** and `code`. Never injects HTML.
import { Fragment } from "react";

function inline(text: string, key: string) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean);
  return parts.map((p, i) =>
    p.startsWith("**") ? <strong key={`${key}-${i}`}>{p.slice(2, -2)}</strong>
      : p.startsWith("`") ? <code key={`${key}-${i}`} className="inline-code">{p.slice(1, -1)}</code>
      : <Fragment key={`${key}-${i}`}>{p}</Fragment>);
}

export function Markdown({ text }: { text: string }) {
  const paras = text.trim().split(/\n\s*\n/);
  return (
    <div className="md">
      {paras.map((p, i) => <p key={i}>{inline(p.replace(/\n/g, " "), String(i))}</p>)}
      <style>{`
        .md p { margin: 0 0 10px; } .md p:last-child { margin-bottom: 0; }
        .inline-code { background: #eef2f8; border: 1px solid var(--line); padding: 1px 5px; border-radius: 5px; font-family: var(--font-mono); font-size: .88em; word-break: break-all; }
      `}</style>
    </div>
  );
}
