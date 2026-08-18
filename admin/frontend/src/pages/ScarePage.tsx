import { useEffect, useState } from "react";
import { getScareConfig, putScareConfig, testScare } from "../api/scare";
import MediaLibrary from "../components/MediaLibrary";
import "./ScarePage.css";

// ponytail: geen backend zone-register -- kleine hardgecodeerde lijst + vrij invoerveld,
// zoals de brief voorschrijft. Zone-CRUD is buiten scope van dit plan.
const KNOWN_ZONES = ["zone-a", "zone-b"];

export default function ScarePage() {
  const [zone, setZone] = useState(KNOWN_ZONES[0]);
  const [customZone, setCustomZone] = useState("");
  const [enabledHashes, setEnabledHashes] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    getScareConfig(zone)
      .then((c) => {
        setEnabledHashes(c.enabled_hashes);
        setError(null);
      })
      .catch(() => setError("Zoneconfiguratie kon niet worden geladen."));
  }, [zone]);

  async function handleSave() {
    setSaving(true);
    try {
      await putScareConfig(zone, { enabled_hashes: enabledHashes });
      setError(null);
    } catch {
      setError("Opslaan is mislukt. Probeer het opnieuw.");
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    setTesting(true);
    try {
      await testScare(zone);
      setError(null);
    } catch {
      setError("Testoproep is mislukt.");
    } finally {
      setTesting(false);
    }
  }

  function commitCustomZone() {
    if (customZone.trim()) {
      setZone(customZone.trim());
      setCustomZone("");
    }
  }

  return (
    <div className="scare-page">
      <header className="scare-header">
        <p className="scare-eyebrow">
          <span className="scare-eyebrow__led" aria-hidden="true" />
          Scare-node
        </p>
        <h1 className="scare-heading">Scare-audio</h1>
      </header>

      {error && (
        <p className="scare-error" role="alert">
          {error}
        </p>
      )}

      <section className="scare-panel">
        <p className="scare-panel__eyebrow">Zone</p>
        <p className="scare-active-zone">
          Actieve zone: <strong>{zone}</strong>
        </p>
        <div className="scare-zone-row">
          {KNOWN_ZONES.map((z) => (
            <button
              key={z}
              type="button"
              className="scare-zone-chip"
              aria-pressed={zone === z}
              onClick={() => setZone(z)}
            >
              <span className="scare-zone-chip__led" aria-hidden="true" />
              {z}
            </button>
          ))}
          <input
            className="scare-zone-custom"
            type="text"
            placeholder="andere zone…"
            value={customZone}
            onChange={(e) => setCustomZone(e.target.value)}
            onBlur={commitCustomZone}
            onKeyDown={(e) => e.key === "Enter" && commitCustomZone()}
          />
        </div>
      </section>

      <section className="scare-panel">
        <p className="scare-panel__eyebrow">Geluidsbibliotheek</p>
        <MediaLibrary
          category="scare_audio"
          selectionMode="multiple"
          selected={enabledHashes}
          onSelectionChange={setEnabledHashes}
        />
      </section>

      <div className="scare-actions">
        <button className="scare-save" type="button" onClick={handleSave} disabled={saving}>
          {saving ? "Bezig…" : "Opslaan"}
        </button>
        <button className="scare-test" type="button" onClick={handleTest} disabled={testing}>
          {testing ? "Bezig…" : "Test"}
        </button>
      </div>
    </div>
  );
}
