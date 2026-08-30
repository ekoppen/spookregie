import { useEffect, useRef, useState } from "react";
import { getMirrorConfig, putMirrorConfig, previewMirrorConfig, testMirror } from "../api/mirror";
import { getSettings, putSettings } from "../api/settings";
import { startMirrorProcess, stopMirrorProcess, getMirrorProcessStatus } from "../api/mirrorProcess";
import { useWebSocket } from "../hooks/useWebSocket";
import MediaLibrary from "../components/MediaLibrary";
import OverlayCanvas from "../components/OverlayCanvas";
import type { AppSettings, MirrorConfig, WsMessage } from "../types";
import "./MirrorPage.css";

// MJPEG-over-HTTP kan de browser direct tonen via <img>; rtsp:// of een
// lokale index (getal) niet -- daarvoor blijft alleen de verwerkte
// "Live preview" (via mirror_stream_url, zodra mirror_node draait) bruikbaar.
function isBrowserViewable(source: string): boolean {
  return source.startsWith("http://") || source.startsWith("https://");
}

const EFFECTS = ["xray", "thermal", "contour", "posterize"] as const;

const FIELD_LABELS: Record<string, string> = {
  intensity: "Intensiteit",
  threshold1: "Drempel 1",
  threshold2: "Drempel 2",
  levels: "Niveaus",
};

function paramFieldsFor(effect: MirrorConfig["effect"]): string[] {
  switch (effect) {
    case "xray":
    case "thermal":
      return ["intensity"];
    case "contour":
      return ["threshold1", "threshold2"];
    case "posterize":
      return ["levels"];
  }
}

export default function MirrorPage() {
  const [config, setConfig] = useState<MirrorConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [streamUrl, setStreamUrl] = useState("");
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [cameraSourceDraft, setCameraSourceDraft] = useState("");
  const [savingCameraSource, setSavingCameraSource] = useState(false);
  const [canvasWidthDraft, setCanvasWidthDraft] = useState("");
  const [canvasHeightDraft, setCanvasHeightDraft] = useState("");
  const [running, setRunning] = useState(false);
  const [processBusy, setProcessBusy] = useState(false);
  const [logLines, setLogLines] = useState<string[]>([]);

  useEffect(() => {
    getMirrorConfig()
      .then((result) => {
        setConfig(result);
        setCanvasWidthDraft(result.canvas_size ? String(result.canvas_size[0]) : "");
        setCanvasHeightDraft(result.canvas_size ? String(result.canvas_size[1]) : "");
        setError(null);
      })
      .catch(() => setError("Spiegelconfiguratie kon niet worden geladen."));
    getSettings()
      .then((result) => {
        setStreamUrl(result.mirror_stream_url);
        setSettings(result);
        setCameraSourceDraft(result.mirror_camera_source);
      })
      .catch(() => {
        /* live preview blijft dan gewoon "niet beschikbaar" tonen */
      });
    getMirrorProcessStatus()
      .then((result) => setRunning(result.running))
      .catch(() => {
        /* status blijft "gestopt" tonen bij een netwerkfout */
      });
  }, []);

  // Live preview: leading-edge throttle (max. 1x per 150ms), niet debounce --
  // debounce stuurt tijdens een sleep pas iets zodra de operator stopt met
  // bewegen, waardoor de live preview de sleep niet in (bijna-)realtime volgt.
  // Faalt stil (console only) per wijziging om alert-ruis te voorkomen.
  const lastPreviewSentAtRef = useRef(0);
  const previewThrottleTimerRef = useRef<number | null>(null);

  useEffect(() => {
    if (!config) return;
    const THROTTLE_MS = 150;

    function send() {
      lastPreviewSentAtRef.current = Date.now();
      previewMirrorConfig(config!).catch((err) => console.error("Preview mislukt:", err));
    }

    const elapsed = Date.now() - lastPreviewSentAtRef.current;
    if (elapsed >= THROTTLE_MS) {
      send();
    } else {
      if (previewThrottleTimerRef.current) window.clearTimeout(previewThrottleTimerRef.current);
      previewThrottleTimerRef.current = window.setTimeout(send, THROTTLE_MS - elapsed);
    }

    return () => {
      if (previewThrottleTimerRef.current) window.clearTimeout(previewThrottleTimerRef.current);
    };
  }, [config]);

  useWebSocket((msg: WsMessage) => {
    if (msg.type === "log" && msg.topic === "process/mirror-node") {
      setLogLines((prev) => [...prev, msg.payload].slice(-200));
    }
  });

  function update(patch: Partial<MirrorConfig>) {
    setConfig((prev) => (prev ? { ...prev, ...patch } : prev));
  }

  function updateCanvasSize(widthStr: string, heightStr: string) {
    const w = parseInt(widthStr, 10);
    const h = parseInt(heightStr, 10);
    update({ canvas_size: w > 0 && h > 0 ? [w, h] : null });
  }

  async function handleSaveCameraSource() {
    if (!settings) return;
    setSavingCameraSource(true);
    try {
      await putSettings({
        mqtt_host: settings.mqtt_host,
        mqtt_port: settings.mqtt_port,
        mqtt_user: settings.mqtt_user,
        ha_url: settings.ha_url,
        mirror_stream_url: settings.mirror_stream_url,
        mqtt_topic_prefix: settings.mqtt_topic_prefix,
        mirror_camera_source: cameraSourceDraft,
      });
      const refreshed = await getSettings();
      setSettings(refreshed);
      setCameraSourceDraft(refreshed.mirror_camera_source);
      setError(null);
    } catch {
      setError("Camera-bron opslaan is mislukt.");
    } finally {
      setSavingCameraSource(false);
    }
  }

  async function handleApply() {
    if (!config) return;
    setSaving(true);
    try {
      await putMirrorConfig(config);
      setError(null);
    } catch {
      setError("Toepassen is mislukt. Probeer het opnieuw.");
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    setTesting(true);
    try {
      await testMirror();
      setError(null);
    } catch {
      setError("Testoproep is mislukt.");
    } finally {
      setTesting(false);
    }
  }

  async function handleStartProcess() {
    setProcessBusy(true);
    try {
      const status = await startMirrorProcess();
      setRunning(status.running);
      setError(null);
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
      setError(null);
    } catch {
      setError("Mirror-node stoppen is mislukt.");
    } finally {
      setProcessBusy(false);
    }
  }

  return (
    <div className="mirror-page">
      <header className="mirror-header">
        <p className="mirror-eyebrow">
          <span className="mirror-eyebrow__led" aria-hidden="true" />
          Spiegel-node
        </p>
        <h1 className="mirror-heading">Mirror-effect</h1>
      </header>

      {error && (
        <p className="mirror-error" role="alert">
          {error}
        </p>
      )}

      {!config ? (
        <p className="mirror-loading">Laden…</p>
      ) : (
        <>
          <section className="mirror-panel">
            <p className="mirror-panel__eyebrow">Effect & parameters</p>
            <div className="mirror-effect-row">
              <label className="mirror-field">
                <span className="mirror-field__label">Effect</span>
                <select
                  className="mirror-field__select"
                  value={config.effect}
                  onChange={(e) =>
                    update({ effect: e.target.value as MirrorConfig["effect"], params: {} })
                  }
                >
                  {EFFECTS.map((effect) => (
                    <option key={effect} value={effect}>
                      {effect}
                    </option>
                  ))}
                </select>
              </label>
              {paramFieldsFor(config.effect).map((field) => (
                <label className="mirror-field" key={field}>
                  <span className="mirror-field__label">{FIELD_LABELS[field] ?? field}</span>
                  <input
                    className="mirror-field__input"
                    type="number"
                    step="0.1"
                    value={config.params[field] ?? ""}
                    onChange={(e) => {
                      const parsed = parseFloat(e.target.value);
                      // Een leeg veld (mid-edit) geeft parseFloat("") -> NaN;
                      // dat nooit persisteren, anders wordt "null" retained
                      // naar MQTT gepubliceerd en breekt het effect op de node.
                      if (Number.isNaN(parsed)) return;
                      update({ params: { ...config.params, [field]: parsed } });
                    }}
                  />
                </label>
              ))}
            </div>
          </section>

          <section className="mirror-panel">
            <p className="mirror-panel__eyebrow">Overlay-bibliotheek</p>
            <MediaLibrary
              category="mirror_overlay"
              selectionMode="single"
              selected={config.overlay_hash ? [config.overlay_hash] : []}
              onSelectionChange={(hashes) => update({ overlay_hash: hashes[0] ?? null })}
            />
          </section>

          <section className="mirror-panel">
            <p className="mirror-panel__eyebrow">Camera-bron</p>
            <div className="mirror-effect-row">
              <label className="mirror-field mirror-field--wide">
                <span className="mirror-field__label">URL (optioneel)</span>
                <input
                  className="mirror-field__input"
                  type="text"
                  value={cameraSourceDraft}
                  placeholder="bijv. http://192.168.178.80:8080/stream"
                  onChange={(e) => setCameraSourceDraft(e.target.value)}
                />
              </label>
              <button
                className="mirror-apply"
                type="button"
                onClick={handleSaveCameraSource}
                disabled={savingCameraSource || !settings}
              >
                {savingCameraSource ? "Bezig…" : "Opslaan"}
              </button>
            </div>
            <p className="mirror-field__label" style={{ marginTop: "0.5rem" }}>
              Leeg = de lokale camera op de node zelf. De node haalt dit pas op bij zijn
              eerstvolgende herstart.
            </p>
          </section>

          <section className="mirror-panel">
            <p className="mirror-panel__eyebrow">Weergaveformaat & compositie</p>
            <div className="mirror-effect-row">
              <label className="mirror-field">
                <span className="mirror-field__label">Breedte (optioneel)</span>
                <input
                  className="mirror-field__input"
                  type="number"
                  min="1"
                  value={canvasWidthDraft}
                  placeholder="bijv. 576"
                  onChange={(e) => {
                    setCanvasWidthDraft(e.target.value);
                    updateCanvasSize(e.target.value, canvasHeightDraft);
                  }}
                />
              </label>
              <label className="mirror-field">
                <span className="mirror-field__label">Hoogte (optioneel)</span>
                <input
                  className="mirror-field__input"
                  type="number"
                  min="1"
                  value={canvasHeightDraft}
                  placeholder="bijv. 720"
                  onChange={(e) => {
                    setCanvasHeightDraft(e.target.value);
                    updateCanvasSize(canvasWidthDraft, e.target.value);
                  }}
                />
              </label>
            </div>
            <p className="mirror-field__label" style={{ marginTop: "0.5rem" }}>
              Leeg = geen apart canvas, de camera-bron vult het beeld zoals nu. Met een
              formaat kun je de bron en de overlay hieronder allebei los positioneren en
              schalen binnen dat formaat (bijv. 576×720 voor een portret-scherm).
            </p>
            {settings?.mirror_camera_source && isBrowserViewable(settings.mirror_camera_source) ? (
              <OverlayCanvas
                streamUrl={settings.mirror_camera_source}
                overlayUrl={config.overlay_hash ? `/api/media/${config.overlay_hash}` : null}
                scale={config.scale}
                position={config.position}
                onPositionChange={(position) => update({ position })}
                onScaleChange={(scale) => update({ scale })}
                canvasSize={config.canvas_size}
                sourceScale={config.source_scale}
                sourcePosition={config.source_position}
                onSourcePositionChange={(source_position) => update({ source_position })}
                onSourceScaleChange={(source_scale) => update({ source_scale })}
              />
            ) : (
              <p className="mirror-stream-missing" role="alert">
                {settings?.mirror_camera_source
                  ? "Deze camera-bron (rtsp:// of een lokale index) kan de browser niet direct tonen — gebruik de Live preview hieronder zodra de mirror-node draait."
                  : "Vul eerst een camera-bron-URL in (hierboven) om 'm hier te kunnen positioneren."}
              </p>
            )}
          </section>

          <section className="mirror-panel">
            <p className="mirror-panel__eyebrow">Mirror-node testen (zonder hardware)</p>
            <div className="mirror-process-row">
              <span
                className={`mirror-process-status ${running ? "mirror-process-status--running" : ""}`}
              >
                {running ? "Draait" : "Gestopt"}
              </span>
              <button
                className="mirror-apply"
                type="button"
                onClick={handleStartProcess}
                disabled={processBusy || running}
              >
                {processBusy ? "Bezig…" : "Start"}
              </button>
              <button
                className="mirror-test"
                type="button"
                onClick={handleStopProcess}
                disabled={processBusy || !running}
              >
                {processBusy ? "Bezig…" : "Stop"}
              </button>
            </div>
            <pre className="mirror-process-log">
              {logLines.length
                ? logLines.join("\n")
                : "Nog geen logregels — start de mirror-node om ze hier te zien."}
            </pre>
          </section>

          <section className="mirror-panel">
            <p className="mirror-panel__eyebrow">Live preview</p>
            {streamUrl ? (
              <OverlayCanvas
                streamUrl={streamUrl}
                overlayUrl={config.overlay_hash ? `/api/media/${config.overlay_hash}` : null}
                scale={config.scale}
                position={config.position}
                onPositionChange={(position) => update({ position })}
                onScaleChange={(scale) => update({ scale })}
              />
            ) : (
              <p className="mirror-stream-missing" role="alert">
                Live preview niet beschikbaar — de mirror-stream-URL is nog niet ingesteld op de
                Instellingen-pagina.
              </p>
            )}
          </section>

          <div className="mirror-actions">
            <button
              className="mirror-apply"
              type="button"
              onClick={handleApply}
              disabled={saving}
            >
              {saving ? "Bezig…" : "Toepassen"}
            </button>
            <button
              className="mirror-test"
              type="button"
              onClick={handleTest}
              disabled={testing}
            >
              {testing ? "Bezig…" : "Test"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
