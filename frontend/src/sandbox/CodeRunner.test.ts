import { describe, expect, it } from "vitest";
import { executeSandboxCode } from "./CodeRunner";
import type { SandboxConfig } from "../types";

describe("CodeRunner", () => {
  it("executes Python list mutations with reference aliasing semantics", async () => {
    const config: SandboxConfig = {
      environment: "python_wasm",
      initial_code: "a = [1, 2, 3]\nb = a\nb.append(4)\nprint(a)",
      test_cases: [
        {
          name: "Verify shared reference mutation",
          expected_output: "[1, 2, 3, 4]",
        },
      ],
      hints: ["b = a creates an alias"],
    };

    const report = await executeSandboxCode(config.initial_code, config);

    expect(report.passed).toBe(true);
    expect(report.stdout).toBe("[1, 2, 3, 4]");
    expect(report.testResults[0].passed).toBe(true);
  });

  it("executes Python for loop with range", async () => {
    const config: SandboxConfig = {
      environment: "python_wasm",
      initial_code: "for i in range(4):\n    print(i)",
      test_cases: [
        {
          name: "Verify range output",
          expected_output: "0\n1\n2\n3",
        },
      ],
      hints: [],
    };

    const report = await executeSandboxCode(config.initial_code, config);

    expect(report.passed).toBe(true);
    expect(report.stdout).toBe("0\n1\n2\n3");
  });

  it("executes Python list comprehension", async () => {
    const config: SandboxConfig = {
      environment: "python_wasm",
      initial_code: "evens = [x**2 for x in range(10) if x % 2 == 0]\nprint(evens)",
      test_cases: [
        {
          name: "Verify squares of evens",
          expected_output: "[0, 4, 16, 36, 64]",
        },
      ],
      hints: [],
    };

    const report = await executeSandboxCode(config.initial_code, config);

    expect(report.passed).toBe(true);
    expect(report.stdout).toBe("[0, 4, 16, 36, 64]");
  });

  it("handles JavaScript evaluation sandbox", async () => {
    const config: SandboxConfig = {
      environment: "javascript_eval",
      initial_code: "const arr = [1, 2]; arr.push(3); console.log(JSON.stringify(arr));",
      test_cases: [
        {
          name: "Verify JS push",
          expected_output: "[1,2,3]",
        },
      ],
      hints: [],
    };

    const report = await executeSandboxCode(config.initial_code, config);

    expect(report.passed).toBe(true);
    expect(report.stdout).toContain("[1,2,3]");
  });
});
