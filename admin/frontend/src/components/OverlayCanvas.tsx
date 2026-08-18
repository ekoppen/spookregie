import { useEffect, useRef, useState } from "react";
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
  const [dragging, setDragging] = useState(false);

  // Track drag on window, not just the container: a fast drag easily carries
  // the cursor past the viewfinder's edges (exactly where users drag toward),
  // and container-scoped onMouseMove/onMouseLeave would silently end the drag.
  useEffect(() => {
    if (!dragging) return;

    function handleWindowMouseMove(e: MouseEvent) {
      if (!containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const x = clampFraction(pixelToFraction(e.clientX - rect.left, rect.width));
      const y = clampFraction(pixelToFraction(e.clientY - rect.top, rect.height));
      onPositionChange([x, y]);
    }
    function handleWindowMouseUp() {
      setDragging(false);
    }

    window.addEventListener("mousemove", handleWindowMouseMove);
    window.addEventListener("mouseup", handleWindowMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleWindowMouseMove);
      window.removeEventListener("mouseup", handleWindowMouseUp);
    };
  }, [dragging, onPositionChange]);

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

        <img className="overlay-canvas__stream" src={streamUrl} alt="Live spiegel-feed" />

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
              alt="Overlay"
              draggable={false}
              onMouseDown={() => setDragging(true)}
              style={{ transform: `translate(-50%, -50%) scale(${scale})` }}
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
