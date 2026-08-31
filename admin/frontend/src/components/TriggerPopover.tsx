import { useEffect, useState } from "react";
import { updateTrigger, deleteTrigger } from "../api/triggers";
import { getHaStates } from "../api/ha";
import type { Trigger, HaState } from "../types";
import "./TriggerPopover.css";

interface Props {
  trigger: Trigger;
  onClose: () => void;
  onSaved: () => void;
}

export default function TriggerPopover({ trigger, onClose, onSaved }: Props) {
  const [kind, setKind] = useState<NonNullable<Trigger["kind"]>>(trigger.kind ?? "always");
  const [from, setFrom] = useState(trigger.schedule_from ?? "");
  const [until, setUntil] = useState(trigger.schedule_until ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [haEntityId, setHaEntityId] = useState(trigger.ha_entity_id ?? "");
  const [haStates, setHaStates] = useState<HaState[]>([]);
  const [haLoadError, setHaLoadError] = useState(false);
  const [showAllDomains, setShowAllDomains] = useState(false);

  useEffect(() => {
    if (kind !== "ha_sensor") return;
    getHaStates()
      .then(setHaStates)
      .catch(() => setHaLoadError(true));
  }, [kind]);

  async function handleSave() {
    if (kind === "ha_sensor" && !haEntityId) {
      setError("Kies een HA-entiteit.");
      return;
    }
    setSaving(true);
    try {
      await updateTrigger(trigger.id, {
        from_branch_id: trigger.from_branch_id,
        to_player_id: trigger.to_player_id,
        kind,
        schedule_from: kind === "schedule" ? from : null,
        schedule_until: kind === "schedule" ? until : null,
        ha_entity_id: kind === "ha_sensor" ? haEntityId : null,
        priority: trigger.priority,
        canvas_x: trigger.canvas_x,
        canvas_y: trigger.canvas_y,
        name: trigger.name,
        color: trigger.color,
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
      await deleteTrigger(trigger.id);
      onSaved();
      onClose();
    } catch {
      setError("Verwijderen is mislukt.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="trigger-popover__backdrop" role="dialog" aria-modal="true">
      <div className="trigger-popover">
        <p className="trigger-popover__title">Trigger instellen</p>
        {error && (
          <p className="trigger-popover__error" role="alert">
            {error}
          </p>
        )}
        <div className="trigger-popover__options">
          <label className="trigger-popover__radio">
            <input
              type="radio"
              name="trigger-kind"
              checked={kind === "always"}
              onChange={() => setKind("always")}
            />
            Altijd
          </label>
          <label className="trigger-popover__radio">
            <input
              type="radio"
              name="trigger-kind"
              checked={kind === "motion"}
              onChange={() => setKind("motion")}
            />
            Beweging
          </label>
          <label className="trigger-popover__radio">
            <input
              type="radio"
              name="trigger-kind"
              checked={kind === "schedule"}
              onChange={() => setKind("schedule")}
            />
            Tijdschema
          </label>
          <label className="trigger-popover__radio">
            <input
              type="radio"
              name="trigger-kind"
              checked={kind === "ha_sensor"}
              onChange={() => setKind("ha_sensor")}
            />
            Home Assistant-sensor
          </label>
          {kind === "ha_sensor" && (
            <div className="trigger-popover__ha">
              {haLoadError && <p className="trigger-popover__error">HA-entiteiten konden niet geladen worden.</p>}
              <label>
                <span>Entiteit</span>
                <select value={haEntityId} onChange={(e) => setHaEntityId(e.target.value)}>
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
              <label className="trigger-popover__checkbox">
                <input
                  type="checkbox"
                  checked={showAllDomains}
                  onChange={(e) => setShowAllDomains(e.target.checked)}
                />
                Toon alle entiteiten (niet alleen binary_sensor)
              </label>
            </div>
          )}
          {kind === "schedule" && (
            <div className="trigger-popover__schedule">
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
        <div className="trigger-popover__actions">
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
