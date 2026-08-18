import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { pixelToFraction, clampFraction } from "../lib/overlayMath";
import "./OverlayCanvas.css";

interface Props {
  streamUrl: string;
  overlayUrl: string | null;
  scale: number;
  position: [number, number];
  onPositionChange: (position: [number, number]) => void;
  onScaleChange: (scale: number) => void;
}

export default function OverlayCanvas({
  streamUrl,
  overlayUrl,
  scale,
  position,
  onPositionChange,
  onScaleChange,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const streamImgRef = useRef<HTMLImageElement>(null);
  const [dragging, setDragging] = useState(false);
  // WYSIWYG-correctie: de node schaalt de overlay t.o.v. de camera-frame-
  // pixels, maar hier wordt de stream op CSS-breedte getoond (die zelden
  // gelijk is aan de camera's eigen resolutie). Zonder deze factor klopt de
  // op-schermschaal alleen toevallig met wat de node daadwerkelijk componeert.
  const [displayScaleFactor, setDisplayScaleFactor] = useState(1);
  // Offset (in fractie-ruimte) tussen het gegrepen punt en het middelpunt van
  // de overlay op pointerdown -- zonder dit "springt" de overlay naar de
  // cursor zodra je 'm niet precies in het midden grijpt.
  const grabOffsetRef = useRef<[number, number]>([0, 0]);

  function updateDisplayScaleFactor() {
    const img = streamImgRef.current;
    if (!img || !img.naturalWidth) return;
    setDisplayScaleFactor(img.clientWidth / img.naturalWidth);
  }

  useEffect(() => {
    updateDisplayScaleFactor();
    window.addEventListener("resize", updateDisplayScaleFactor);
    return () => window.removeEventListener("resize", updateDisplayScaleFactor);
  }, []);

  // Pointer Events i.p.v. mouse events: één code path voor muis, touch én
  // pen (dit is realistisch een telefoon naast de fysieke spiegel), en
  // setPointerCapture routeert move/up naar dit element ongeacht waar de
  // cursor heen gaat -- lost het "cursor verlaat de viewfinder" probleem
  // zonder window-listeners op.
  function handlePointerDown(e: ReactPointerEvent<HTMLImageElement>) {
    if (!containerRef.current) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    const rect = containerRef.current.getBoundingClientRect();
    const pointerX = clampFraction(pixelToFraction(e.clientX - rect.left, rect.width));
    const pointerY = clampFraction(pixelToFraction(e.clientY - rect.top, rect.height));
    grabOffsetRef.current = [position[0] - pointerX, position[1] - pointerY];
    setDragging(true);
  }

  function handlePointerMove(e: ReactPointerEvent<HTMLImageElement>) {
    if (!dragging || !containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const pointerX = clampFraction(pixelToFraction(e.clientX - rect.left, rect.width));
    const pointerY = clampFraction(pixelToFraction(e.clientY - rect.top, rect.height));
    const [offsetX, offsetY] = grabOffsetRef.current;
    onPositionChange([clampFraction(pointerX + offsetX), clampFraction(pointerY + offsetY)]);
  }

  function handlePointerUp(e: ReactPointerEvent<HTMLImageElement>) {
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
    setDragging(false);
  }

  return (
    <div className="overlay-canvas">
      <div
        ref={containerRef}
        className="overlay-canvas__viewfinder"
        data-dragging={dragging}
      >
        <span className="overlay-canvas__bracket overlay-canvas__bracket--tl" aria-hidden="true" />
        <span className="overlay-canvas__bracket overlay-canvas__bracket--tr" aria-hidden="true" />
        <span className="overlay-canvas__bracket overlay-canvas__bracket--bl" aria-hidden="true" />
        <span className="overlay-canvas__bracket overlay-canvas__bracket--br" aria-hidden="true" />
        <span className="overlay-canvas__scanline" aria-hidden="true" />

        <img
          ref={streamImgRef}
          className="overlay-canvas__stream"
          src={streamUrl}
          alt="Live spiegel-feed"
          onLoad={updateDisplayScaleFactor}
        />

        {overlayUrl && (
          <div
            className="overlay-canvas__reticle"
            style={{
              left: `${position[0] * 100}%`,
              top: `${position[1] * 100}%`,
            }}
          >
            <img
              className="overlay-canvas__overlay"
              src={overlayUrl}
              alt="Sleepgreep voor overlay-positie (indicatief, geen eindresultaat -- de node componeert de echte overlay)"
              draggable={false}
              onPointerDown={handlePointerDown}
              onPointerMove={handlePointerMove}
              onPointerUp={handlePointerUp}
              onPointerCancel={handlePointerUp}
              style={{ transform: `translate(-50%, -50%) scale(${scale * displayScaleFactor})` }}
            />
            <span className="overlay-canvas__crosshair" aria-hidden="true">
              <span className="overlay-canvas__crosshair-ring" />
              <span className="overlay-canvas__crosshair-line overlay-canvas__crosshair-line--h" />
              <span className="overlay-canvas__crosshair-line overlay-canvas__crosshair-line--v" />
            </span>
          </div>
        )}
      </div>

      <div className="overlay-canvas__lever">
        <span className="overlay-canvas__lever-label">Schaal</span>
        <input
          className="overlay-canvas__lever-input"
          type="range"
          min="0.1"
          max="3"
          step="0.05"
          value={scale}
          onChange={(e) => onScaleChange(parseFloat(e.target.value))}
          aria-label="Overlay-schaal"
        />
        <span className="overlay-canvas__lever-value">{scale.toFixed(2)}×</span>
      </div>
    </div>
  );
}
