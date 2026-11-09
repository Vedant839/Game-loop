import { beforeEach, describe, expect, it, vi } from "vitest";
import { getLearnerId, hasTabOnlyProgress } from "./api";

describe("getLearnerId", () => {
  beforeEach(() => localStorage.clear());

  it("keeps a stable anonymous ID per creator", () => {
    vi.spyOn(window.crypto, "randomUUID").mockReturnValueOnce("00000000-0000-4000-8000-000000000001").mockReturnValueOnce("00000000-0000-4000-8000-000000000002");
    expect(getLearnerId("creator-a")).toBe("00000000-0000-4000-8000-000000000001");
    expect(getLearnerId("creator-a")).toBe("00000000-0000-4000-8000-000000000001");
    expect(getLearnerId("creator-b")).toBe("00000000-0000-4000-8000-000000000002");
    expect(localStorage.getItem("gl_learner_creator-a")).toBe("00000000-0000-4000-8000-000000000001");
  });

  it("falls back to session storage and reports tab-only progress when local storage throws", async () => {
    const storage = Object.getPrototypeOf(window.localStorage) as Storage;
    const originalGet = storage.getItem;
    const originalSet = storage.setItem;
    vi.spyOn(storage, "getItem").mockImplementation(function (this: Storage, key: string) {
      if (this === window.localStorage) throw new Error("blocked");
      return originalGet.call(this, key);
    });
    vi.spyOn(storage, "setItem").mockImplementation(function (this: Storage, key: string, value: string) {
      if (this === window.localStorage) throw new Error("blocked");
      return originalSet.call(this, key, value);
    });
    vi.spyOn(window.crypto, "randomUUID").mockReturnValue("00000000-0000-4000-8000-000000000003");

    expect(getLearnerId("creator-b")).toBe("00000000-0000-4000-8000-000000000003");
    expect(window.sessionStorage.getItem("gl_learner_creator-b")).toBe("00000000-0000-4000-8000-000000000003");
    expect(hasTabOnlyProgress()).toBe(true);
  });

  it("keeps an in-memory learner ID if both browser storage APIs throw", () => {
    const storage = Object.getPrototypeOf(window.localStorage) as Storage;
    vi.spyOn(storage, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(storage, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(window.crypto, "randomUUID").mockReturnValue("00000000-0000-4000-8000-000000000004");

    expect(getLearnerId("creator-c")).toBe("00000000-0000-4000-8000-000000000004");
    expect(getLearnerId("creator-c")).toBe("00000000-0000-4000-8000-000000000004");
    expect(hasTabOnlyProgress()).toBe(true);
  });
});
