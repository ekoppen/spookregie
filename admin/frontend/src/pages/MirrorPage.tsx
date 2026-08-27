import { useEffect, useRef, useState } from "react";
import { getMirrorConfig, putMirrorConfig, previewMirrorConfig, testMirror } from "../api/mirror";
import { getSettings } from "../api/settings";
import MediaLibrary from "../components/MediaLibrary";
import OverlayCanvas from "../components/OverlayCanvas";
import type { MirrorConfig } from "../types";
import "./MirrorPage.css";

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

  useEffect(() => {
    getMirrorConfig()
      .then((result) => {
        setConfig(result);
        setError(null);
      })
      .catch(() => setError("Spiegelconfiguratie kon niet worden geladen."));
    getSettings()
      .then((result) => setStreamUrl(result.mirror_stream_url))
      .catch(() => {
        /* live preview blijft dan gewoon "niet beschikbaar" tonen */
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

  function update(patch: Partial<MirrorConfig>) {
    setConfig((prev) => (prev ? { ...prev, ...patch } : prev));
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
