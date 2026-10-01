import { cleanup } from "@testing-library/react";
import { toast } from "sonner";
import { afterAll, afterEach, beforeAll } from "vitest";

import { configureApi } from "@/lib/api";

import { server } from "./api";

configureApi("http://test");
beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => {
  toast.dismiss(); // sonner's store is module-level; don't leak toasts into the next test
  cleanup();
  server.resetHandlers();
  localStorage.clear();
});
afterAll(() => server.close());

// jsdom lacks these; Base UI and the sidebar use them.
window.matchMedia ??= ((query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addEventListener: () => {},
  removeEventListener: () => {},
  addListener: () => {},
  removeListener: () => {},
  dispatchEvent: () => false,
})) as typeof window.matchMedia;
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

// Base UI positions popups with these; jsdom has neither.
Element.prototype.scrollIntoView ??= () => {};
Element.prototype.hasPointerCapture ??= () => false;
