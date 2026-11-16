import React, { useState } from "react";

interface ContextPanelProps {
  notes: string;
  chapters: string;
  onNotesChange: (notes: string) => void;
  onChaptersChange: (chapters: string) => void;
}

const MAX_NOTES_BYTES = 100 * 1024; // 100 KB

export const ContextPanel: React.FC<ContextPanelProps> = ({
  notes,
  chapters,
  onNotesChange,
  onChaptersChange,
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const contextBytes = new TextEncoder().encode(`${notes}${chapters}`).length;
  const isContextOverLimit = contextBytes > MAX_NOTES_BYTES;

  return (
    <div
      className="context-panel"
      data-testid="context-panel"
      style={{
        border: "1px solid #334155",
        borderRadius: "8px",
        padding: "12px",
        marginTop: "12px",
        background: "#0f172a",
      }}
    >
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        style={{
          background: "none",
          border: "none",
          color: "#38bdf8",
          fontSize: "0.95rem",
          fontWeight: 600,
          cursor: "pointer",
          padding: 0,
          display: "flex",
          alignItems: "center",
          gap: "8px",
        }}
        data-testid="toggle-context-panel"
      >
        <span>{isOpen ? "▼" : "▶"}</span>
        <span>Creator Context (Optional Slide Notes & Chapters)</span>
      </button>

      {isOpen && (
        <div style={{ marginTop: "12px", display: "flex", flexDirection: "column", gap: "12px" }}>
          <p style={{ margin: 0, fontSize: "0.85rem", color: "#94a3b8" }}>
            Add slide text, lecture notes, or chapter markers to anchor concepts during silent, code-heavy, or math-heavy segments.
          </p>

          <div>
            <label style={{ display: "block", fontSize: "0.85rem", color: "#e2e8f0", marginBottom: "4px" }}>
              Lecture Notes / Slide Text (Plain text or Markdown; notes and chapters share a 100 KB limit)
            </label>
            <textarea
              rows={4}
              value={notes}
              onChange={(e) => onNotesChange(e.target.value)}
              placeholder="Paste slide outlines, syllabus points, or lecture script..."
              style={{
                width: "100%",
                boxSizing: "border-box",
                padding: "8px",
                borderRadius: "4px",
                background: "#1e293b",
                color: "#f8fafc",
                border: isContextOverLimit ? "1px solid #ef4444" : "1px solid #475569",
              }}
              data-testid="input-notes"
            />
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.75rem", marginTop: "2px" }}>
              <span style={{ color: isContextOverLimit ? "#ef4444" : "#94a3b8" }}>
                {(contextBytes / 1024).toFixed(1)} KB / 100 KB
              </span>
              {isContextOverLimit && (
                <span style={{ color: "#ef4444" }} data-testid="notes-error">
                  Creator context exceeds 100 KB limit
                </span>
              )}
            </div>
          </div>

          <div>
            <label style={{ display: "block", fontSize: "0.85rem", color: "#e2e8f0", marginBottom: "4px" }}>
              Chapters (Lines formatted as MM:SS Title or H:MM:SS Title)
            </label>
            <textarea
              rows={3}
              value={chapters}
              onChange={(e) => onChaptersChange(e.target.value)}
              placeholder={"00:00 Introduction\n04:30 Recursive Step\n12:15 Base Case Demonstration"}
              style={{
                width: "100%",
                boxSizing: "border-box",
                padding: "8px",
                borderRadius: "4px",
                background: "#1e293b",
                color: "#f8fafc",
                border: "1px solid #475569",
              }}
              data-testid="input-chapters"
            />
          </div>
        </div>
      )}
    </div>
  );
};
