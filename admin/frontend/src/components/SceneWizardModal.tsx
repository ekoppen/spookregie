import { useEffect, useState } from "react";
import { getScene, createScene, updateScene, previewScene, type SceneDraft } from "../api/scenes";
import { getSettings } from "../api/settings";
import MediaLibrary from "./MediaLibrary";
import OverlayCanvas from "./OverlayCanvas";
import type { Scene } from "../types";
import "./SceneWizardModal.css";

const EFFECTS = ["xray", "thermal", "contour", "posterize"] as const;
const FIELD_LABELS: Record<string, string> = {
  intensity: "Intensiteit",
  threshold1: "Drempel 1",
  threshold2: "Drempel 2",
  levels: "Niveaus",
};

function paramFieldsFor(effect: Scene["effect"]): string[] {
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

const EMPTY_DRAFT: SceneDraft = {
  name: "Nieuwe scene",
  enabled: true,
  source_mode: "camera",
  effect: "xray",
  params: {},
  overlay_hash: null,
  scale: 1.0,
  position: [0.5, 0.5],
  canvas_size: null,
  source_scale: 1.0,
  source_position: [0.5, 0.5],
  trigger_type: "always",
  trigger_from: null,
  trigger_until: null,
};

interface Props {
  sceneId: number | null;
  onClose: () => void;
  onSaved: () => void;
}

type Step = "input" | "animation" | "output" | "trigger";
const STEP_LABEL: Record<Step, string> = {
  input: "Input",
  animation: "Animatie",
  output: "Output",
  trigger: "Trigger",
};

export default function SceneWizardModal({ sceneId, onClose, onSaved }: Props) {
  const [draft, setDraft] = useState<SceneDraft>(EMPTY_DRAFT);
  const [step, setStep] = useState<Step>("input");
  const [cameraSource, setCameraSource] = useState("");
  const [canvasWidthDraft, setCanvasWidthDraft] = useState("");
  const [canvasHeightDraft, setCanvasHeightDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getSettings()
      .then((s) => setCameraSource(s.mirror_camera_source))
      .catch(() => {
        /* voorbeeldbeeld blijft dan "niet beschikbaar" */
      });
    if (sceneId !== null) {
      getScene(sceneId)
        .then((scene) => {
          setDraft(scene);
          setCanvasWidthDraft(scene.canvas_size ? String(scene.canvas_size[0]) : "");
          setCanvasHeightDraft(scene.canvas_size ? String(scene.canvas_size[1]) : "");
        })
        .catch(() => setError("Scene kon niet worden geladen."));
    }
  }, [sceneId]);

  // Live preview tijdens het bewerken -- alleen mogelijk voor een al
  // opgeslagen scene (de preview-route heeft een id nodig). Simpele
  // fire-and-forget bij elke wijziging, geen aparte throttle-timer:
  // elke keypress/sleep-update is al een expliciete, door de gebruiker
  // bedoelde wijziging.
  useEffect(() => {
    if (sceneId === null) return;
    previewScene(sceneId, draft).catch((err) => console.error("Preview mislukt:", err));
  }, [sceneId, draft]);

  function update(patch: Partial<SceneDraft>) {
    setDraft((prev) => ({ ...prev, ...patch }));
  }

  function updateCanvasSize(widthStr: string, heightStr: string) {
    const w = parseInt(widthStr, 10);
    const h = parseInt(heightStr, 10);
    update({ canvas_size: w > 0 && h > 0 ? [w, h] : null });
  }

  async function handleSave() {
    setSaving(true);
    try {
      if (sceneId === null) {
        await createScene(draft);
      } else {
        await updateScene(sceneId, draft);
      }
      onSaved();
      onClose();
    } catch {
      setError("Opslaan is mislukt. Probeer het opnieuw.");
    } finally {
      setSaving(false);
    }
  }

  const steps: Step[] =
    draft.source_mode === "camera" ? ["input", "animation", "output", "trigger"] : ["input", "trigger"];
  const stepIndex = steps.indexOf(step);

  return (
    <div className="scene-modal__backdrop" role="dialog" aria-modal="true">
      <div className="scene-modal">
        <header className="scene-modal__header">
          <input
            className="scene-modal__name"
            type="text"
            value={draft.name}
            onChange={(e) => update({ name: e.target.value })}
            placeholder="Naam van deze scene"
          />
          <button className="scene-modal__close" type="button" onClick={onClose} aria-label="Sluiten">
            ×
          </button>
        </header>

        <nav className="scene-modal__steps">
          {steps.map((s, i) => (
            <span key={s} className="scene-modal__step" data-active={s === step} data-done={i < stepIndex}>
              {i + 1}. {STEP_LABEL[s]}
            </span>
          ))}
        </nav>

        {error && (
          <p className="scene-modal__error" role="alert">
            {error}
          </p>
        )}

        <div className="scene-modal__body">
          {step === "input" && (
            <div className="scene-modal__field-group">
              <label className="scene-modal__radio">
                <input
                  type="radio"
                  name="source_mode"
                  checked={draft.source_mode === "camera"}
                  onChange={() => update({ source_mode: "camera" })}
                />
                Live camera-bron
              </label>
              <label className="scene-modal__radio">
                <input
                  type="radio"
                  name="source_mode"
                  checked={draft.source_mode === "scare_video"}
                  onChange={() => update({ source_mode: "scare_video" })}
                />
                Scare-video (willekeurig uit de ingeschakelde bibliotheek)
              </label>
            </div>
          )}

          {step === "animation" && (
            <>
              <div className="scene-modal__field-group">
                <label className="scene-modal__field">
                  <span>Effect</span>
                  <select
                    value={draft.effect}
                    onChange={(e) => update({ effect: e.target.value as Scene["effect"], params: {} })}
                  >
                    {EFFECTS.map((effect) => (
                      <option key={effect} value={effect}>
                        {effect}
                      </option>
                    ))}
                  </select>
                </label>
                {paramFieldsFor(draft.effect).map((field) => (
                  <label className="scene-modal__field" key={field}>
                    <span>{FIELD_LABELS[field] ?? field}</span>
                    <input
                      type="number"
                      step="0.1"
                      value={draft.params[field] ?? ""}
                      onChange={(e) => {
                        const parsed = parseFloat(e.target.value);
                        if (Number.isNaN(parsed)) return;
                        update({ params: { ...draft.params, [field]: parsed } });
                      }}
                    />
                  </label>
                ))}
              </div>
              <p className="scene-modal__label">Overlay</p>
              <MediaLibrary
                category="mirror_overlay"
                selectionMode="single"
                selected={draft.overlay_hash ? [draft.overlay_hash] : []}
                onSelectionChange={(hashes) => update({ overlay_hash: hashes[0] ?? null })}
              />
            </>
          )}

          {step === "output" && (
            <>
              <div className="scene-modal__field-group">
                <label className="scene-modal__field">
                  <span>Breedte (optioneel)</span>
                  <input
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
                <label className="scene-modal__field">
                  <span>Hoogte (optioneel)</span>
                  <input
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
              {cameraSource ? (
                <OverlayCanvas
                  streamUrl={cameraSource}
                  overlayUrl={draft.overlay_hash ? `/api/media/${draft.overlay_hash}` : null}
                  scale={draft.scale}
                  position={draft.position}
                  onPositionChange={(position) => update({ position })}
                  onScaleChange={(scale) => update({ scale })}
                  canvasSize={draft.canvas_size}
                  sourceScale={draft.source_scale}
                  sourcePosition={draft.source_position}
                  onSourcePositionChange={(source_position) => update({ source_position })}
                  onSourceScaleChange={(source_scale) => update({ source_scale })}
                />
              ) : (
                <p className="scene-modal__label">
                  Geen camera-bron ingesteld op de Instellingen-pagina — kan hier niet getoond worden.
                </p>
              )}
            </>
          )}

          {step === "trigger" && (
            <div className="scene-modal__field-group">
              <label className="scene-modal__radio">
                <input
                  type="radio"
                  name="trigger_type"
                  checked={draft.trigger_type === "always"}
                  onChange={() => update({ trigger_type: "always", trigger_from: null, trigger_until: null })}
                />
                Altijd (basis-scene)
              </label>
              <label className="scene-modal__radio">
                <input
                  type="radio"
                  name="trigger_type"
                  checked={draft.trigger_type === "motion"}
                  onChange={() => update({ trigger_type: "motion", trigger_from: null, trigger_until: null })}
                />
                Beweging
              </label>
              <label className="scene-modal__radio">
                <input
                  type="radio"
                  name="trigger_type"
                  checked={draft.trigger_type === "schedule"}
                  onChange={() => update({ trigger_type: "schedule" })}
                />
                Tijdschema
              </label>
              {draft.trigger_type === "schedule" && (
                <div className="scene-modal__field-group">
                  <label className="scene-modal__field">
                    <span>Van</span>
                    <input
                      type="time"
                      value={draft.trigger_from ?? ""}
                      onChange={(e) => update({ trigger_from: e.target.value })}
                    />
                  </label>
                  <label className="scene-modal__field">
                    <span>Tot</span>
                    <input
                      type="time"
                      value={draft.trigger_until ?? ""}
                      onChange={(e) => update({ trigger_until: e.target.value })}
                    />
                  </label>
                </div>
              )}
            </div>
          )}
        </div>

        <footer className="scene-modal__footer">
          <button
            type="button"
            className="scene-modal__nav"
            disabled={stepIndex === 0}
            onClick={() => setStep(steps[stepIndex - 1])}
          >
            Vorige
          </button>
          {stepIndex < steps.length - 1 ? (
            <button type="button" className="scene-modal__nav" onClick={() => setStep(steps[stepIndex + 1])}>
              Volgende
            </button>
          ) : (
            <button type="button" className="scene-modal__save" disabled={saving} onClick={handleSave}>
              {saving ? "Bezig…" : "Opslaan"}
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}
