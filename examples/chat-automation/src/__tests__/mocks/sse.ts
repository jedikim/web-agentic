import type { ProgressEvent, HandoffEvent, TurnCompleteEvent } from "../../types";

type Listener = (event: { data: string }) => void;

/**
 * Mock EventSource for testing SSE subscription.
 * Allows tests to emit events programmatically.
 */
export class MockEventSource {
  url: string;
  readyState = 0; // CONNECTING
  onerror: (() => void) | null = null;

  private listeners = new Map<string, Listener[]>();

  constructor(url: string) {
    this.url = url;
    // Simulate connection opening
    setTimeout(() => {
      this.readyState = 1; // OPEN
    }, 0);
  }

  addEventListener(type: string, listener: Listener) {
    const list = this.listeners.get(type) || [];
    list.push(listener);
    this.listeners.set(type, list);
  }

  removeEventListener(type: string, listener: Listener) {
    const list = this.listeners.get(type) || [];
    this.listeners.set(
      type,
      list.filter((l) => l !== listener),
    );
  }

  close() {
    this.readyState = 2; // CLOSED
    this.listeners.clear();
  }

  /** Emit a raw event to listeners of a given type. */
  emit(type: string, data: unknown) {
    const listeners = this.listeners.get(type) || [];
    const event = { data: JSON.stringify(data) };
    for (const listener of listeners) {
      listener(event);
    }
  }

  /** Emit a session_progress event. */
  emitProgress(data: ProgressEvent) {
    this.emit("session_progress", data);
  }

  /** Emit a handoff_requested event. */
  emitHandoff(data: HandoffEvent) {
    this.emit("handoff_requested", data);
  }

  /** Emit a session_turn_completed event. */
  emitTurnComplete(data: TurnCompleteEvent) {
    this.emit("session_turn_completed", data);
  }
}

/** Last created MockEventSource instance (for test access). */
export let lastMockEventSource: MockEventSource | null = null;

/**
 * Install MockEventSource as globalThis.EventSource.
 * Returns a cleanup function that restores the original.
 */
export function installMockEventSource(): () => void {
  const original = globalThis.EventSource;

  // @ts-expect-error -- MockEventSource is not a full EventSource implementation
  globalThis.EventSource = class extends MockEventSource {
    constructor(url: string) {
      super(url);
      lastMockEventSource = this;
    }
  };

  return () => {
    globalThis.EventSource = original;
    lastMockEventSource = null;
  };
}
