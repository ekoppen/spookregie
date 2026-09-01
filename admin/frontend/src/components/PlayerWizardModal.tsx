import { useEffect, useState } from "react";
import { getPlayer, createPlayer, updatePlayer, deletePlayer, type PlayerDraft } from "../api/players";
import { listSources, getSource } from "../api/sources";
import { listPlayerBranches, createPlayerBranch, updatePlayerBranch, deletePlayerBranch } from "../api/branches";
import { getHaStates } from "../api/ha";
import MediaLibrary from "./MediaLibrary";
import OverlayCanvas from "./OverlayCanvas";
import PreviewPanel from "./PreviewPanel";
import type { Player, Source, PlayerBranch, HaState } from "../types";
import "./PlayerWizardModal.css";

const EFFECTS = ["xray", "thermal", "contour", "posterize"] as const;
const FIELD_LABELS: Record<string, string> = {
  intensity: "Intensiteit",
  threshold1: "Drempel 1",
  threshold2: "Drempel 2",
  levels: "Niveaus",
};

function paramFieldsFor(effect: Player["effect"]): string[] {
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

const EMPTY_DRAFT: PlayerDraft = {
  name: "Nieuwe player",
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
  is_root: false,
  canvas_x: 0,
  canvas_y: 0,
  color: null,
  source_id: null,
  audio_source_id: null,
  playback_mode: "once",
  repeat_while_ha_entity_id: null,
};

interface Props {
  playerId: number | null;
  initialStep?: Step;
  onClose: () => void;
  onSaved: () => void;
}

type Step = "input" | "source" | "animation" | "output" | "playback" | "branches";
const STEP_LABEL: Record<Step, string> = {
  input: "Input",
  source: "Bron",
  animation: "Animatie",
  // "Weergave" i.p.v. "Output" -- dit is de canvas-/overlay-plaatsingsstap,
  // niet te verwarren met het nieuwe Output-knooptype in de graaf.
  output: "Weergave",
  playback: "Afspelen",
  branches: "Aftakkingen",
};

export default function PlayerWizardModal({ playerId, initialStep, onClose, onSaved }: Props) {
  const [draft, setDraft] = useState<PlayerDraft>(EMPTY_DRAFT);
  const [step, setStep] = useState<Step>(initialStep ?? "input");
  const [cameraSource, setCameraSource] = useState("");
  const [sources, setSources] = useState<Source[]>([]);
  const [canvasWidthDraft, setCanvasWidthDraft] = useState("");
  const [canvasHeightDraft, setCanvasHeightDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [haStates, setHaStates] = useState<HaState[]>([]);
  const [haLoadError, setHaLoadError] = useState(false);
  const [showAllDomains, setShowAllDomains] = useState(false);
  const [branches, setBranches] = useState<PlayerBranch[]>([]);
  const [newBranchName, setNewBranchName] = useState("");

  useEffect(() => {
    if (playerId !== null) {
      getPlayer(playerId)
        .then((player) => {
          setDraft(player);
          setCanvasWidthDraft(player.canvas_size ? String(player.canvas_size[0]) : "");
          setCanvasHeightDraft(player.canvas_size ? String(player.canvas_size[1]) : "");
        })
        .catch(() => setError("Player kon niet worden geladen."));
    }
  }, [playerId]);

  useEffect(() => {
    listSources()
      .then(setSources)
      .catch(() => {
        /* Bron-dropdown blijft dan leeg -- opslaan blijft mogelijk zonder gekozen bron */
      });
  }, []);

  useEffect(() => {
    if (draft.source_id === null) {
      setCameraSource("");
      return;
    }
    getSource(draft.source_id)
      .then((source) => setCameraSource(source.kind === "camera_stream" ? source.value : ""))
      .catch(() => {
        /* voorbeeldbeeld blijft dan "niet beschikbaar" */
      });
  }, [draft.source_id]);

  useEffect(() => {
    if (draft.playback_mode !== "repeat_while") return;
    getHaStates()
      .then(setHaStates)
      .catch(() => setHaLoadError(true));
  }, [draft.playback_mode]);

  function refreshBranches() {
    if (playerId === null) return;
    listPlayerBranches(playerId)
      .then(setBranches)
      .catch(() => setError("Aftakkingen konden niet worden geladen."));
  }

  useEffect(() => {
    if (step === "branches") refreshBranches();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, playerId]);

  const [previewOpen, setPreviewOpen] = useState(false);

  function update(patch: Partial<PlayerDraft>) {
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
      if (playerId === null) {
        await createPlayer(draft);
      } else {
        await updatePlayer(playerId, draft);
      }
      onSaved();
      onClose();
    } catch {
      setError("Opslaan is mislukt. Probeer het opnieuw.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (playerId === null) return;
    if (!window.confirm(`Player "${draft.name}" verwijderen? Dit kan niet ongedaan worden gemaakt.`)) return;
    setSaving(true);
    try {
      await deletePlayer(playerId);
      onSaved();
      onClose();
    } catch {
      setError("Verwijderen is mislukt. Probeer het opnieuw.");
    } finally {
      setSaving(false);
    }
  }

  async function handleAddBranch() {
    if (playerId === null || !newBranchName.trim()) return;
    await createPlayerBranch(playerId, newBranchName.trim());
    setNewBranchName("");
    refreshBranches();
  }

  async function handleRenameBranch(branchId: number, name: string) {
    await updatePlayerBranch(branchId, name);
    refreshBranches();
  }

  async function handleDeleteBranch(branchId: number) {
    try {
      await deletePlayerBranch(branchId);
      refreshBranches();
    } catch {
      setError("Aftakking verwijderen is mislukt -- heeft die nog een trigger of output-verbinding?");
    }
  }

  const steps: Step[] =
    draft.source_mode === "camera" ? ["input", "source", "animation", "output", "branches"] : ["input", "playback", "branches"];
  const stepIndex = steps.indexOf(step);

  return (
    <div className="player-modal__backdrop" role="dialog" aria-modal="true">
      <div className="player-modal">
        <header className="player-modal__header">
          <input
            className="player-modal__name"
            type="text"
            value={draft.name}
            onChange={(e) => update({ name: e.target.value })}
            placeholder="Naam van deze player"
          />
          <button className="player-modal__close" type="button" onClick={onClose} aria-label="Sluiten">
            ×
          </button>
          {draft.source_mode === "camera" && (
            <button
              type="button"
              className="player-modal__preview-toggle"
              onClick={() => setPreviewOpen((open) => !open)}
            >
              {previewOpen ? "Preview verbergen" : "Preview"}
            </button>
          )}
        </header>

        <nav className="player-modal__steps">
          {steps.map((s, i) => (
            <span key={s} className="player-modal__step" data-active={s === step} data-done={i < stepIndex}>
              {i + 1}. {STEP_LABEL[s]}
            </span>
          ))}
        </nav>

        {error && (
          <p className="player-modal__error" role="alert">
            {error}
          </p>
        )}

        <div className="player-modal__body">
          {step === "input" && (
            <div className="player-modal__field-group">
              <label className="player-modal__radio">
                <input
                  type="radio"
                  name="source_mode"
                  checked={draft.source_mode === "camera"}
                  onChange={() => update({ source_mode: "camera" })}
                />
                Live camera-bron
              </label>
              <label className="player-modal__radio">
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

          {step === "source" && (
            <div className="player-modal__field-group">
              <label className="player-modal__field">
                <span>Source</span>
                <select
                  value={draft.source_id ?? ""}
                  onChange={(e) => update({ source_id: e.target.value ? parseInt(e.target.value, 10) : null })}
                >
                  <option value="">— gebruik de eerste/enige source —</option>
                  {sources.map((source) => (
                    <option key={source.id} value={source.id}>
                      {source.name} ({source.kind === "camera_stream" ? "camera" : "afbeelding"})
                    </option>
                  ))}
                </select>
              </label>
            </div>
          )}

          {step === "animation" && (
            <>
              <div className="player-modal__field-group">
                <label className="player-modal__field">
                  <span>Effect</span>
                  <select
                    value={draft.effect}
                    onChange={(e) => update({ effect: e.target.value as Player["effect"], params: {} })}
                  >
                    {EFFECTS.map((effect) => (
                      <option key={effect} value={effect}>
                        {effect}
                      </option>
                    ))}
                  </select>
                </label>
                {paramFieldsFor(draft.effect).map((field) => (
                  <label className="player-modal__field" key={field}>
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
              <p className="player-modal__label">Overlay</p>
              <MediaLibrary
                kind="image"
                selectionMode="single"
                selected={draft.overlay_hash ? [draft.overlay_hash] : []}
                onSelectionChange={(hashes) => update({ overlay_hash: hashes[0] ?? null })}
              />
            </>
          )}

          {step === "output" && (
            <>
              <div className="player-modal__field-group">
                <label className="player-modal__field">
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
                <label className="player-modal__field">
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
                <p className="player-modal__label">
                  Geen camera-source gekozen op de Bron-stap (of de gekozen source is een statische
                  afbeelding) — kan hier niet getoond worden.
                </p>
              )}
            </>
          )}

          {step === "playback" && (
            <div className="player-modal__field-group">
              <label className="player-modal__radio">
                <input
                  type="radio"
                  name="playback_mode"
                  checked={draft.playback_mode === "once"}
                  onChange={() => update({ playback_mode: "once" })}
                />
                1x afspelen
              </label>
              <label className="player-modal__radio">
                <input
                  type="radio"
                  name="playback_mode"
                  checked={draft.playback_mode === "repeat_once"}
                  onChange={() => update({ playback_mode: "repeat_once" })}
                />
                Eenmaal herhalen (2x totaal)
              </label>
              <label className="player-modal__radio">
                <input
                  type="radio"
                  name="playback_mode"
                  checked={draft.playback_mode === "repeat_while"}
                  onChange={() => update({ playback_mode: "repeat_while" })}
                />
                Herhalen zolang een sensor actief is
              </label>
              {draft.playback_mode === "repeat_while" && (
                <div className="player-modal__field-group">
                  {haLoadError && <p className="player-modal__error">HA-entiteiten konden niet geladen worden.</p>}
                  <label className="player-modal__field">
                    <span>Sensor</span>
                    <select
                      value={draft.repeat_while_ha_entity_id ?? ""}
                      onChange={(e) => update({ repeat_while_ha_entity_id: e.target.value || null })}
                    >
                      <option value="">— kies een entiteit —</option>
                      {haStates
                        .filter((s) => showAllDomains || s.entity_id.startsWith("binary_sensor."))
                        .map((s) => (
                          <option key={s.entity_id} value={s.entity_id}>
                            {s.entity_id} ({s.state})
                          </option>
                        ))}
                    </select>
                  </label>
                  <label className="player-modal__radio">
                    <input
                      type="checkbox"
                      checked={showAllDomains}
                      onChange={(e) => setShowAllDomains(e.target.checked)}
                    />
                    Toon alle entiteiten (niet alleen binary_sensor)
                  </label>
                </div>
              )}
            </div>
          )}

          {step === "branches" && (
            <div className="player-modal__field-group">
              {playerId === null ? (
                <p className="player-modal__label">Sla deze player eerst op om aftakkingen te beheren.</p>
              ) : (
                <>
                  {branches.map((branch) => (
                    <div className="player-modal__branch-row" key={branch.id}>
                      <input
                        type="text"
                        defaultValue={branch.name}
                        onBlur={(e) => {
                          if (e.target.value.trim() && e.target.value !== branch.name) {
                            handleRenameBranch(branch.id, e.target.value.trim());
                          }
                        }}
                      />
                      <button type="button" onClick={() => handleDeleteBranch(branch.id)}>
                        Verwijderen
                      </button>
                    </div>
                  ))}
                  <div className="player-modal__branch-row">
                    <input
                      type="text"
                      placeholder="Naam nieuwe aftakking"
                      value={newBranchName}
                      onChange={(e) => setNewBranchName(e.target.value)}
                    />
                    <button type="button" onClick={handleAddBranch} disabled={!newBranchName.trim()}>
                      + Aftakking
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
        </div>

        <footer className="player-modal__footer">
          {playerId !== null && (
            <button type="button" className="player-modal__delete" disabled={saving} onClick={handleDelete}>
              Verwijderen
            </button>
          )}
          <button
            type="button"
            className="player-modal__nav"
            disabled={stepIndex === 0}
            onClick={() => setStep(steps[stepIndex - 1])}
          >
            Vorige
          </button>
          {stepIndex < steps.length - 1 ? (
            <button type="button" className="player-modal__nav" onClick={() => setStep(steps[stepIndex + 1])}>
              Volgende
            </button>
          ) : (
            <button type="button" className="player-modal__save" disabled={saving} onClick={handleSave}>
              {saving ? "Bezig…" : "Opslaan"}
            </button>
          )}
        </footer>
      </div>
      {previewOpen && draft.source_mode === "camera" && (
        <PreviewPanel draft={draft} onClose={() => setPreviewOpen(false)} />
      )}
    </div>
  );
}
