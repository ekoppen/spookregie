import { useEffect, useState } from "react";
import { listDevices, updateDevice, deleteDevice } from "../api/devices";
import { listOutputs } from "../api/outputs";
import { getNodes } from "../api/nodes";
import { ApiError } from "../api/client";
import type { Device, Output, NodeStatusMap } from "../types";
import "./DevicesPage.css";

interface Draft {
  name: string;
  output_id: number | null;
}

export default function DevicesPage() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [outputs, setOutputs] = useState<Output[]>([]);
  const [nodes, setNodes] = useState<NodeStatusMap>({});
  const [drafts, setDrafts] = useState<Record<number, Draft>>({});
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function refresh() {
    listDevices()
      .then((result) => {
        setDevices(result);
        setDrafts(Object.fromEntries(result.map((d) => [d.id, { name: d.name, output_id: d.output_id }])));
        setError(null);
      })
      .catch(() => setError("Apparaten konden niet worden geladen."));
  }

  useEffect(() => {
    refresh();
    listOutputs().then(setOutputs).catch(() => setError("Outputs konden niet worden geladen."));
    getNodes().then(setNodes).catch(() => {
      /* online/offline-badge blijft dan gewoon leeg */
    });
  }, []);

  function showNotice(message: string) {
    setNotice(message);
    window.setTimeout(() => setNotice(null), 3000);
  }

  function updateDraft(id: number, patch: Partial<Draft>) {
    setDrafts((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));
  }

  async function handleSave(id: number) {
    const draft = drafts[id];
    if (!draft) return;
    setSaving(true);
    try {
      await updateDevice(id, { name: draft.name, output_id: draft.output_id });
      refresh();
      showNotice("Apparaat opgeslagen.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Opslaan is mislukt.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: number) {
    if (!window.confirm("Dit apparaat uit de lijst verwijderen? Het meldt zich vanzelf opnieuw als het weer een checkin stuurt.")) return;
    setSaving(true);
    try {
      await deleteDevice(id);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Verwijderen is mislukt.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="devices-page">
      <header className="devices-header">
        <p className="devices-eyebrow">
          <span className="devices-eyebrow__led" aria-hidden="true" />
          Apparaten
        </p>
        <h1 className="devices-heading">Apparaten</h1>
      </header>

      {error && (
        <p className="devices-error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="devices-notice" role="status">
          {notice}
        </p>
      )}

      <section className="devices-panel">
        {devices.length === 0 && <p className="devices-empty">Nog geen apparaten gemeld.</p>}
        {devices.map((device) => {
          const draft = drafts[device.id] ?? { name: device.name, output_id: device.output_id };
          const online = nodes[device.device_uuid]?.status === "online";
          return (
            <div className="devices-row" key={device.id}>
              <span className={`devices-status-badge devices-status-badge--${online ? "online" : "offline"}`}>
                {online ? "Online" : "Offline"}
              </span>
              <input
                className="devices-field__input"
                type="text"
                value={draft.name}
                onChange={(e) => updateDraft(device.id, { name: e.target.value })}
              />
              <span className="devices-field__meta">{device.platform}</span>
              <span className="devices-field__meta">{device.git_sha ? device.git_sha.slice(0, 7) : "—"}</span>
              <span className="devices-field__meta">{device.last_seen_at ?? "—"}</span>
              <select
                className="devices-field__select"
                value={draft.output_id ?? ""}
                onChange={(e) => updateDraft(device.id, { output_id: e.target.value ? Number(e.target.value) : null })}
              >
                <option value="">Geen output</option>
                {outputs.map((output) => (
                  <option key={output.id} value={output.id}>
                    {output.name}
                  </option>
                ))}
              </select>
              <button type="button" onClick={() => handleSave(device.id)} disabled={saving}>
                Opslaan
              </button>
              <button type="button" onClick={() => handleDelete(device.id)} disabled={saving}>
                Verwijderen
              </button>
            </div>
          );
        })}
      </section>

      <p className="devices-field__label">
        Apparaten melden zichzelf zodra hun agent draait en verbinding heeft
        -- zie deploy/install-agent.sh voor de eenmalige installatie. Koppel
        hier welke fysieke output een apparaat bedient.
      </p>
    </div>
  );
}
