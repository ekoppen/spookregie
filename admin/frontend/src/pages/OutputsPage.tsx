import { useEffect, useState } from "react";
import { listOutputs, createOutput, updateOutput, deleteOutput } from "../api/outputs";
import { ApiError } from "../api/client";
import type { Output } from "../types";
import "./OutputsPage.css";

interface Draft {
  name: string;
}

export default function OutputsPage() {
  const [outputs, setOutputs] = useState<Output[]>([]);
  const [drafts, setDrafts] = useState<Record<number, Draft>>({});
  const [newName, setNewName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function refresh() {
    listOutputs()
      .then((result) => {
        setOutputs(result);
        setDrafts(Object.fromEntries(result.map((o) => [o.id, { name: o.name }])));
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
      await createOutput({ name: newName.trim(), camera_source: "", canvas_x: 0, canvas_y: 0 });
      setNewName("");
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
    const existing = outputs.find((o) => o.id === id);
    if (!draft || !existing) return;
    setSaving(true);
    try {
      await updateOutput(id, { name: draft.name, camera_source: existing.camera_source, canvas_x: existing.canvas_x, canvas_y: existing.canvas_y });
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
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Verwijderen is mislukt.");
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
          const draft = drafts[output.id] ?? { name: output.name };
          return (
            <div className="outputs-row" key={output.id}>
              <input
                className="outputs-field__input"
                type="text"
                value={draft.name}
                onChange={(e) => updateDraft(output.id, { name: e.target.value })}
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
          <button type="button" onClick={handleCreate} disabled={saving || !newName.trim()}>
            + Output toevoegen
          </button>
        </div>
      </section>

      <p className="outputs-field__label">
        Nodes halen dit pas op bij hun eerstvolgende herstart. Een output met
        nog players eraan gekoppeld kan niet verwijderd worden.
      </p>
    </div>
  );
}
