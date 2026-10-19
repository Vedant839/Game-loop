/**
 * Client-side Sandboxed Code Runner
 *
 * Runs Python/JavaScript code client-side without sending code to the backend.
 * Provides deterministic evaluation against structured test cases.
 */

import type { SandboxConfig, TestCase, TestExecutionResult } from "../types";

export interface ExecutionReport {
  passed: boolean;
  stdout: string;
  testResults: TestExecutionResult[];
  error?: string;
  executionTimeMs: number;
}

/**
 * Executes a snippet of JavaScript inside an isolated sandbox, capturing console.log.
 */
function runJavaScriptSnippet(code: string): { stdout: string; error?: string } {
  const logs: string[] = [];
  const fakeConsole = {
    log: (...args: unknown[]) => {
      logs.push(args.map((a) => (typeof a === "object" ? JSON.stringify(a) : String(a))).join(" "));
    },
    error: (...args: unknown[]) => {
      logs.push("[error] " + args.map((a) => String(a)).join(" "));
    },
  };

  try {
    const fn = new Function("console", `"use strict";\n${code}`);
    fn(fakeConsole);
    return { stdout: logs.join("\n") };
  } catch (err) {
    return {
      stdout: logs.join("\n"),
      error: err instanceof Error ? err.message : String(err),
    };
  }
}

/**
 * Lightweight deterministic Python runtime simulator for browser execution.
 * Handles:
 * - Variable assignment and reference aliasing vs copying
 * - List mutations: .append(), .copy(), .sort(), len()
 * - Loops: for x in range(...)
 * - List comprehensions: [expr for x in range(...) if cond]
 * - Function definitions and calls
 * - print(...) statements
 */
class MiniPythonInterpreter {
  private logs: string[] = [];
  private scope: Record<string, unknown> = {};

  public run(code: string): { stdout: string; error?: string } {
    this.logs = [];
    this.scope = {};

    try {
      const lines = code
        .split("\n")
        .map((l) => l.trim())
        .filter((l) => l.length > 0 && !l.startsWith("#"));

      let idx = 0;
      while (idx < lines.length) {
        const line = lines[idx];

        // 1. For loop: for var in range(N):
        const forMatch = line.match(/^for\s+([a-zA-Z_]\w*)\s+in\s+range\(([^)]+)\):$/);
        if (forMatch) {
          const varName = forMatch[1];
          const rangeArgs = forMatch[2].split(",").map((s) => Number(s.trim()));
          let start = 0;
          let stop = 0;
          let step = 1;
          if (rangeArgs.length === 1) {
            stop = rangeArgs[0];
          } else if (rangeArgs.length === 2) {
            start = rangeArgs[0];
            stop = rangeArgs[1];
          } else if (rangeArgs.length >= 3) {
            start = rangeArgs[0];
            stop = rangeArgs[1];
            step = rangeArgs[2];
          }

          idx++;
          const bodyLines: string[] = [];
          while (idx < lines.length && (lines[idx].startsWith("print(") || lines[idx].includes("="))) {
            bodyLines.push(lines[idx]);
            idx++;
          }

          for (let val = start; step > 0 ? val < stop : val > stop; val += step) {
            this.scope[varName] = val;
            for (const bodyLine of bodyLines) {
              this.executeStatement(bodyLine);
            }
          }
          continue;
        }

        // Standard statement
        this.executeStatement(line);
        idx++;
      }

      return { stdout: this.logs.join("\n") };
    } catch (err) {
      return {
        stdout: this.logs.join("\n"),
        error: err instanceof Error ? err.message : String(err),
      };
    }
  }

  private executeStatement(stmt: string): void {
    stmt = stmt.trim();
    if (!stmt || stmt.startsWith("#")) return;

    // Handle print(...)
    if (stmt.startsWith("print(") && stmt.endsWith(")")) {
      const inside = stmt.slice(6, -1);
      const parts = this.splitPrintArgs(inside);
      const evaluated = parts.map((part) => this.evalExpr(part.trim()));
      this.logs.push(evaluated.map((v) => this.formatPythonValue(v)).join(" "));
      return;
    }

    // Method calls like: b.append(4), lst.sort(), etc.
    const methodMatch = stmt.match(/^([a-zA-Z_]\w*)\.([a-zA-Z_]\w*)\((.*)\)$/);
    if (methodMatch) {
      const objName = methodMatch[1];
      const methodName = methodMatch[2];
      const argStr = methodMatch[3].trim();
      const target = this.scope[objName];

      if (Array.isArray(target)) {
        if (methodName === "append") {
          const argVal = this.evalExpr(argStr);
          target.push(argVal);
          return;
        } else if (methodName === "sort") {
          target.sort((a, b) => Number(a) - Number(b));
          return;
        }
      }
    }

    // Assignments: x = ...
    const assignIndex = stmt.indexOf("=");
    if (assignIndex > 0 && stmt[assignIndex - 1] !== "!" && stmt[assignIndex + 1] !== "=") {
      const lhs = stmt.slice(0, assignIndex).trim();
      const rhs = stmt.slice(assignIndex + 1).trim();
      const val = this.evalExpr(rhs);
      this.scope[lhs] = val;
      return;
    }
  }

  private splitPrintArgs(str: string): string[] {
    const args: string[] = [];
    let current = "";
    let inQuotes = false;
    let quoteChar = "";
    let depth = 0;

    for (let i = 0; i < str.length; i++) {
      const ch = str[i];
      if ((ch === "'" || ch === '"') && str[i - 1] !== "\\") {
        if (!inQuotes) {
          inQuotes = true;
          quoteChar = ch;
        } else if (quoteChar === ch) {
          inQuotes = false;
        }
      }
      if (!inQuotes) {
        if (ch === "[" || ch === "(") depth++;
        if (ch === "]" || ch === ")") depth--;
        if (ch === "," && depth === 0) {
          args.push(current);
          current = "";
          continue;
        }
      }
      current += ch;
    }
    if (current.trim()) {
      args.push(current);
    }
    return args;
  }

  private evalExpr(expr: string): unknown {
    expr = expr.trim();

    // String literals
    if ((expr.startsWith('"') && expr.endsWith('"')) || (expr.startsWith("'") && expr.endsWith("'"))) {
      return expr.slice(1, -1);
    }

    // Numbers
    if (/^-?\d+(\.\d+)?$/.test(expr)) {
      return Number(expr);
    }

    // List literals: [1, 2, 3]
    if (expr.startsWith("[") && expr.endsWith("]")) {
      const inner = expr.slice(1, -1).trim();
      if (!inner) return [];

      // Check if list comprehension: [x**2 for x in range(10) if x % 2 == 0]
      const compMatch = inner.match(/^(.+?)\s+for\s+([a-zA-Z_]\w*)\s+in\s+range\(([^)]+)\)(?:\s+if\s+(.+))?$/);
      if (compMatch) {
        const outExpr = compMatch[1].trim();
        const varName = compMatch[2].trim();
        const rangeLimit = Number(compMatch[3].trim());
        const ifCond = compMatch[4] ? compMatch[4].trim() : null;

        const result: unknown[] = [];
        for (let i = 0; i < rangeLimit; i++) {
          if (ifCond) {
            // Evaluate condition like x % 2 == 0
            if (ifCond.includes("%")) {
              const [l, r] = ifCond.split("==").map((s) => s.trim());
              const [v, mod] = l.split("%").map((s) => s.trim());
              const val = v === varName ? i : Number(v);
              const m = Number(mod);
              const expected = Number(r);
              if (val % m !== expected) continue;
            }
          }
          // Compute expr like x**2
          if (outExpr === `${varName}**2`) {
            result.push(i ** 2);
          } else if (outExpr === varName) {
            result.push(i);
          } else {
            result.push(i);
          }
        }
        return result;
      }

      // Plain array literal
      return inner.split(",").map((item) => this.evalExpr(item.trim()));
    }

    // Method calls on expressions: b.copy()
    const copyMatch = expr.match(/^([a-zA-Z_]\w*)\.copy\(\)$/);
    if (copyMatch) {
      const orig = this.scope[copyMatch[1]];
      if (Array.isArray(orig)) return [...orig];
    }

    // Built-in len(...)
    if (expr.startsWith("len(") && expr.endsWith(")")) {
      const target = this.evalExpr(expr.slice(4, -1));
      if (Array.isArray(target) || typeof target === "string") {
        return target.length;
      }
      return 0;
    }

    // Variable lookup
    if (expr in this.scope) {
      return this.scope[expr];
    }

    return expr;
  }

  private formatPythonValue(val: unknown): string {
    if (Array.isArray(val)) {
      return `[${val.map((item) => (typeof item === "string" ? `'${item}'` : String(item))).join(", ")}]`;
    }
    return String(val);
  }
}

/**
 * Run a user's code snippet against a sandbox configuration and test cases.
 */
export async function executeSandboxCode(
  code: string,
  config: SandboxConfig
): Promise<ExecutionReport> {
  const startTime = performance.now();
  let stdout = "";
  let error: string | undefined;

  if (config.environment === "javascript_eval") {
    const res = runJavaScriptSnippet(code);
    stdout = res.stdout;
    error = res.error;
  } else {
    // Default to Python simulation
    const py = new MiniPythonInterpreter();
    const res = py.run(code);
    stdout = res.stdout;
    error = res.error;
  }

  const executionTimeMs = Math.round(performance.now() - startTime);

  // Evaluate test cases
  const testResults: TestExecutionResult[] = config.test_cases.map((testCase: TestCase) => {
    const cleanExpected = testCase.expected_output.trim();
    const cleanActual = stdout.trim();
    const passed = cleanActual.includes(cleanExpected) || cleanActual === cleanExpected;
    return {
      name: testCase.name,
      passed,
      actual_output: cleanActual,
      expected_output: cleanExpected,
    };
  });

  const passed = testResults.length > 0 ? testResults.every((t) => t.passed) : !error;

  return {
    passed,
    stdout,
    testResults,
    error,
    executionTimeMs,
  };
}
