"use client";
import { useEffect, useRef, useState } from "react";
import "@xterm/xterm/css/xterm.css";
import { api, ApiError } from "@/lib/api";

type Status = "connecting" | "open" | "reconnecting" | "closed";
const FINAL: Record<string, string> = {
  submitted: "Lab submitted. The terminal is closed.",
  reset: "Lab reset. Reconnecting when your fresh sandbox is ready…",
  stopped: "Lab ended. The terminal is closed.",
  failed: "Your sandbox stopped. The terminal is closed.",
  too_many_terminals: "This lab already has 2 terminals open. Close one to open another.",
  session_not_ready: "Your lab isn't running.",
};

export function Terminal({ sessionId, active }: { sessionId: string; active: boolean }) {
  const host = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<Status>("connecting");
  const [note, setNote] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0); // bump to reconnect manually

  useEffect(() => {
    if (!active || !host.current) return;
    let disposed = false;
    let ws: WebSocket | null = null;
    let tries = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let term: import("@xterm/xterm").Terminal | undefined;
    let fit: import("@xterm/addon-fit").FitAddon | undefined;
    let onResize: (() => void) | undefined;

    (async () => {
      const [{ Terminal: XTerm }, { FitAddon }] = await Promise.all([import("@xterm/xterm"), import("@xterm/addon-fit")]);
      if (disposed || !host.current) return;
      const mono = getComputedStyle(document.documentElement).getPropertyValue("--f-mono").trim();
      term = new XTerm({
        fontFamily: `${mono ? `${mono}, ` : ""}Consolas, monospace`, fontSize: 14, cursorBlink: true,
        theme: { background: "#0c1426", foreground: "#dbe6ff", cursor: "#5fd3f0", selectionBackground: "#26406f" },
        scrollback: 3000, allowProposedApi: false,
      });
      fit = new FitAddon();
      term.loadAddon(fit);
      term.open(host.current);
      fit.fit();
      term.onData((d) => ws?.readyState === WebSocket.OPEN && ws.send(JSON.stringify({ t: "i", d })));
      term.onResize(({ cols, rows }) => ws?.readyState === WebSocket.OPEN && ws.send(JSON.stringify({ t: "r", c: cols, r: rows })));
      onResize = () => fit?.fit();
      window.addEventListener("resize", onResize);
      connect();
    })();

    async function connect() {
      if (disposed) return;
      setStatus(tries ? "reconnecting" : "connecting");
      let ticket: string;
      try {
        ticket = (await api<{ ticket: string }>(`/api/sessions/${sessionId}/terminal-ticket`, { method: "POST" })).ticket;
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) { setStatus("closed"); setNote(FINAL.session_not_ready); return; }
        return retry();
      }
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws/terminal?ticket=${encodeURIComponent(ticket)}`);
      ws.binaryType = "arraybuffer";
      ws.onopen = () => {
        tries = 0;
        setStatus("open");
        setNote(null);
        if (term) ws!.send(JSON.stringify({ t: "r", c: term.cols, r: term.rows }));
        term?.focus();
      };
      ws.onmessage = (ev) => term?.write(typeof ev.data === "string" ? ev.data : new Uint8Array(ev.data));
      ws.onclose = (ev) => {
        if (disposed) return;
        if (ev.reason && FINAL[ev.reason]) { setStatus("closed"); setNote(FINAL[ev.reason]); return; }
        retry();
      };
    }

    function retry() {
      if (disposed) return;
      if (++tries > 5) { setStatus("closed"); setNote("Can't reach your terminal."); return; }
      setStatus("reconnecting");
      timer = setTimeout(connect, Math.min(8000, 500 * 2 ** tries));
    }

    return () => {
      disposed = true;
      clearTimeout(timer);
      if (onResize) window.removeEventListener("resize", onResize);
      ws?.close();
      term?.dispose();
    };
  }, [sessionId, active, nonce]);

  return (
    <div className="term-wrap">
      <div className="term-bar">
        <span className={`term-dot ${status}`} aria-hidden />
        <span className="mono small">AWS CLI · us-east-1 · isolated training cloud</span>
        <span className="grow" />
        <span className="small" role="status" aria-live="polite">
          {status === "open" ? "Connected" : status === "closed" ? "Disconnected"
            : status === "reconnecting" ? "Reconnecting…" : "Connecting…"}
        </span>
        {status === "closed" && active && <button className="small" onClick={() => { setNote(null); setNonce((n) => n + 1); }}>Reconnect</button>}
      </div>
      {note && <div className="term-note small">{note}</div>}
      <div ref={host} className="term-host" data-testid="terminal" />
      <style>{`
        .term-wrap { display: flex; flex-direction: column; height: 100%; background: var(--terminal); border-radius: var(--radius); overflow: hidden; border: 1px solid #1e2c4d; }
        .term-bar { display: flex; align-items: center; gap: 8px; padding: 8px 12px; color: #aab8d8; border-bottom: 1px solid #1e2c4d; }
        .term-bar button { background: transparent; color: #dbe6ff; border-color: #33466f; }
        .term-dot { width: 8px; height: 8px; border-radius: 50%; background: #6b7a99; }
        .term-dot.open { background: #3fd08c; } .term-dot.reconnecting, .term-dot.connecting { background: #f2c14e; }
        .term-dot.closed { background: #e5484d; }
        .term-note { background: #1a2542; color: #f2d58a; padding: 6px 12px; }
        .term-host { flex: 1; min-height: 0; padding: 8px 4px 4px 10px; }
        .term-host .xterm { height: 100%; }
      `}</style>
    </div>
  );
}
