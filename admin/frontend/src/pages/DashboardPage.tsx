import { useEffect, useState, useCallback } from "react";
import { getNodes } from "../api/nodes";
import { getSchedule, putSchedule, emergencyStop, wake } from "../api/schedule";
import { listScenes } from "../api/scenes";
import { listSceneEdges } from "../api/sceneEdges";
import { testMirror } from "../api/mirror";
import { startMirrorProcess, stopMirrorProcess, getMirrorProcessStatus } from "../api/mirrorProcess";
import { useWebSocket } from "../hooks/useWebSocket";
import NodeStatusCard from "../components/NodeStatusCard";
import SceneWizardModal from "../components/SceneWizardModal";
import SceneGraphCanvas from "../components/SceneGraphCanvas";
import type { NodeStatusMap, Schedule, Scene, SceneEdge, WsMessage } from "../types";
import "./DashboardPage.css";

export default function DashboardPage() {
  const [nodes, setNodes] = useState<NodeStatusMap>({});
  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [savingSchedule, setSavingSchedule] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [waking, setWaking] = useState(false);
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [sceneEdges, setSceneEdges] = useState<SceneEdge[]>([]);
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardSceneId, setWizardSceneId] = useState<number | null>(null);
  const [wizardInitialStep, setWizardInitialStep] = useState<"input" | "animation" | "output">("input");
  const [running, setRunning] = useState(false);
  const [processBusy, setProcessBusy] = useState(false);
  const [logLines, setLogLines] = useState<string[]>([]);
  const [testing, setTesting] = useState(false);

  function refreshScenes() {
    listScenes()
      .then(setScenes)
      .catch(() => setError("Scenes konden niet worden geladen."));
    listSceneEdges()
      .then(setSceneEdges)
      .catch(() => setError("Verbindingen konden niet worden geladen."));
  }

  useEffect(() => {
    getNodes()
      .then(setNodes)
      .catch(() => setError("Nodes konden niet worden geladen."));
    getSchedule()
      .then(setSchedule)
      .catch(() => setError("Tijdvenster kon niet worden geladen."));
    refreshScenes();
    getMirrorProcessStatus()
      .then((result) => setRunning(result.running))
      .catch(() => {
        /* status blijft "gestopt" tonen bij een netwerkfout */
      });
  }, []);

  const handleWsMessage = useCallback((msg: WsMessage) => {
    if (msg.type === "status") {
      const match = msg.topic.match(/^status\/(.+)$/);
      if (match) {
        setNodes((prev) => ({ ...prev, [match[1]]: { status: msg.payload as "online" | "offline" } }));
      }
      return;
    }
    if (msg.type === "log" && msg.topic === "process/mirror-node") {
      setLogLines((prev) => [...prev, msg.payload].slice(-200));
    }
  }, []);

  const { connected } = useWebSocket(handleWsMessage);

  // Korte, tijdelijke succesmelding (vooral voor noodstop/wakker maken: de
  // meest kritieke knoppen in de app mogen nooit stil blijven bij succes).
  function showNotice(message: string) {
    setNotice(message);
    window.setTimeout(() => setNotice(null), 3000);
  }

  async function handleScheduleSave() {
    if (!schedule) return;
    setSavingSchedule(true);
    try {
      await putSchedule(schedule);
      setError(null);
    } catch {
      setError("Opslaan van tijdvenster is mislukt. Probeer het opnieuw.");
    } finally {
      setSavingSchedule(false);
    }
  }

  async function handleEmergencyStop() {
    setStopping(true);
    try {
      await emergencyStop();
      setError(null);
      showNotice("Noodstop geactiveerd.");
    } catch {
      setError("Noodstop is mislukt. Probeer het opnieuw.");
    } finally {
      setStopping(false);
    }
  }

  async function handleWake() {
    setWaking(true);
    try {
      await wake();
      setError(null);
      showNotice("Systeem wakker gemaakt.");
    } catch {
      setError("Wakker maken is mislukt. Probeer het opnieuw.");
    } finally {
      setWaking(false);
    }
  }

  function openWizard(id: number | null, step: "input" | "animation" | "output" = "input") {
    setWizardSceneId(id);
    setWizardInitialStep(step);
    setWizardOpen(true);
  }

  async function handleStartProcess() {
    setProcessBusy(true);
    try {
      const status = await startMirrorProcess();
      setRunning(status.running);
    } catch {
      setError("Mirror-node starten is mislukt.");
    } finally {
      setProcessBusy(false);
    }
  }

  async function handleStopProcess() {
    setProcessBusy(true);
    try {
      const status = await stopMirrorProcess();
      setRunning(status.running);
    } catch {
      setError("Mirror-node stoppen is mislukt.");
    } finally {
      setProcessBusy(false);
    }
  }

  async function handleTest() {
    setTesting(true);
    try {
      await testMirror();
    } catch {
      setError("Testoproep is mislukt.");
    } finally {
      setTesting(false);
    }
  }

  const nodeEntries = Object.entries(nodes);
  const onlineCount = nodeEntries.filter(([, info]) => info.status === "online").length;

  return (
    <div className="dash-page">
      <header className="dash-header">
        <div>
          <p className="dash-eyebrow">
            <span className={`dash-eyebrow__led ${connected ? "dash-eyebrow__led--on" : "dash-eyebrow__led--off"}`} aria-hidden="true" />
            {connected ? "LIVE VERBINDING" : "VERBINDEN…"}
          </p>
          <h1 className="dash-heading">Beheerpagina</h1>
        </div>
        <p className="dash-tally">
          <span className="dash-tally__count">{onlineCount}</span>
          <span className="dash-tally__total">/ {nodeEntries.length} online</span>
        </p>
      </header>

      {error && (
        <p className="dash-error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="dash-notice" role="status">
          {notice}
        </p>
      )}

      <section className="dash-panel">
        <p className="dash-panel__eyebrow">Scenes</p>
        <SceneGraphCanvas
          scenes={scenes}
          edges={sceneEdges}
          onSceneClick={(id, step) => openWizard(id, step)}
          onGraphChanged={refreshScenes}
          onAddScene={() => openWizard(null)}
        />
      </section>

      <section className="dash-panel">
        <p className="dash-panel__eyebrow">Mirror-node</p>
        <div className="mirror-process-row">
          <span className={`mirror-process-status ${running ? "mirror-process-status--running" : ""}`}>
            {running ? "Draait" : "Gestopt"}
          </span>
          <button type="button" onClick={handleStartProcess} disabled={processBusy || running}>
            {processBusy ? "Bezig…" : "Start"}
          </button>
          <button type="button" onClick={handleStopProcess} disabled={processBusy || !running}>
            {processBusy ? "Bezig…" : "Stop"}
          </button>
          <button type="button" onClick={handleTest} disabled={testing}>
            {testing ? "Bezig…" : "Test"}
          </button>
        </div>
        <pre className="mirror-process-log">
          {logLines.length ? logLines.join("\n") : "Nog geen logregels — start de mirror-node om ze hier te zien."}
        </pre>
      </section>

      {wizardOpen && (
        <SceneWizardModal
          sceneId={wizardSceneId}
          initialStep={wizardInitialStep}
          onClose={() => setWizardOpen(false)}
          onSaved={refreshScenes}
        />
      )}

      <section className="dash-panel">
        <p className="dash-panel__eyebrow">Nodes op het paneel</p>
        {nodeEntries.length === 0 ? (
          <p className="dash-empty">Nog geen nodes gezien.</p>
        ) : (
          <div className="node-grid">
            {nodeEntries.map(([name, info]) => (
              <NodeStatusCard key={name} name={name} status={info.status} />
            ))}
          </div>
        )}
      </section>

      <section className="dash-panel dash-panel--controls">
        <p className="dash-panel__eyebrow">Noodbediening</p>
        <div className="dash-controls">
          <button
            className="estop-button"
            onClick={handleEmergencyStop}
            disabled={stopping}
            type="button"
          >
            <span className="estop-button__ring">
              <span className="estop-button__label">
                {stopping ? (
                  "Bezig…"
                ) : (
                  <>
                    Nood
                    <br />
                    stop
                  </>
                )}
              </span>
            </span>
          </button>
          <button className="wake-button" onClick={handleWake} disabled={waking} type="button">
            {waking ? "Bezig…" : "Wakker maken"}
          </button>
        </div>
      </section>

      {schedule && (
        <section className="dash-panel dash-panel--schedule">
          <p className="dash-panel__eyebrow">Tijdvenster</p>
          <div className="schedule-form">
            <label className="schedule-field">
              <span className="schedule-field__label">Aan</span>
              <input
                className="schedule-field__input"
                type="time"
                value={schedule.on_time}
                onChange={(e) => setSchedule({ ...schedule, on_time: e.target.value })}
              />
            </label>
            <label className="schedule-field">
              <span className="schedule-field__label">Uit</span>
              <input
                className="schedule-field__input"
                type="time"
                value={schedule.off_time}
                onChange={(e) => setSchedule({ ...schedule, off_time: e.target.value })}
              />
            </label>
            <label className="schedule-toggle">
              <input
                type="checkbox"
                checked={schedule.enabled}
                onChange={(e) => setSchedule({ ...schedule, enabled: e.target.checked })}
              />
              <span className="schedule-toggle__rocker" aria-hidden="true" />
              <span className="schedule-toggle__label">Ingeschakeld</span>
            </label>
            <button
              className="schedule-save"
              onClick={handleScheduleSave}
              disabled={savingSchedule}
              type="button"
            >
              {savingSchedule ? "Bezig…" : "Opslaan"}
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
