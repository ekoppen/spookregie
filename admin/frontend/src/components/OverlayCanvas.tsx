import {
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from "react";
import { pixelToFraction, clampFraction } from "../lib/overlayMath";
import "./OverlayCanvas.css";

interface Props {
  streamUrl: string;
  overlayUrl: string | null;
  scale: number;
  position: [number, number];
  onPositionChange: (position: [number, number]) => void;
  onScaleChange: (scale: number) => void;
  // Zonder canvasSize: bestaand gedrag, streamUrl vult de viewfinder 1:1 en
  // is niet zelf sleepbaar. Mét canvasSize: de viewfinder krijgt de
  // aspect-ratio van het canvas en streamUrl wordt een tweede sleep-/
  // schaalbare laag daarbinnen (zelfde plaatsingslogica als de overlay).
  canvasSize?: [number, number] | null;
  sourceScale?: number;
  sourcePosition?: [number, number];
  onSourcePositionChange?: (position: [number, number]) => void;
  onSourceScaleChange?: (scale: number) => void;
}

// Eén sleep-implementatie voor zowel de bron- als de overlay-laag -- beide
// verplaatsen een [x, y]-fractie binnen dezelfde canvas-container.
function useDragLayer(
  containerRef: RefObject<HTMLDivElement | null>,
  position: [number, number],
  onPositionChange: (position: [number, number]) => void,
) {
  const [dragging, setDragging] = useState(false);
  const grabOffsetRef = useRef<[number, number]>([0, 0]);

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

  return { dragging, handlePointerDown, handlePointerMove, handlePointerUp };
}

export default function OverlayCanvas({
  streamUrl,
  overlayUrl,
  scale,
  position,
  onPositionChange,
  onScaleChange,
  canvasSize = null,
  sourceScale = 1,
  sourcePosition = [0.5, 0.5],
  onSourcePositionChange,
  onSourceScaleChange,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const streamImgRef = useRef<HTMLImageElement>(null);
  // WYSIWYG-correctie: de node schaalt t.o.v. camera-frame-pixels (of, met
  // canvasSize, t.o.v. canvas-pixels), maar hier wordt op CSS-breedte
  // getoond -- zonder deze factor klopt de op-schermschaal alleen toevallig.
  const [displayScaleFactor, setDisplayScaleFactor] = useState(1);

  function updateDisplayScaleFactor() {
    if (canvasSize) {
      const box = containerRef.current;
      if (!box || !canvasSize[0]) return;
      setDisplayScaleFactor(box.getBoundingClientRect().width / canvasSize[0]);
      return;
    }
    const img = streamImgRef.current;
    if (!img || !img.naturalWidth) return;
    setDisplayScaleFactor(img.clientWidth / img.naturalWidth);
  }

  useEffect(() => {
    updateDisplayScaleFactor();
    window.addEventListener("resize", updateDisplayScaleFactor);
    return () => window.removeEventListener("resize", updateDisplayScaleFactor);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canvasSize?.[0], canvasSize?.[1]]);

  const overlayDrag = useDragLayer(containerRef, position, onPositionChange);
  const sourceDrag = useDragLayer(
    containerRef,
    sourcePosition,
    onSourcePositionChange ?? (() => {}),
  );

  return (
    <div className="overlay-canvas">
      <div
        ref={containerRef}
        className="overlay-canvas__viewfinder"
        data-dragging={overlayDrag.dragging || sourceDrag.dragging}
        style={canvasSize ? { aspectRatio: `${canvasSize[0]} / ${canvasSize[1]}` } : undefined}
      >
        <span className="overlay-canvas__bracket overlay-canvas__bracket--tl" aria-hidden="true" />
        <span className="overlay-canvas__bracket overlay-canvas__bracket--tr" aria-hidden="true" />
        <span className="overlay-canvas__bracket overlay-canvas__bracket--bl" aria-hidden="true" />
        <span className="overlay-canvas__bracket overlay-canvas__bracket--br" aria-hidden="true" />
        <span className="overlay-canvas__scanline" aria-hidden="true" />

        {canvasSize ? (
          <div
            className="overlay-canvas__reticle"
            style={{ left: `${sourcePosition[0] * 100}%`, top: `${sourcePosition[1] * 100}%` }}
          >
            <img
              ref={streamImgRef}
              className="overlay-canvas__source"
              src={streamUrl}
              alt="Camera-bron -- sleepgreep voor positie binnen het canvas"
              draggable={false}
              onLoad={updateDisplayScaleFactor}
              onPointerDown={sourceDrag.handlePointerDown}
              onPointerMove={sourceDrag.handlePointerMove}
              onPointerUp={sourceDrag.handlePointerUp}
              onPointerCancel={sourceDrag.handlePointerUp}
              style={{ transform: `translate(-50%, -50%) scale(${sourceScale * displayScaleFactor})` }}
            />
          </div>
        ) : (
          <img
            ref={streamImgRef}
            className="overlay-canvas__stream"
            src={streamUrl}
            alt="Live spiegel-feed"
            onLoad={updateDisplayScaleFactor}
          />
        )}

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
              onPointerDown={overlayDrag.handlePointerDown}
              onPointerMove={overlayDrag.handlePointerMove}
              onPointerUp={overlayDrag.handlePointerUp}
              onPointerCancel={overlayDrag.handlePointerUp}
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

      <div className="overlay-canvas__levers">
        {canvasSize && onSourceScaleChange && (
          <div className="overlay-canvas__lever">
            <span className="overlay-canvas__lever-label">Bron</span>
            <input
              className="overlay-canvas__lever-input"
              type="range"
              min="0.1"
              max="3"
              step="0.05"
              value={sourceScale}
              onChange={(e) => onSourceScaleChange(parseFloat(e.target.value))}
              aria-label="Bron-schaal"
            />
            <span className="overlay-canvas__lever-value">{sourceScale.toFixed(2)}×</span>
          </div>
        )}
        <div className="overlay-canvas__lever">
          <span className="overlay-canvas__lever-label">{canvasSize ? "Overlay" : "Schaal"}</span>
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
    </div>
  );
}
