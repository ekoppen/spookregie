export function pixelToFraction(px: number, containerSize: number): number {
  if (containerSize === 0) return 0;
  return px / containerSize;
}

export function fractionToPixel(fraction: number, containerSize: number): number {
  return fraction * containerSize;
}

export function clampFraction(fraction: number): number {
  return Math.min(1, Math.max(0, fraction));
}
