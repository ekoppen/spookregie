import { useState } from "react";
import MediaLibrary from "../components/MediaLibrary";
import "./MediaPage.css";

export default function MediaPage() {
  const [selectedImage, setSelectedImage] = useState<string[]>([]);
  const [selectedAudio, setSelectedAudio] = useState<string[]>([]);
  const [selectedVideo, setSelectedVideo] = useState<string[]>([]);

  return (
    <div className="media-page">
      <header className="media-page__header">
        <p className="media-page__eyebrow">
          <span className="media-page__eyebrow-led" aria-hidden="true" />
          Mediabibliotheek
        </p>
        <h1 className="media-page__heading">Media</h1>
        <p className="media-page__hint">
          Foto's, video's en audio die je in de flow-graaf kunt gebruiken (als
          Source, overlay, of scare-video/-audio). Uploaden hieronder maakt het
          bestand meteen overal beschikbaar waar dat kind gekozen kan worden.
        </p>
      </header>

      <section className="media-page__section">
        <h2 className="media-page__section-heading">Afbeeldingen</h2>
        <MediaLibrary kind="image" selectionMode="multiple" selected={selectedImage} onSelectionChange={setSelectedImage} />
      </section>

      <section className="media-page__section">
        <h2 className="media-page__section-heading">Audio</h2>
        <MediaLibrary kind="audio" selectionMode="multiple" selected={selectedAudio} onSelectionChange={setSelectedAudio} />
      </section>

      <section className="media-page__section">
        <h2 className="media-page__section-heading">Video's</h2>
        <MediaLibrary kind="video" selectionMode="multiple" selected={selectedVideo} onSelectionChange={setSelectedVideo} />
      </section>
    </div>
  );
}
