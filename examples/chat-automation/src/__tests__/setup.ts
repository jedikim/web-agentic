import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "./mocks/handlers";

// MSW lifecycle
beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => {
  server.resetHandlers();
  cleanup();
});
afterAll(() => server.close());

// Polyfill URL.createObjectURL (happy-dom doesn't support it)
if (typeof URL.createObjectURL === "undefined") {
  URL.createObjectURL = (blob: Blob) =>
    `blob:mock/${blob.size}`;
}
if (typeof URL.revokeObjectURL === "undefined") {
  URL.revokeObjectURL = () => {};
}
