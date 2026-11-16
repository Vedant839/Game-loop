import React from "react";

export interface WindowReport {
  start_s: number;
  end_s: number;
  words: number;
  coverage: number;
  verdict: "strong" | "weak";
}

export interface WeakSpan {
  start_s: number;
  end_s: number;
}

export interface PreflightReportData {
  windows: WindowReport[];
  speech_coverage: number;
  longest_silent_stretch_s: number;
  weak_windows: WeakSpan[];
  suitability: "good" | "mixed" | "limited" | "unknown";
  message: string;
}

interface PreflightReportProps {
  report: PreflightReportData;
  onRunVisualAnalysis?: () => void;
  canRunVisualAnalysis?: boolean;
}

export const PreflightReport: React.FC<PreflightReportProps> = ({
  report,
  onRunVisualAnalysis,
  canRunVisualAnalysis = false,
}) => {
  const coveragePercent = Math.round(report.speech_coverage * 100);
  const isWeak = report.suitability === "mixed" || report.suitability === "limited";

  return (
    <div className="preflight-report" data-testid="preflight-report" style={{ border: "1px solid #334155", borderRadius: "8px", padding: "16px", marginTop: "12px", background: "#0f172a" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
        <h3 style={{ margin: 0, fontSize: "1rem", color: "#f8fafc" }}>Transcript Preflight Quality</h3>
        <span
          data-testid="suitability-badge"
          style={{
            padding: "2px 8px",
            borderRadius: "4px",
            fontSize: "0.85rem",
            fontWeight: "bold",
            textTransform: "uppercase",
            background:
              report.suitability === "good"
                ? "#065f46"
                : report.suitability === "mixed"
                ? "#854d0e"
                : "#7f1d1d",
            color: "#f8fafc",
          }}
        >
          {report.suitability}
        </span>
      </div>

      <p style={{ margin: "4px 0 12px 0", fontSize: "0.9rem", color: "#cbd5e1" }} data-testid="preflight-message">
        {report.message}
      </p>

      {/* Timeline Strip */}
      <div
        className="timeline-strip"
        data-testid="timeline-strip"
        style={{
          display: "flex",
          height: "18px",
          borderRadius: "4px",
          overflow: "hidden",
          background: "#1e293b",
          marginBottom: "12px",
        }}
      >
        {report.windows.map((win, idx) => (
          <div
            key={idx}
            className={`timeline-window ${win.verdict}`}
            title={`${win.start_s}s - ${win.end_s}s (${win.verdict}, ${win.words} words)`}
            style={{
              flex: 1,
              backgroundColor: win.verdict === "strong" ? "#10b981" : "#f59e0b",
              borderRight: "1px solid #0f172a",
            }}
          />
        ))}
      </div>

      <div style={{ display: "flex", gap: "16px", fontSize: "0.85rem", color: "#94a3b8" }}>
        <span>Speech Coverage: <strong>{coveragePercent}%</strong></span>
        <span>Weak Windows: <strong>{report.weak_windows.length}</strong></span>
        <span>Longest Silence: <strong>{Math.round(report.longest_silent_stretch_s)}s</strong></span>
      </div>

      {isWeak && canRunVisualAnalysis && onRunVisualAnalysis && (
        <div style={{ marginTop: "12px", paddingTop: "8px", borderTop: "1px solid #1e293b" }}>
          <button
            type="button"
            onClick={onRunVisualAnalysis}
            style={{
              background: "#3b82f6",
              color: "#ffffff",
              border: "none",
              padding: "6px 12px",
              borderRadius: "4px",
              cursor: "pointer",
              fontSize: "0.85rem",
            }}
            data-testid="btn-visual-analysis"
          >
            Analyze weak sections with video
          </button>
        </div>
      )}
    </div>
  );
};
