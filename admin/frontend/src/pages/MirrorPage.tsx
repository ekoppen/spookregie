import { useEffect, useState } from "react";
import { getMirrorConfig, putMirrorConfig, previewMirrorConfig, testMirror } from "../api/mirror";
import MediaLibrary from "../components/MediaLibrary";
import OverlayCanvas from "../components/OverlayCanvas";
import type { MirrorConfig } from "../types";
import "./MirrorPage.css";

const EFFECTS = ["xray", "thermal", "contour", "posterize"] as const;
const STREAM_URL = import.meta.env.VITE_MIRROR_STREAM_URL ?? "";

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

  useEffect(() => {
    getMirrorConfig()
      .then((result) => {
        setConfig(result);
        setError(null);
      })
      .catch(() => setError("Spiegelconfiguratie kon niet worden geladen."));
  }, []);

  // Live preview: debounced, fails silently (console only) per keystroke to avoid alert-noise.
  useEffect(() => {
    if (!config) return;
    const timer = setTimeout(() => {
      previewMirrorConfig(config).catch((err) => console.error("Preview mislukt:", err));
    }, 150);
    return () => clearTimeout(timer);
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
                    onChange={(e) =>
                      update({ params: { ...config.params, [field]: parseFloat(e.target.value) } })
                    }
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
            <OverlayCanvas
              streamUrl={STREAM_URL}
              overlayUrl={config.overlay_hash ? `/api/media/${config.overlay_hash}` : null}
              scale={config.scale}
              position={config.position}
              onPositionChange={(position) => update({ position })}
              onScaleChange={(scale) => update({ scale })}
            />
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
