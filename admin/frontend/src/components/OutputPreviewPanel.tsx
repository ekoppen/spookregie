import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { getSettings } from "../api/settings";
import { startMirrorProcess, stopMirrorProcess, getMirrorProcessStatus } from "../api/mirrorProcess";
import "./OutputPreviewPanel.css";

interface Props {
  onClose: () => void;
}

// Preview van het volledige, samengestelde graaf-resultaat -- één globaal
// mirror-node-kindproces (camera + effect + overlay + scare-video), geen
// aparte stream per output. Zie docs/superpowers/specs voor de achtergrond:
// dit hergebruikt de al bestaande headless-start/stop-machinerie, die tot nu
// toe nooit een zichtbare <img> had.
export default function OutputPreviewPanel({ onClose }: Props) {
  const navigate = useNavigate();
  const [streamUrl, setStreamUrl] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSettings()
      .then((s) => setStreamUrl(s.mirror_stream_url || null))
      .catch(() => setError("Instellingen konden niet worden geladen."));
    getMirrorProcessStatus()
      .then((s) => setRunning(s.running))
      .catch(() => {
        /* status blijft "gestopt" tonen bij een netwerkfout */
      });
  }, []);

  async function handleStart() {
    setBusy(true);
    try {
      const status = await startMirrorProcess();
      setRunning(status.running);
      setError(null);
    } catch {
      setError("Starten is mislukt.");
    } finally {
      setBusy(false);
    }
  }

  async function handleStop() {
    setBusy(true);
    try {
      const status = await stopMirrorProcess();
      setRunning(status.running);
      setError(null);
    } catch {
      setError("Stoppen is mislukt.");
    } finally {
      setBusy(false);
    }
  }

  return createPortal(
    <div className="output-preview__backdrop" role="dialog" aria-modal="true">
      <div className="output-preview">
        <header className="output-preview__header">
          <p className="output-preview__title">Live voorbeeld</p>
          <button type="button" className="output-preview__close" onClick={onClose} aria-label="Sluiten">
            Sluiten
          </button>
        </header>

        {error && (
          <p className="output-preview__error" role="alert">
            {error}
          </p>
        )}

        <div className="output-preview__stage">
          {running && streamUrl ? (
            <img className="output-preview__image" src={streamUrl} alt="Live voorbeeld van de spiegel-uitvoer" />
          ) : running ? (
            <p className="output-preview__hint">
              Geen live-preview-stream-URL ingesteld. Stel deze in bij{" "}
              <button type="button" className="output-preview__link" onClick={() => navigate("/settings")}>
                Instellingen
              </button>
              .
            </p>
          ) : (
            <p className="output-preview__hint">Nog gestopt -- klik op Start om het voorbeeld te bekijken.</p>
          )}
        </div>

        <div className="output-preview__actions">
          <button type="button" onClick={handleStart} disabled={busy || running}>
            Start
          </button>
          <button type="button" onClick={handleStop} disabled={busy || !running}>
            Stop
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
