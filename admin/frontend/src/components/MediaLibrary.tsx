import { useEffect, useState } from "react";
import { listMedia, uploadMedia, deleteMedia } from "../api/media";
import type { MediaItem } from "../types";
import "./MediaLibrary.css";

interface Props {
  kind: "image" | "audio" | "video";
  selected: string[];
  onSelectionChange: (hashes: string[]) => void;
  selectionMode: "single" | "multiple";
}

const KIND_COPY: Record<Props["kind"], { empty: string; upload: string }> = {
  image: {
    empty: "Nog geen afbeeldingen geüpload.",
    upload: "Afbeelding toevoegen",
  },
  audio: {
    empty: "Nog geen geluiden geüpload.",
    upload: "Geluid toevoegen",
  },
  video: {
    empty: "Nog geen video's geüpload.",
    upload: "Video toevoegen",
  },
};

function KindIcon({ kind }: { kind: Props["kind"] }) {
  if (kind === "image") {
    return (
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true">
        <rect x="3" y="4" width="18" height="14" rx="2" stroke="currentColor" strokeWidth="1.6" />
        <circle cx="8.5" cy="9" r="1.4" fill="currentColor" />
        <path d="M4 15.5l4.5-4 3.5 3 3-2.5L21 15" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
      </svg>
    );
  }
  if (kind === "video") {
    return (
      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true">
        <rect x="3" y="5" width="14" height="14" rx="2" stroke="currentColor" strokeWidth="1.6" />
        <path d="M17 9.5l4-2.5v10l-4-2.5" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true">
      <path d="M4 12h2l2-6 3 12 2-9 2 6h1.5" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
      <path d="M17 8v10a1.5 1.5 0 11-1.5-1.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M17 8l3-1v10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

export default function MediaLibrary({ kind, selected, onSelectionChange, selectionMode }: Props) {
  const [items, setItems] = useState<MediaItem[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const copy = KIND_COPY[kind];

  function refresh() {
    listMedia(kind)
      .then((result) => {
        setItems(result);
        setError(null);
      })
      .catch(() => setError("Bibliotheek kon niet worden geladen."));
  }

  useEffect(refresh, [kind]);

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      await uploadMedia(file, kind);
      setError(null);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Bestand kon niet worden geüpload.");
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  }

  async function handleDelete(hash: string) {
    try {
      await deleteMedia(hash);
      setError(null);
      onSelectionChange(selected.filter((h) => h !== hash));
      refresh();
    } catch {
      setError("Bestand kon niet worden verwijderd.");
    }
  }

  function toggleSelect(hash: string) {
    if (selectionMode === "single") {
      onSelectionChange([hash]);
    } else {
      onSelectionChange(
        selected.includes(hash) ? selected.filter((h) => h !== hash) : [...selected, hash],
      );
    }
  }

  return (
    <div className="media-library">
      <div className="media-library__toolbar">
        <label className={`media-upload ${uploading ? "media-upload--busy" : ""}`}>
          <input
            className="media-upload__input"
            type="file"
            onChange={handleUpload}
            disabled={uploading}
          />
          <span className="media-upload__plus" aria-hidden="true">
            +
          </span>
          {uploading ? "Bezig met uploaden…" : copy.upload}
        </label>
      </div>

      {error && (
        <p className="media-library__error" role="alert">
          {error}
        </p>
      )}

      {items.length === 0 ? (
        <p className="media-library__empty">{copy.empty}</p>
      ) : (
        <ul className="media-grid">
          {items.map((item) => {
            const isSelected = selected.includes(item.hash);
            return (
              <li key={item.hash} className="media-card" data-selected={isSelected}>
                <label className="media-card__select">
                  <input
                    className="media-card__input"
                    type={selectionMode === "single" ? "radio" : "checkbox"}
                    name={selectionMode === "single" ? `media-${kind}` : undefined}
                    checked={isSelected}
                    onChange={() => toggleSelect(item.hash)}
                  />
                  <span className="media-card__led" aria-hidden="true" />
                  <span className="media-card__icon">
                    <KindIcon kind={kind} />
                  </span>
                  <span className="media-card__name" title={item.filename}>
                    {item.filename}
                  </span>
                  <span className="media-card__hash">{item.hash.slice(0, 8)}</span>
                </label>
                <button
                  type="button"
                  className="media-card__delete"
                  onClick={() => handleDelete(item.hash)}
                  aria-label={`Verwijder ${item.filename}`}
                >
                  ×
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
