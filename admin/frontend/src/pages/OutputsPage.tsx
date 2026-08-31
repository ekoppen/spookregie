import { useEffect, useState } from "react";
import { listOutputs, createOutput, updateOutput, deleteOutput } from "../api/outputs";
import type { Output } from "../types";
import "./OutputsPage.css";

interface Draft {
  name: string;
  camera_source: string;
}

export default function OutputsPage() {
  const [outputs, setOutputs] = useState<Output[]>([]);
  const [drafts, setDrafts] = useState<Record<number, Draft>>({});
  const [newName, setNewName] = useState("");
  const [newCameraSource, setNewCameraSource] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function refresh() {
    listOutputs()
      .then((result) => {
        setOutputs(result);
        setDrafts(Object.fromEntries(result.map((o) => [o.id, { name: o.name, camera_source: o.camera_source }])));
        setError(null);
      })
      .catch(() => setError("Outputs konden niet worden geladen."));
  }

  useEffect(() => {
    refresh();
  }, []);

  function showNotice(message: string) {
    setNotice(message);
    window.setTimeout(() => setNotice(null), 3000);
  }

  function updateDraft(id: number, patch: Partial<Draft>) {
    setDrafts((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));
  }

  async function handleCreate() {
    if (!newName.trim()) return;
    setSaving(true);
    try {
      await createOutput({ name: newName.trim(), camera_source: newCameraSource.trim() });
      setNewName("");
      setNewCameraSource("");
      refresh();
      showNotice("Output aangemaakt.");
    } catch {
      setError("Aanmaken is mislukt.");
    } finally {
      setSaving(false);
    }
  }

  async function handleSave(id: number) {
    const draft = drafts[id];
    if (!draft) return;
    setSaving(true);
    try {
      await updateOutput(id, draft);
      refresh();
      showNotice("Output opgeslagen.");
    } catch {
      setError("Opslaan is mislukt.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: number) {
    if (!window.confirm("Deze output verwijderen?")) return;
    setSaving(true);
    try {
      await deleteOutput(id);
      refresh();
    } catch {
      setError("Verwijderen is mislukt — heeft deze output nog scenes?");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="outputs-page">
      <header className="outputs-header">
        <p className="outputs-eyebrow">
          <span className="outputs-eyebrow__led" aria-hidden="true" />
          Fysieke uitgangen
        </p>
        <h1 className="outputs-heading">Outputs</h1>
      </header>

      {error && (
        <p className="outputs-error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="outputs-notice" role="status">
          {notice}
        </p>
      )}

      <section className="outputs-panel">
        {outputs.map((output) => {
          const draft = drafts[output.id] ?? { name: output.name, camera_source: output.camera_source };
          return (
            <div className="outputs-row" key={output.id}>
              <input
                className="outputs-field__input"
                type="text"
                value={draft.name}
                onChange={(e) => updateDraft(output.id, { name: e.target.value })}
              />
              <input
                className="outputs-field__input outputs-field__input--wide"
                type="text"
                value={draft.camera_source}
                placeholder="bijv. rtsp://gebruiker:wachtwoord@192.168.1.50:554/stream1"
                onChange={(e) => updateDraft(output.id, { camera_source: e.target.value })}
              />
              <button type="button" onClick={() => handleSave(output.id)} disabled={saving}>
                Opslaan
              </button>
              <button type="button" onClick={() => handleDelete(output.id)} disabled={saving}>
                Verwijderen
              </button>
            </div>
          );
        })}

        <div className="outputs-row outputs-row--new">
          <input
            className="outputs-field__input"
            type="text"
            placeholder="Naam (bijv. Beamer tuin)"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <input
            className="outputs-field__input outputs-field__input--wide"
            type="text"
            placeholder="Camera-bron (optioneel)"
            value={newCameraSource}
            onChange={(e) => setNewCameraSource(e.target.value)}
          />
          <button type="button" onClick={handleCreate} disabled={saving || !newName.trim()}>
            + Output toevoegen
          </button>
        </div>
      </section>

      <p className="outputs-field__label">
        Leeg = de lokale camera op de node zelf. Een RTSP/HTTP-URL gebruikt die
        camera in plaats daarvan — elk merk met een standaard stream werkt.
        Nodes halen dit pas op bij hun eerstvolgende herstart. Een output met
        nog scenes eraan gekoppeld kan niet verwijderd worden.
      </p>
    </div>
  );
}
