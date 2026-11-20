import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

/** A minimal in-memory Storage, enough for the app's get/set/clear use. */
class MemoryStorage implements Storage {
  private readonly entries = new Map<string, string>();

  get length(): number {
    return this.entries.size;
  }

  clear(): void {
    this.entries.clear();
  }

  getItem(key: string): string | null {
    return this.entries.get(key) ?? null;
  }

  key(index: number): string | null {
    return Array.from(this.entries.keys())[index] ?? null;
  }

  removeItem(key: string): void {
    this.entries.delete(key);
  }

  setItem(key: string, value: string): void {
    this.entries.set(key, value);
  }
}

// Recent Node versions define their own `localStorage` global, which is
// undefined unless Node is started with a storage file, and it shadows the one
// jsdom provides. Tests get a predictable in-memory store instead.
Object.defineProperty(window, "localStorage", {
  configurable: true,
  value: new MemoryStorage(),
});

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});
