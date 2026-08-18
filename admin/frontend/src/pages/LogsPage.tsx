import { useCallback, useEffect, useRef, useState } from "react";
import { getLogs } from "../api/nodes";
import { useWebSocket } from "../hooks/useWebSocket";
import { parseLogPayload } from "../lib/wsMessage";
import type { LogEntry, WsMessage } from "../types";
import "./LogsPage.css";

function levelClass(level: string): string {
  const normalized = level.toLowerCase();
  if (normalized === "error" || normalized === "critical") return "logs-row--error";
  if (normalized === "warning" || normalized === "warn") return "logs-row--warning";
  return "logs-row--info";
}

export default function LogsPage() {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getLogs(undefined, 100)
      .then((result) => {
        setLogs(result);
        setError(null);
      })
      .catch(() => setError("Logregels konden niet worden geladen."));
  }, []);

  // Live tail: een misvormd WS-frame wordt stil genegeerd (parseLogPayload geeft null),
  // net als useWebSocket zelf al doet bij ongeldige JSON -- geen page-level foutmelding hiervoor.
  const handleWsMessage = useCallback((msg: WsMessage) => {
    if (msg.type !== "log") return;
    const match = msg.topic.match(/^log\/(.+)$/);
    if (!match) return;
    const entry = parseLogPayload(msg.payload);
    if (!entry) return;
    setLogs((prev) => [...prev.slice(-199), { ...entry, node: match[1] }]);
  }, []);

  const { connected } = useWebSocket(handleWsMessage);

  useEffect(() => {
    if (!autoScroll || !scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [logs, autoScroll]);

  function handleScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    setAutoScroll(atBottom);
  }

  function resumeAutoScroll() {
    setAutoScroll(true);
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }

  return (
    <div className="logs-page">
      <header className="logs-header">
        <p className="logs-eyebrow">
          <span
            className="logs-eyebrow__led"
            data-connected={connected}
            aria-hidden="true"
          />
          {connected ? "Live verbinding" : "Verbinding verbroken — opnieuw verbinden…"}
        </p>
        <h1 className="logs-heading">Logs</h1>
      </header>

      {error && (
        <p className="logs-error" role="alert">
          {error}
        </p>
      )}

      <div className="logs-console" ref={scrollRef} onScroll={handleScroll}>
        {logs.length === 0 ? (
          <p className="logs-empty">Nog geen logregels ontvangen.</p>
        ) : (
          logs.map((log, i) => (
            <div className={`logs-row ${levelClass(log.level)}`} key={i}>
              <span className="logs-row__ts">
                {new Date(log.ts * 1000).toLocaleTimeString("nl-NL", { hour12: false })}
              </span>
              <span className="logs-row__node">{log.node}</span>
              <span className="logs-row__level">{log.level.toUpperCase()}</span>
              <span className="logs-row__msg">{log.msg}</span>
            </div>
          ))
        )}
      </div>

      {!autoScroll && (
        <button type="button" className="logs-resume" onClick={resumeAutoScroll}>
          ↓ Naar live
        </button>
      )}
    </div>
  );
}
