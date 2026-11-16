import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PreflightReport, type PreflightReportData } from "./PreflightReport";
import { ContextPanel } from "./ContextPanel";
import { ReviewList, type ReviewIntervention } from "./ReviewList";
import {
  calculateVisualAnalysisCost,
  mergeAndPadSpans,
  type WeakSpan,
} from "./visualAnalysis";

describe("P1.5 Studio Components", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  describe("PreflightReport", () => {
    const mockReport: PreflightReportData = {
      windows: [
        { start_s: 0, end_s: 30, words: 45, coverage: 0.8, verdict: "strong" },
        { start_s: 30, end_s: 60, words: 5, coverage: 0.1, verdict: "weak" },
      ],
      speech_coverage: 0.45,
      longest_silent_stretch_s: 25,
      weak_windows: [{ start_s: 30, end_s: 60 }],
      suitability: "mixed",
      message: "Some stretches have low narration.",
    };

    it("renders suitability badge and colored timeline strip", () => {
      render(<PreflightReport report={mockReport} />);
      expect(screen.getByTestId("suitability-badge")).toHaveTextContent("mixed");
      expect(screen.getByTestId("preflight-message")).toHaveTextContent("Some stretches have low narration.");
      const strip = screen.getByTestId("timeline-strip");
      expect(strip.children.length).toBe(2);
    });

    it("displays visual analysis button for weak/mixed report when enabled", () => {
      const onRun = vi.fn();
      render(
        <PreflightReport
          report={mockReport}
          canRunVisualAnalysis={true}
          onRunVisualAnalysis={onRun}
        />
      );
      const btn = screen.getByTestId("btn-visual-analysis");
      fireEvent.click(btn);
      expect(onRun).toHaveBeenCalled();
    });
  });

  describe("ContextPanel", () => {
    it("toggles panel and respects 100 KB limit warnings", () => {
      const onNotes = vi.fn();
      const onChapters = vi.fn();
      render(
        <ContextPanel
          notes="Some initial notes"
          chapters="00:00 Intro"
          onNotesChange={onNotes}
          onChaptersChange={onChapters}
        />
      );

      // Initially closed
      expect(screen.queryByTestId("input-notes")).not.toBeInTheDocument();

      // Toggle open
      fireEvent.click(screen.getByTestId("toggle-context-panel"));
      expect(screen.getByTestId("input-notes")).toBeInTheDocument();
      expect(screen.getByTestId("input-chapters")).toBeInTheDocument();

      // Over limit test
      const largeText = "x".repeat(101 * 1024);
      const { rerender } = render(
        <ContextPanel
          notes={largeText}
          chapters=""
          onNotesChange={onNotes}
          onChaptersChange={onChapters}
        />
      );
      fireEvent.click(screen.getAllByTestId("toggle-context-panel")[1]);
      expect(screen.getByTestId("notes-error")).toBeInTheDocument();
    });
  });

  describe("visualAnalysis helpers", () => {
    it("merges adjacent weak spans and calculates cost", () => {
      const spans: WeakSpan[] = [
        { start_s: 30, end_s: 60 },
        { start_s: 62, end_s: 90 }, // within padding
      ];
      const merged = mergeAndPadSpans(spans, 5.0);
      expect(merged.length).toBe(1);
      expect(merged[0].start_s).toBe(25);
      expect(merged[0].end_s).toBe(95);

      const cost = calculateVisualAnalysisCost(spans);
      expect(cost.totalMinutes).toBe(2);
      expect(cost.estimatedCostUsd).toBe(0.004);
    });
  });

  describe("ReviewList", () => {
    const mockCheckpoints: ReviewIntervention[] = [
      {
        id: "chk_1",
        trigger_time: 120,
        concept: "Base Case",
        difficulty: "Medium",
        type: "single_choice",
        question: "What is a base case?",
        options: [{ id: "opt_a", text: "Termination" }],
        correct_feedback: "Right",
        incorrect_feedback: "Wrong",
        confidence: "high",
        review_state: "auto",
        evidence: [{ source: "transcript", quote: "a base case is required" }],
      },
      {
        id: "chk_2",
        trigger_time: 240,
        concept: "Stack Overflow",
        difficulty: "Hard",
        type: "single_choice",
        question: "Why does infinite recursion crash?",
        options: [{ id: "opt_a", text: "Stack exhaust" }],
        correct_feedback: "Right",
        incorrect_feedback: "Wrong",
        confidence: "medium",
        review_state: "needs_review",
        evidence: [{ source: "visual", ref: "v_001" }],
      },
    ];

    it("renders checkpoints with confidence badges and supports filtering and approval", async () => {
      const onApproveOne = vi.fn().mockResolvedValue(undefined);
      const onApproveAll = vi.fn().mockResolvedValue(undefined);

      render(
        <ReviewList
          lectureId="lec_123"
          creatorToken="token"
          checkpoints={mockCheckpoints}
          onApproveOne={onApproveOne}
          onApproveAllFlagged={onApproveAll}
        />
      );

      expect(screen.getByTestId("checkpoint-row-chk_1")).toBeInTheDocument();
      expect(screen.getByTestId("checkpoint-row-chk_2")).toBeInTheDocument();
      expect(screen.getByTestId("badge-confidence-chk_1")).toHaveTextContent("high confidence");
      expect(screen.getByTestId("badge-confidence-chk_2")).toHaveTextContent("medium confidence");

      // Approve single
      const approveBtn = screen.getByTestId("btn-approve-chk_2");
      fireEvent.click(approveBtn);
      expect(onApproveOne).toHaveBeenCalledWith("chk_2");

      // Approve all flagged
      const approveAllBtn = screen.getByTestId("btn-approve-all");
      fireEvent.click(approveAllBtn);
      expect(onApproveAll).toHaveBeenCalled();

      // Filter needs review
      const filter = screen.getByTestId("filter-needs-review");
      fireEvent.click(filter);
      expect(screen.queryByTestId("checkpoint-row-chk_1")).not.toBeInTheDocument();
      expect(screen.getByTestId("checkpoint-row-chk_2")).toBeInTheDocument();
    });
  });
});
