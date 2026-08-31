import { useEffect, useRef, useState } from "react";
import type { SceneDraft } from "../api/scenes";
import "./PreviewPanel.css";

interface Props {
  draft: SceneDraft;
  onClose: () => void;
}

export default function PreviewPanel({ draft, onClose }: Props) {
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const lastFetchedAtRef = useRef(0);
  const throttleTimerRef = useRef<number | null>(null);

  // Leading-edge throttle (max. 1x per 150ms), zelfde patroon als de
  // vroegere live-hardware-preview -- alleen doelt dit nu op de eigen
  // /api/players/preview-frame-route i.p.v. de fysieke spiegel.
  useEffect(() => {
    const THROTTLE_MS = 150;

    async function fetchPreview() {
      lastFetchedAtRef.current = Date.now();
      setLoading(true);
      try {
        const response = await fetch("/api/players/preview-frame", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(draft),
        });
        if (!response.ok) {
          setError("Voorbeeld kon niet worden opgehaald.");
          return;
        }
        const blob = await response.blob();
        setImageUrl((prev) => {
          if (prev) URL.revokeObjectURL(prev);
          return URL.createObjectURL(blob);
        });
        setError(null);
      } catch {
        setError("Voorbeeld kon niet worden opgehaald.");
      } finally {
        setLoading(false);
      }
    }

    const elapsed = Date.now() - lastFetchedAtRef.current;
    if (elapsed >= THROTTLE_MS) {
      fetchPreview();
    } else {
      if (throttleTimerRef.current) window.clearTimeout(throttleTimerRef.current);
      throttleTimerRef.current = window.setTimeout(fetchPreview, THROTTLE_MS - elapsed);
    }

    return () => {
      if (throttleTimerRef.current) window.clearTimeout(throttleTimerRef.current);
    };
  }, [draft]);

  useEffect(() => {
    return () => {
      if (imageUrl) URL.revokeObjectURL(imageUrl);
    };
  }, [imageUrl]);

  return (
    <div className="preview-panel">
      <div className="preview-panel__header">
        <p className="preview-panel__title">Voorbeeld</p>
        <button type="button" className="preview-panel__close" onClick={onClose} aria-label="Sluiten">
          ×
        </button>
      </div>
      {error && (
        <p className="preview-panel__error" role="alert">
          {error}
        </p>
      )}
      {imageUrl ? (
        <img className="preview-panel__image" src={imageUrl} alt="Voorbeeld van de scene" />
      ) : (
        <p className="preview-panel__loading">{loading ? "Bezig…" : "Nog geen voorbeeld."}</p>
      )}
    </div>
  );
}
