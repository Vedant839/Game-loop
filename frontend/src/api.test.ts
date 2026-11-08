import { beforeEach, describe, expect, it, vi } from "vitest";
import { getLearnerId } from "./api";

describe("getLearnerId", () => {
  beforeEach(() => localStorage.clear());

  it("keeps a stable anonymous ID per creator", () => {
    vi.spyOn(window.crypto, "randomUUID").mockReturnValueOnce("learner-a").mockReturnValueOnce("learner-b");
    expect(getLearnerId("creator-a")).toBe("learner-a");
    expect(getLearnerId("creator-a")).toBe("learner-a");
    expect(getLearnerId("creator-b")).toBe("learner-b");
    expect(localStorage.getItem("gl_learner_creator-a")).toBe("learner-a");
  });

  it("does not fall back to tab-only session storage", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    expect(() => getLearnerId()).toThrow("browser local storage is unavailable");
  });
});
