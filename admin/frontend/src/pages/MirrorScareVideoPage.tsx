import { useEffect, useState } from "react";
import { getMirrorScareVideoConfig, putMirrorScareVideoConfig } from "../api/mirrorScareVideo";
import MediaLibrary from "../components/MediaLibrary";
import "./MirrorScareVideoPage.css";

export default function MirrorScareVideoPage() {
  const [enabledHashes, setEnabledHashes] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getMirrorScareVideoConfig()
      .then((c) => {
        setEnabledHashes(c.enabled_hashes);
        setError(null);
      })
      .catch(() => setError("Configuratie kon niet worden geladen."));
  }, []);

  async function handleSave() {
    setSaving(true);
    try {
      await putMirrorScareVideoConfig({ enabled_hashes: enabledHashes });
      setError(null);
    } catch {
      setError("Opslaan is mislukt. Probeer het opnieuw.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mirror-scare-video-page">
      <header className="mirror-scare-video-header">
        <p className="mirror-scare-video-eyebrow">
          <span className="mirror-scare-video-eyebrow__led" aria-hidden="true" />
          Spiegel-node
        </p>
        <h1 className="mirror-scare-video-heading">Scare-video's</h1>
      </header>

      {error && (
        <p className="mirror-scare-video-error" role="alert">
          {error}
        </p>
      )}

      <section className="mirror-scare-video-panel">
        <p className="mirror-scare-video-panel__eyebrow">Video-bibliotheek</p>
        <p className="mirror-scare-video-hint">
          Ingeschakelde video's worden willekeurig gekozen en vervangen bij een trigger tijdelijk
          het live beeld (inclusief geluid, indien aanwezig).
        </p>
        <MediaLibrary
          kind="video"
          selectionMode="multiple"
          selected={enabledHashes}
          onSelectionChange={setEnabledHashes}
        />
      </section>

      <div className="mirror-scare-video-actions">
        <button
          className="mirror-scare-video-save"
          type="button"
          onClick={handleSave}
          disabled={saving}
        >
          {saving ? "Bezig…" : "Opslaan"}
        </button>
      </div>
    </div>
  );
}
