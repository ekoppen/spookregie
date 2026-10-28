import { useEffect, useRef, useState } from "react";
import { getSettings } from "../api/settings";
import { getPlayer } from "../api/players";
import { getSource } from "../api/sources";
import { useWebSocket } from "../hooks/useWebSocket";
import "./BeamerPage.css";

const STREAM_RETRY_MS = 2000;

// Fullscreen weergave voor de beamer-laptop: toont de MJPEG-stream van de
// mirror-node en speelt het geluid van elke scare-video die de mirror-node
// start af in de browser (de node zelf heeft op lan01 geen speaker).
export default function BeamerPage() {
  const [streamUrl, setStreamUrl] = useState<string | null>(null);
  const [streamAttempt, setStreamAttempt] = useState(0);
  const [started, setStarted] = useState(false);
  const playerAudio = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    getSettings()
      .then((s) => setStreamUrl(s.mirror_stream_url || null))
      .catch(() => setStreamUrl(null));
  }, []);

  useWebSocket((msg) => {
    if (!started) return;
    try {
      if (msg.type === "scare_playing") {
        const { hash } = JSON.parse(msg.payload) as { hash?: string };
        if (hash) new Audio(`/api/media/${hash}/audio`).play().catch(() => {});
      } else if (msg.type === "scene_active") {
        const { player_id } = JSON.parse(msg.payload) as { player_id?: number };
        if (player_id) playPlayerAudio(player_id).catch(() => {});
      }
    } catch {
      // ongeldige payload, negeren
    }
  });

  // Speelt het audio-source-geluid van de player waar de graaf net heen ging
  // (bv. de lokstem) één keer af; een volgende overgang kapt het af.
  async function playPlayerAudio(playerId: number) {
    playerAudio.current?.pause();
    playerAudio.current = null;
    const player = await getPlayer(playerId);
    if (player.audio_source_id == null) return;
    const source = await getSource(player.audio_source_id);
    if (source.kind !== "audio" || !source.value) return;
    const audio = new Audio(`/api/media/${source.value}`);
    playerAudio.current = audio;
    audio.play().catch(() => {});
  }

  function handleStart() {
    // Browsers staan geluid pas toe na een klik -- daarom deze startknop.
    setStarted(true);
    document.documentElement.requestFullscreen?.().catch(() => {});
  }

  // Herstart de mirror-node, dan breekt de stream af -- blijf opnieuw
  // proberen zodat de beamer zichzelf herstelt zonder dat iemand klikt.
  function handleStreamError() {
    setTimeout(() => setStreamAttempt((n) => n + 1), STREAM_RETRY_MS);
  }

  const src = streamUrl ? `${streamUrl}${streamUrl.includes("?") ? "&" : "?"}r=${streamAttempt}` : null;

  return (
    <div className="beamer">
      {src && <img className="beamer__stream" src={src} alt="" onError={handleStreamError} />}
      {!streamUrl && <p className="beamer__notice">Geen stream-URL ingesteld (Instellingen).</p>}
      {!started && (
        <button className="beamer__start" onClick={handleStart}>
          Klik om te starten (geluid + fullscreen)
        </button>
      )}
    </div>
  );
}
