import React, { useState } from "react";
import type { Intervention } from "../types";

export interface ReviewIntervention extends Intervention {
  confidence?: "high" | "medium" | "low" | null;
  review_state?: "auto" | "needs_review" | "approved" | null;
  evidence?: Array<{ source: string; ref?: string | null; quote?: string | null }>;
}

interface ReviewListProps {
  lectureId: string;
  creatorToken: string;
  checkpoints: ReviewIntervention[];
  onApproveOne: (checkpointId: string) => Promise<void>;
  onApproveAllFlagged: () => Promise<void>;
}

export const ReviewList: React.FC<ReviewListProps> = ({
  checkpoints,
  onApproveOne,
  onApproveAllFlagged,
}) => {
  const [filterNeedsReview, setFilterNeedsReview] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [busyAll, setBusyAll] = useState(false);

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs < 10 ? "0" : ""}${secs}`;
  };

  const sortedCheckpoints = [...checkpoints].sort((a, b) => a.trigger_time - b.trigger_time);
  const displayedCheckpoints = filterNeedsReview
    ? sortedCheckpoints.filter((c) => c.review_state === "needs_review")
    : sortedCheckpoints;

  const needsReviewCount = sortedCheckpoints.filter((c) => c.review_state === "needs_review").length;

  const handleApprove = async (id: string) => {
    setBusyId(id);
    try {
      await onApproveOne(id);
    } finally {
      setBusyId(null);
    }
  };

  const handleApproveAll = async () => {
    setBusyAll(true);
    try {
      await onApproveAllFlagged();
    } finally {
      setBusyAll(false);
    }
  };

  return (
    <div className="review-list" data-testid="review-list" style={{ marginTop: "16px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
        <div>
          <h3 style={{ margin: 0, fontSize: "1.1rem", color: "#f8fafc" }}>Generated Checkpoints Review</h3>
          <p style={{ margin: "4px 0 0 0", fontSize: "0.85rem", color: "#94a3b8" }}>
            High-confidence checkpoints auto-publish. Medium-confidence checkpoints are hidden from students until approved.
          </p>
        </div>

        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          <label style={{ fontSize: "0.85rem", color: "#cbd5e1", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={filterNeedsReview}
              onChange={(e) => setFilterNeedsReview(e.target.checked)}
              data-testid="filter-needs-review"
            />
            {" "}Show only needs review ({needsReviewCount})
          </label>
          {needsReviewCount > 0 && (
            <button
              type="button"
              onClick={handleApproveAll}
              disabled={busyAll}
              style={{
                background: "#059669",
                color: "#ffffff",
                border: "none",
                padding: "6px 12px",
                borderRadius: "4px",
                cursor: "pointer",
                fontSize: "0.85rem",
              }}
              data-testid="btn-approve-all"
            >
              {busyAll ? "Approving..." : "Approve all flagged"}
            </button>
          )}
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
        {displayedCheckpoints.map((cp) => {
          const isNeedsReview = cp.review_state === "needs_review";
          return (
            <div
              key={cp.id}
              data-testid={`checkpoint-row-${cp.id}`}
              style={{
                border: isNeedsReview ? "1px solid #eab308" : "1px solid #334155",
                borderRadius: "6px",
                padding: "12px",
                background: isNeedsReview ? "#1e1b07" : "#0f172a",
                display: "flex",
                flexDirection: "column",
                gap: "6px",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <span style={{ fontWeight: "bold", color: "#38bdf8", fontSize: "0.9rem" }}>
                    {formatTime(cp.trigger_time)}
                  </span>
                  <span
                    style={{
                      fontSize: "0.75rem",
                      padding: "2px 6px",
                      borderRadius: "4px",
                      background: cp.confidence === "high" ? "#065f46" : "#854d0e",
                      color: "#f8fafc",
                    }}
                    data-testid={`badge-confidence-${cp.id}`}
                  >
                    {cp.confidence ? `${cp.confidence} confidence` : "standard"}
                  </span>
                  <span
                    style={{
                      fontSize: "0.75rem",
                      padding: "2px 6px",
                      borderRadius: "4px",
                      background:
                        cp.review_state === "approved"
                          ? "#0284c7"
                          : isNeedsReview
                          ? "#ca8a04"
                          : "#334155",
                      color: "#f8fafc",
                    }}
                    data-testid={`badge-state-${cp.id}`}
                  >
                    {cp.review_state || "auto"}
                  </span>
                </div>

                {isNeedsReview && (
                  <button
                    type="button"
                    onClick={() => handleApprove(cp.id)}
                    disabled={busyId === cp.id}
                    style={{
                      background: "#10b981",
                      color: "#ffffff",
                      border: "none",
                      padding: "4px 10px",
                      borderRadius: "4px",
                      cursor: "pointer",
                      fontSize: "0.8rem",
                    }}
                    data-testid={`btn-approve-${cp.id}`}
                  >
                    {busyId === cp.id ? "Approving..." : "Approve"}
                  </button>
                )}
              </div>

              <div style={{ fontSize: "0.9rem", color: "#f1f5f9" }}>{cp.question}</div>

              {cp.evidence && cp.evidence.length > 0 && (
                <div style={{ fontSize: "0.8rem", color: "#94a3b8", display: "flex", flexDirection: "column", gap: "2px" }}>
                  {cp.evidence.map((ev, i) => (
                    <div key={i}>
                      <strong style={{ color: "#cbd5e1" }}>[{ev.source}]</strong>{" "}
                      {ev.quote ? `"${ev.quote}"` : ev.ref}
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
