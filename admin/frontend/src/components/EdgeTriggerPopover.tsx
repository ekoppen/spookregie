import { useState } from "react";
import { updateSceneEdge, deleteSceneEdge } from "../api/sceneEdges";
import type { SceneEdge } from "../types";
import "./EdgeTriggerPopover.css";

interface Props {
  edge: SceneEdge;
  onClose: () => void;
  onSaved: () => void;
}

export default function EdgeTriggerPopover({ edge, onClose, onSaved }: Props) {
  const [triggerType, setTriggerType] = useState<NonNullable<SceneEdge["trigger_type"]>>(
    edge.trigger_type ?? "always",
  );
  const [from, setFrom] = useState(edge.trigger_from ?? "");
  const [until, setUntil] = useState(edge.trigger_until ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSave() {
    setSaving(true);
    try {
      await updateSceneEdge(edge.id, {
        from_scene_id: edge.from_scene_id,
        to_scene_id: edge.to_scene_id,
        trigger_type: triggerType,
        trigger_from: triggerType === "schedule" ? from : null,
        trigger_until: triggerType === "schedule" ? until : null,
        priority: edge.priority,
      });
      onSaved();
      onClose();
    } catch {
      setError("Opslaan is mislukt.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    setSaving(true);
    try {
      await deleteSceneEdge(edge.id);
      onSaved();
      onClose();
    } catch {
      setError("Verwijderen is mislukt.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="edge-popover__backdrop" role="dialog" aria-modal="true">
      <div className="edge-popover">
        <p className="edge-popover__title">Trigger voor deze verbinding</p>
        {error && (
          <p className="edge-popover__error" role="alert">
            {error}
          </p>
        )}
        <div className="edge-popover__options">
          <label className="edge-popover__radio">
            <input
              type="radio"
              name="edge-trigger"
              checked={triggerType === "always"}
              onChange={() => setTriggerType("always")}
            />
            Altijd
          </label>
          <label className="edge-popover__radio">
            <input
              type="radio"
              name="edge-trigger"
              checked={triggerType === "motion"}
              onChange={() => setTriggerType("motion")}
            />
            Beweging
          </label>
          <label className="edge-popover__radio">
            <input
              type="radio"
              name="edge-trigger"
              checked={triggerType === "schedule"}
              onChange={() => setTriggerType("schedule")}
            />
            Tijdschema
          </label>
          {triggerType === "schedule" && (
            <div className="edge-popover__schedule">
              <label>
                <span>Van</span>
                <input type="time" value={from} onChange={(e) => setFrom(e.target.value)} />
              </label>
              <label>
                <span>Tot</span>
                <input type="time" value={until} onChange={(e) => setUntil(e.target.value)} />
              </label>
            </div>
          )}
        </div>
        <div className="edge-popover__actions">
          <button type="button" onClick={handleDelete} disabled={saving}>
            Verwijderen
          </button>
          <button type="button" onClick={onClose} disabled={saving}>
            Annuleren
          </button>
          <button type="button" onClick={handleSave} disabled={saving}>
            {saving ? "Bezig…" : "Opslaan"}
          </button>
        </div>
      </div>
    </div>
  );
}
