import React, { useEffect, useState } from "react";
import { executeSandboxCode, type ExecutionReport } from "../sandbox/CodeRunner";
import type {
  ActiveInterventionPayload,
  EvaluationResult,
  InquiryExperimentSubmission,
  SandboxConfig,
} from "../types";

interface Props {
  intervention: ActiveInterventionPayload;
  onSubmit: (answer: string | string[]) => Promise<EvaluationResult>;
  onSubmitExperiment?: (submission: InquiryExperimentSubmission) => Promise<EvaluationResult>;
  onFeedbackComplete: () => void;
}

export default function InterventionOverlay({
  intervention,
  onSubmit,
  onSubmitExperiment,
  onFeedbackComplete,
}: Props) {
  const isInquiry =
    intervention.type === "predict_and_verify" || intervention.type === "inquiry_sandbox";

  // MCQ state
  const [selectedSingle, setSelectedSingle] = useState<string>("");
  const [selectedMultiple, setSelectedMultiple] = useState<string[]>([]);

  // Inquiry state
  const [inquiryStep, setInquiryStep] = useState<"hypothesis" | "experiment">("hypothesis");
  const [selectedHypothesis, setSelectedHypothesis] = useState<string>("");
  const [code, setCode] = useState<string>(
    intervention.sandbox_config?.initial_code ?? ""
  );
  const [isRunningCode, setIsRunningCode] = useState<boolean>(false);
  const [executionReport, setExecutionReport] = useState<ExecutionReport | null>(null);
  const [showHints, setShowHints] = useState<boolean>(false);

  // Common state
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [evaluationResult, setEvaluationResult] = useState<EvaluationResult | null>(null);
  const [countdown, setCountdown] = useState<number>(4);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const isSingleChoice = intervention.type === "single_choice";
  const hasMcqSelection = isSingleChoice
    ? selectedSingle.length > 0
    : selectedMultiple.length > 0;

  const handleToggleMultiple = (optionId: string) => {
    if (evaluationResult || isSubmitting) return;
    setSelectedMultiple((prev) =>
      prev.includes(optionId) ? prev.filter((id) => id !== optionId) : [...prev, optionId]
    );
  };

  const handleMcqSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!hasMcqSelection || isSubmitting || evaluationResult) return;

    setIsSubmitting(true);
    setSubmitError(null);
    const answer = isSingleChoice ? selectedSingle : selectedMultiple;

    try {
      const result = await onSubmit(answer);
      setEvaluationResult(result);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Submission failed.");
    } finally {
      setIsSubmitting(false);
    }
  };

  // Inquiry: Run code in sandboxed runner
  const handleRunCode = async () => {
    if (!intervention.sandbox_config) return;
    setIsRunningCode(true);
    try {
      const report = await executeSandboxCode(code, intervention.sandbox_config);
      setExecutionReport(report);
    } catch (err) {
      setExecutionReport({
        passed: false,
        stdout: "",
        testResults: [],
        error: err instanceof Error ? err.message : String(err),
        executionTimeMs: 0,
      });
    } finally {
      setIsRunningCode(false);
    }
  };

  // Inquiry: Final submission of experiment
  const handleInquirySubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isSubmitting || evaluationResult) return;

    setIsSubmitting(true);
    setSubmitError(null);

    const submission: InquiryExperimentSubmission = {
      intervention_id: intervention.id,
      idempotency_key: `inq_sub_${intervention.id}_${Date.now()}`,
      hypothesis_answer: selectedHypothesis || null,
      code_submitted: code,
      test_results: executionReport?.testResults ?? [],
      passed_tests: executionReport?.passed ?? false,
    };

    try {
      let result: EvaluationResult;
      if (onSubmitExperiment) {
        result = await onSubmitExperiment(submission);
      } else {
        result = await onSubmit(selectedHypothesis || "experiment_done");
      }
      setEvaluationResult(result);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Experiment submission failed.");
    } finally {
      setIsSubmitting(false);
    }
  };

  // Feedback display timer countdown
  useEffect(() => {
    if (!evaluationResult) return;

    setCountdown(4);
    const timer = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          clearInterval(timer);
          onFeedbackComplete();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [evaluationResult, onFeedbackComplete]);

  // Hypothesis options to display
  const hypothesisOptions =
    intervention.hypothesis_options && intervention.hypothesis_options.length > 0
      ? intervention.hypothesis_options
      : intervention.options;

  const tierBadgeLabel = intervention.tier ? `Tier ${intervention.tier}` : null;

  return (
    <div className="intervention-overlay-backdrop" role="dialog" aria-modal="true">
      <div className={`intervention-card ${isInquiry ? "inquiry-card" : ""}`}>
        <div className="intervention-header">
          <span className="badge concept-badge">{intervention.concept}</span>
          <span className={`badge difficulty-badge ${intervention.difficulty.toLowerCase()}`}>
            {intervention.difficulty}
          </span>
          {tierBadgeLabel && (
            <span className="badge tier-badge">{tierBadgeLabel}</span>
          )}
          <span className="badge type-badge">
            {isInquiry
              ? intervention.type === "predict_and_verify"
                ? "Predict & Verify"
                : "Inquiry Sandbox"
              : isSingleChoice
              ? "Single Choice"
              : "Multiple Selection"}
          </span>
        </div>

        <h3 className="question-text">{intervention.question}</h3>

        {/* FEEDBACK STATE */}
        {evaluationResult ? (
          <div
            className={`feedback-box ${
              evaluationResult.is_correct ? "feedback-correct" : "feedback-incorrect"
            }`}
          >
            <h4>
              {evaluationResult.is_correct
                ? isInquiry
                  ? "✓ Verified & Correct!"
                  : "✓ Correct!"
                : "✗ Incorrect"}
            </h4>
            <p className="feedback-text">{evaluationResult.feedback}</p>
            {evaluationResult.mastery_delta !== undefined && evaluationResult.mastery_delta !== 0 && (
              <div className="feedback-meta">
                <span className="mastery-badge">
                  Mastery Delta: {evaluationResult.mastery_delta > 0 ? "+" : ""}
                  {(evaluationResult.mastery_delta * 100).toFixed(0)}%
                </span>
                {evaluationResult.suggested_next_tier && (
                  <span className="suggested-tier-badge">
                    Next Recommended Tier: {evaluationResult.suggested_next_tier}
                  </span>
                )}
              </div>
            )}
            <p className="countdown-text">Resuming video in {countdown}s...</p>
          </div>
        ) : isInquiry ? (
          /* INQUIRY SANDBOX WORKFLOW */
          <div className="inquiry-container">
            <div className="inquiry-progress-tabs">
              <button
                type="button"
                className={`tab-btn ${inquiryStep === "hypothesis" ? "active" : ""}`}
                onClick={() => setInquiryStep("hypothesis")}
              >
                1. Observe & Hypothesize
              </button>
              <button
                type="button"
                className={`tab-btn ${inquiryStep === "experiment" ? "active" : ""}`}
                onClick={() => setInquiryStep("experiment")}
              >
                2. Experiment & Verify
              </button>
            </div>

            {inquiryStep === "hypothesis" ? (
              <div className="hypothesis-step">
                <p className="step-prompt">
                  {intervention.hypothesis_prompt ||
                    "Formulate a hypothesis: What do you predict will happen?"}
                </p>

                {intervention.sandbox_config?.initial_code && (
                  <div className="code-preview-block">
                    <span className="code-label">Code to observe:</span>
                    <pre className="code-preview">
                      <code>{intervention.sandbox_config.initial_code}</code>
                    </pre>
                  </div>
                )}

                <div className="options-list">
                  {hypothesisOptions.map((opt) => (
                    <label
                      key={opt.id}
                      className={`option-item ${selectedHypothesis === opt.id ? "selected" : ""}`}
                    >
                      <input
                        type="radio"
                        name="hypothesis-choice"
                        value={opt.id}
                        checked={selectedHypothesis === opt.id}
                        onChange={() => setSelectedHypothesis(opt.id)}
                      />
                      <span className="option-text">{opt.text}</span>
                    </label>
                  ))}
                </div>

                <div className="inquiry-actions">
                  <button
                    type="button"
                    className="submit-button"
                    disabled={!selectedHypothesis}
                    onClick={() => setInquiryStep("experiment")}
                  >
                    Lock Hypothesis & Proceed to Experiment →
                  </button>
                </div>
              </div>
            ) : (
              <form onSubmit={handleInquirySubmit} className="experiment-step">
                <div className="sandbox-workspace">
                  <div className="editor-panel">
                    <div className="panel-header">
                      <span>Python Sandbox</span>
                      <button
                        type="button"
                        className="hint-toggle-btn"
                        onClick={() => setShowHints((prev) => !prev)}
                      >
                        {showHints ? "Hide Hints" : "Need a Hint?"}
                      </button>
                    </div>

                    {showHints && intervention.sandbox_config?.hints && (
                      <ul className="hints-list">
                        {intervention.sandbox_config.hints.map((h, i) => (
                          <li key={i}>{h}</li>
                        ))}
                      </ul>
                    )}

                    <textarea
                      className="code-editor"
                      rows={8}
                      value={code}
                      onChange={(e) => setCode(e.target.value)}
                      spellCheck={false}
                    />

                    <div className="editor-actions">
                      <button
                        type="button"
                        className="run-code-button"
                        onClick={handleRunCode}
                        disabled={isRunningCode}
                      >
                        {isRunningCode ? "Running..." : "▶ Run Experiment"}
                      </button>
                    </div>
                  </div>

                  <div className="terminal-panel">
                    <div className="panel-header">
                      <span>Console Output & Test Verification</span>
                    </div>

                    <pre className="terminal-output">
                      {executionReport
                        ? executionReport.error
                          ? `Error: ${executionReport.error}\n${executionReport.stdout}`
                          : executionReport.stdout || "(No output printed)"
                        : "Click 'Run Experiment' to execute your code."}
                    </pre>

                    {executionReport && executionReport.testResults.length > 0 && (
                      <div className="test-results-block">
                        <span className="test-header">Verification Checks:</span>
                        {executionReport.testResults.map((t, idx) => (
                          <div
                            key={idx}
                            className={`test-case-row ${t.passed ? "passed" : "failed"}`}
                          >
                            <span>{t.passed ? "✓" : "✗"} {t.name}</span>
                            <span className="test-badge">{t.passed ? "PASSED" : "FAILED"}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>

                {submitError && <p className="error-message">{submitError}</p>}

                <div className="inquiry-actions">
                  <button
                    type="button"
                    className="secondary-btn"
                    onClick={() => setInquiryStep("hypothesis")}
                  >
                    ← Review Hypothesis
                  </button>
                  <button
                    type="submit"
                    className="submit-button"
                    disabled={isSubmitting}
                  >
                    {isSubmitting ? "Evaluating Conclusion..." : "Submit Conclusion & Verify"}
                  </button>
                </div>
              </form>
            )}
          </div>
        ) : (
          /* TRADITIONAL MCQ OPTIONS FORM */
          <form onSubmit={handleMcqSubmit} className="options-form">
            <div className="options-list">
              {intervention.options.map((option) => {
                const isSelected = isSingleChoice
                  ? selectedSingle === option.id
                  : selectedMultiple.includes(option.id);

                return (
                  <label
                    key={option.id}
                    className={`option-item ${isSelected ? "selected" : ""}`}
                  >
                    <input
                      type={isSingleChoice ? "radio" : "checkbox"}
                      name={`intervention-option-${intervention.id}`}
                      value={option.id}
                      checked={isSelected}
                      disabled={isSubmitting}
                      onChange={() => {
                        if (isSingleChoice) {
                          setSelectedSingle(option.id);
                        } else {
                          handleToggleMultiple(option.id);
                        }
                      }}
                    />
                    <span className="option-text">{option.text}</span>
                  </label>
                );
              })}
            </div>

            {submitError && <p className="error-message">{submitError}</p>}

            <button
              type="submit"
              className="submit-button"
              disabled={!hasMcqSelection || isSubmitting}
            >
              {isSubmitting ? "Evaluating..." : "Submit Answer"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
