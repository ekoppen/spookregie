import { useEffect, useState } from "react";
import { listSources, createSource, updateSource, deleteSource } from "../api/sources";
import { ApiError } from "../api/client";
import MediaLibrary from "../components/MediaLibrary";
import type { Source } from "../types";
import "./SourcesPage.css";

interface Draft {
  name: string;
  kind: Source["kind"];
  value: string;
}

// video_loop kiest uit dezelfde media-kind als static_image (allebei
// beeldmateriaal); alleen static_image gebruikt "image", video_loop "video".
function mediaKindFor(kind: Draft["kind"]): "image" | "audio" | "video" | null {
  if (kind === "static_image") return "image";
  if (kind === "video_loop") return "video";
  if (kind === "audio") return "audio";
  return null; // camera_stream: geen media-kind, vrij-tekst-URL-veld
}

export default function SourcesPage() {
  const [sources, setSources] = useState<Source[]>([]);
  const [drafts, setDrafts] = useState<Record<number, Draft>>({});
  const [newName, setNewName] = useState("");
  const [newKind, setNewKind] = useState<Draft["kind"]>("camera_stream");
  const [newValue, setNewValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // Eén picker tegelijk open: id van de bestaande source, of "new" voor de
  // aanmaak-rij, of null als er niks open staat.
  const [pickerOpenFor, setPickerOpenFor] = useState<number | "new" | null>(null);

  function refresh() {
    listSources()
      .then((result) => {
        setSources(result);
        setDrafts(Object.fromEntries(result.map((s) => [s.id, { name: s.name, kind: s.kind, value: s.value }])));
        setError(null);
      })
      .catch(() => setError("Sources konden niet worden geladen."));
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
      await createSource({
        name: newName.trim(), kind: newKind, value: newValue.trim(), canvas_x: 0, canvas_y: 0,
      });
      setNewName("");
      setNewValue("");
      setPickerOpenFor(null);
      refresh();
      showNotice("Source aangemaakt.");
    } catch {
      setError("Aanmaken is mislukt.");
    } finally {
      setSaving(false);
    }
  }

  async function handleSave(id: number) {
    const draft = drafts[id];
    const existing = sources.find((s) => s.id === id);
    if (!draft || !existing) return;
    setSaving(true);
    try {
      await updateSource(id, { ...draft, canvas_x: existing.canvas_x, canvas_y: existing.canvas_y });
      refresh();
      showNotice("Source opgeslagen.");
    } catch {
      setError("Opslaan is mislukt.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: number) {
    if (!window.confirm("Deze source verwijderen?")) return;
    setSaving(true);
    try {
      await deleteSource(id);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Verwijderen is mislukt.");
    } finally {
      setSaving(false);
    }
  }

  function valuePreview(draft: Draft): string {
    if (!draft.value) return "Kies media…";
    return draft.value.slice(0, 12) + "…";
  }

  return (
    <div className="sources-page">
      <header className="sources-header">
        <p className="sources-eyebrow">
          <span className="sources-eyebrow__led" aria-hidden="true" />
          Beeldbronnen
        </p>
        <h1 className="sources-heading">Sources</h1>
      </header>

      {error && (
        <p className="sources-error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="sources-notice" role="status">
          {notice}
        </p>
      )}

      <section className="sources-panel">
        {sources.map((source) => {
          const draft = drafts[source.id] ?? { name: source.name, kind: source.kind, value: source.value };
          const mediaKind = mediaKindFor(draft.kind);
          return (
            <div key={source.id}>
              <div className="sources-row">
                <input
                  className="sources-field__input"
                  type="text"
                  value={draft.name}
                  onChange={(e) => updateDraft(source.id, { name: e.target.value })}
                />
                <select
                  className="sources-field__input"
                  value={draft.kind}
                  onChange={(e) => updateDraft(source.id, { kind: e.target.value as Draft["kind"], value: "" })}
                >
                  <option value="camera_stream">Camera-stream</option>
                  <option value="static_image">Statische afbeelding</option>
                  <option value="video_loop">Video-loop</option>
                  <option value="audio">Audio</option>
                </select>
                {mediaKind === null ? (
                  <input
                    className="sources-field__input sources-field__input--wide"
                    type="text"
                    value={draft.value}
                    placeholder="rtsp://gebruiker:wachtwoord@192.168.1.50:554/stream1, of lokaal: 0"
                    onChange={(e) => updateDraft(source.id, { value: e.target.value })}
                  />
                ) : (
                  <button
                    type="button"
                    className="sources-field__input sources-field__input--wide sources-media-button"
                    onClick={() => setPickerOpenFor(pickerOpenFor === source.id ? null : source.id)}
                  >
                    {valuePreview(draft)}
                  </button>
                )}
                <button type="button" onClick={() => handleSave(source.id)} disabled={saving}>
                  Opslaan
                </button>
                <button type="button" onClick={() => handleDelete(source.id)} disabled={saving}>
                  Verwijderen
                </button>
              </div>
              {pickerOpenFor === source.id && mediaKind !== null && (
                <div className="sources-media-picker">
                  <MediaLibrary
                    kind={mediaKind}
                    selectionMode="single"
                    selected={draft.value ? [draft.value] : []}
                    onSelectionChange={(hashes) => {
                      updateDraft(source.id, { value: hashes[0] ?? "" });
                      setPickerOpenFor(null);
                    }}
                  />
                </div>
              )}
            </div>
          );
        })}

        <div>
          <div className="sources-row sources-row--new">
            <input
              className="sources-field__input"
              type="text"
              placeholder="Naam (bijv. Tuincamera)"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
            />
            <select
              className="sources-field__input"
              value={newKind}
              onChange={(e) => {
                setNewKind(e.target.value as Draft["kind"]);
                setNewValue("");
              }}
            >
              <option value="camera_stream">Camera-stream</option>
              <option value="static_image">Statische afbeelding</option>
              <option value="video_loop">Video-loop</option>
              <option value="audio">Audio</option>
            </select>
            {mediaKindFor(newKind) === null ? (
              <input
                className="sources-field__input sources-field__input--wide"
                type="text"
                placeholder="Camera-URL, of lokaal apparaatnummer zoals 0"
                value={newValue}
                onChange={(e) => setNewValue(e.target.value)}
              />
            ) : (
              <button
                type="button"
                className="sources-field__input sources-field__input--wide sources-media-button"
                onClick={() => setPickerOpenFor(pickerOpenFor === "new" ? null : "new")}
              >
                {newValue ? newValue.slice(0, 12) + "…" : "Kies media…"}
              </button>
            )}
            <button type="button" onClick={handleCreate} disabled={saving || !newName.trim()}>
              + Source toevoegen
            </button>
          </div>
          {pickerOpenFor === "new" && mediaKindFor(newKind) !== null && (
            <div className="sources-media-picker">
              <MediaLibrary
                kind={mediaKindFor(newKind)!}
                selectionMode="single"
                selected={newValue ? [newValue] : []}
                onSelectionChange={(hashes) => {
                  setNewValue(hashes[0] ?? "");
                  setPickerOpenFor(null);
                }}
              />
            </div>
          )}
        </div>
      </section>

      <p className="sources-field__label">
        Een source is een camera-stream, statische afbeelding, video-loop of
        audio die je in de graaf aan een of meerdere players kunt koppelen.
        Een source met nog players eraan gekoppeld kan niet verwijderd worden.
      </p>
    </div>
  );
}
