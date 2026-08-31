import "@testing-library/jest-dom/vitest";

// ponytail: jsdom implementeert geen ResizeObserver; @xyflow/react gebruikt
// 'm intern (ZoomPane) om de viewport te meten. Stub is genoeg voor tests
// die geen echte layout-metingen nodig hebben.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
// @ts-expect-error -- jsdom heeft geen eigen ResizeObserver-type
globalThis.ResizeObserver = ResizeObserverStub;
