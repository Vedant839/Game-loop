import React, { useEffect, useState } from "react";
import { executeSandboxCode, type ExecutionReport } from "../sandbox/CodeRunner";
import type {
  ActiveInterventionPayload,
  EvaluationResult,
  InquiryExperimentSubmission,
  OpenEndedSubmissionResponse,
  SandboxConfig,
} from "../types";

interface Props {
  intervention: ActiveInterventionPayload;
  onSubmit: (answer: string | string[]) => Promise<EvaluationResult>;
  onSubmitExperiment?: (submission: InquiryExperimentSubmission) => Promise<EvaluationResult>;
  onSubmitOpenEnded?: (answer: string) => Promise<OpenEndedSubmissionResponse>;
  onSelfAssess?: (submissionId: string, correct: boolean) => Promise<void>;
  onSkip?: () => Promise<void>;
  onFeedbackComplete: () => void;
}

export default function InterventionOverlay({
  intervention,
  onSubmit,
  onSubmitExperiment,
  onSubmitOpenEnded,
  onSelfAssess,
  onSkip,
  onFeedbackComplete,
}: Props) {
  const isInquiry =
    intervention.type === "predict_and_verify" || intervention.type === "inquiry_sandbox";
  const isOpenEnded = intervention.type === "open_ended";

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

  // Open-ended state
  const [openEndedText, setOpenEndedText] = useState<string>("");
  const [isEvaluatingOpenEnded, setIsEvaluatingOpenEnded] = useState<boolean>(false);
  const [openEndedResponse, setOpenEndedResponse] = useState<OpenEndedSubmissionResponse | null>(null);
  const [isSelfAssessing, setIsSelfAssessing] = useState<boolean>(false);

  // Common state
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [isSkipping, setIsSkipping] = useState<boolean>(false);
  const [evaluationResult, setEvaluationResult] = useState<EvaluationResult | null>(null);
  const [countdown, setCountdown] = useState<number>(4);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const policy = intervention.policy ?? "skippable";
  const isSkippable = policy === "skippable";
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

  const handleSkip = async () => {
    if (!onSkip || isSkipping || isSubmitting) return;
    setIsSkipping(true);
    setSubmitError(null);
    try {
      await onSkip();
      onFeedbackComplete();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to skip.");
      setIsSkipping(false);
    }
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

  const handleOpenEndedSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!openEndedText.trim() || isSubmitting || evaluationResult) return;

    setIsSubmitting(true);
    setSubmitError(null);

    try {
      if (onSubmitOpenEnded) {
        setIsEvaluatingOpenEnded(true);
        const resp = await onSubmitOpenEnded(openEndedText);
        setOpenEndedResponse(resp);

        if (resp.resumption_policy === "immediate_optimistic") {
          setEvaluationResult({
            is_correct: resp.is_correct ?? true,
            feedback: resp.formative_feedback ?? "Your conceptual explanation has been recorded and is being evaluated.",
            submitted_answer: openEndedText,
            session_state: resp.session_state ?? intervention.session_state,
          });
          setIsEvaluatingOpenEnded(false);
        } else {
          // wait_for_result
          if (resp.status === "completed") {
            setEvaluationResult({
              is_correct: resp.is_correct ?? true,
              feedback: resp.formative_feedback ?? "Evaluation complete.",
              submitted_answer: openEndedText,
              session_state: resp.session_state ?? intervention.session_state,
            });
            setIsEvaluatingOpenEnded(false);
          } else {
            // Wait up to 5 seconds before offering self-assessment fallback
            setTimeout(() => {
              setIsSelfAssessing(true);
              setIsEvaluatingOpenEnded(false);
            }, 5000);
          }
        }
      } else {
        const result = await onSubmit(openEndedText);
        setEvaluationResult(result);
      }
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Submission failed.");
      setIsEvaluatingOpenEnded(false);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSelfAssessClick = async (correct: boolean) => {
    if (!openEndedResponse || !onSelfAssess) return;
    setIsSubmitting(true);
    try {
      await onSelfAssess(openEndedResponse.submission_id, correct);
      setEvaluationResult({
        is_correct: correct,
        feedback: correct
          ? "Self-assessment recorded. Verified alignment with reference rubric."
          : "Self-assessment recorded. Core misconceptions identified for revision.",
        submitted_answer: openEndedText,
        session_state: intervention.session_state,
      });
      setIsSelfAssessing(false);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Self-assessment failed.");
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
          <span className={`policy-badge ${policy}`}>
            {isSkippable ? "Skippable" : "Required"}
          </span>
          <span className="badge type-badge">
            {isInquiry
              ? intervention.type === "predict_and_verify"
                ? "Predict & Verify"
                : "Inquiry Sandbox"
              : isOpenEnded
              ? "Open-Ended Reasoning"
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
        ) : isOpenEnded ? (
          /* OPEN-ENDED REASONING / PROOFS WORKFLOW */
          <div className="open-ended-container">
            {isEvaluatingOpenEnded ? (
              <div className="evaluating-card">
                <div className="evaluating-spinner" />
                <h4>Evaluating your conceptual reasoning...</h4>
                <p className="feedback-text">
                  Our pedagogical evaluator is analyzing your explanation against key rubric concepts.
                </p>
              </div>
            ) : isSelfAssessing ? (
              <div className="self-assess-card">
                <h4>Self-Assessment: Reference Rubric</h4>
                <p className="feedback-text">
                  Compare your response with the expert rubric below:
                </p>
                <div className="rubric-reference">
                  <h5>Reference Explanation</h5>
                  <p>
                    {intervention.rubric?.reference_answer ||
                      "Rotating 180 degrees around the midpoint of the transversal segment maps alternate interior angles directly onto each other."}
                  </p>
                  {intervention.rubric?.key_concepts && intervention.rubric.key_concepts.length > 0 && (
                    <div className="key-concepts-list">
                      {intervention.rubric.key_concepts.map((concept) => (
                        <span key={concept} className="concept-pill">
                          {concept}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <p style={{ fontSize: "0.85rem", color: "var(--text-muted)", margin: "0.5rem 0" }}>
                  Did your response explain these core mathematical concepts?
                </p>
                <div className="self-assess-buttons">
                  <button
                    type="button"
                    className="self-assess-pass-btn"
                    onClick={() => handleSelfAssessClick(true)}
                    disabled={isSubmitting}
                  >
                    ✓ Covered Key Concepts
                  </button>
                  <button
                    type="button"
                    className="self-assess-fail-btn"
                    onClick={() => handleSelfAssessClick(false)}
                    disabled={isSubmitting}
                  >
                    ✗ Missed Key Concepts
                  </button>
                </div>
              </div>
            ) : (
              <form onSubmit={handleOpenEndedSubmit} className="open-ended-form">
                <label htmlFor="open-ended-input" className="sr-only">
                  Your Explanation
                </label>
                <textarea
                  id="open-ended-input"
                  className="open-ended-textarea"
                  placeholder="Explain your mathematical or conceptual reasoning step-by-step..."
                  value={openEndedText}
                  onChange={(e) => setOpenEndedText(e.target.value)}
                  disabled={isSubmitting}
                  rows={5}
                />
                <div className="textarea-footer">
                  <span>
                    {openEndedText.trim()
                      ? `${openEndedText.trim().split(/\s+/).length} words`
                      : "0 words"}{" "}
                    • {openEndedText.length} characters
                  </span>
                  {intervention.rubric?.passing_score && (
                    <span>
                      Passing threshold: {(intervention.rubric.passing_score * 100).toFixed(0)}%
                    </span>
                  )}
                </div>

                {submitError && <p className="error-message">{submitError}</p>}

                <div className="checkpoint-actions">
                  {isSkippable && (
                    <button
                      type="button"
                      className="skip-button"
                      onClick={handleSkip}
                      disabled={isSubmitting || isSkipping}
                    >
                      Skip Checkpoint
                    </button>
                  )}
                  <button
                    type="submit"
                    className="submit-button"
                    disabled={!openEndedText.trim() || isSubmitting}
                  >
                    {isSubmitting ? "Submitting..." : "Submit for Evaluation"}
                  </button>
                </div>
              </form>
            )}
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
                        name="inquiry-hypothesis"
                        value={opt.id}
                        checked={selectedHypothesis === opt.id}
                        onChange={() => setSelectedHypothesis(opt.id)}
                      />
                      <span className="option-text">{opt.text}</span>
                    </label>
                  ))}
                </div>

                <div className="checkpoint-actions">
                  {isSkippable && (
                    <button
                      type="button"
                      className="skip-button"
                      onClick={handleSkip}
                      disabled={isSubmitting || isSkipping}
                    >
                      Skip Checkpoint
                    </button>
                  )}
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
                <div className="hypothesis-reminder">
                  <span>Locked Hypothesis: </span>
                  <strong>
                    {hypothesisOptions.find((o) => o.id === selectedHypothesis)?.text ??
                      selectedHypothesis}
                  </strong>
                </div>

                <div className="sandbox-panel">
                  <div className="sandbox-header">
                    <span>
                      {intervention.sandbox_config?.environment === "javascript_eval"
                        ? "JavaScript Sandbox"
                        : "Python Sandbox"}
                    </span>
                    {intervention.sandbox_config?.hints &&
                      intervention.sandbox_config.hints.length > 0 && (
                        <button
                          type="button"
                          className="hint-btn"
                          onClick={() => setShowHints((h) => !h)}
                        >
                          {showHints ? "Hide Hints" : "Show Hints"}
                        </button>
                      )}
                  </div>

                  {showHints && intervention.sandbox_config?.hints && (
                    <div className="hints-box">
                      <ul>
                        {intervention.sandbox_config.hints.map((hint, idx) => (
                          <li key={idx}>{hint}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  <div className="code-editor-area">
                    <textarea
                      className="code-textarea"
                      value={code}
                      onChange={(e) => setCode(e.target.value)}
                      rows={8}
                      spellCheck={false}
                      aria-label="Interactive Code Editor"
                    />
                  </div>

                  <div className="sandbox-controls">
                    <button
                      type="button"
                      className="run-code-button"
                      onClick={handleRunCode}
                      disabled={isRunningCode}
                    >
                      {isRunningCode ? "Running..." : "▶ Run Experiment"}
                    </button>
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

                <div className="form-actions">
                  <button
                    type="button"
                    className="secondary-btn"
                    onClick={() => setInquiryStep("hypothesis")}
                  >
                    ← Review Hypothesis
                  </button>
                  {isSkippable && (
                    <button
                      type="button"
                      className="skip-button"
                      onClick={handleSkip}
                      disabled={isSubmitting || isSkipping}
                    >
                      Skip Checkpoint
                    </button>
                  )}
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

            <div className="checkpoint-actions">
              {isSkippable && (
                <button
                  type="button"
                  className="skip-button"
                  onClick={handleSkip}
                  disabled={isSubmitting || isSkipping}
                >
                  Skip Checkpoint
                </button>
              )}
              <button
                type="submit"
                className="submit-button"
                disabled={!hasMcqSelection || isSubmitting}
              >
                {isSubmitting ? "Evaluating..." : "Submit Answer"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
