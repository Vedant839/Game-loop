export type Difficulty = "Easy" | "Medium" | "Hard" | "Tough";

export type InterventionType =
  | "single_choice"
  | "multiple_selection"
  | "predict_and_verify"
  | "inquiry_sandbox"
  | "open_ended";

export type InterventionState =
  | "PENDING"
  | "ACTIVE"
  | "COMPLETED"
  | "BYPASSED"
  | "EVALUATING"
  | "SKIPPED";

export type InterventionPolicy = "skippable" | "required" | "required_with_retry";

export type ResumptionPolicy = "immediate_optimistic" | "wait_for_result";

export type SubmissionStatus = "pending" | "evaluating" | "completed" | "failed";

export interface RubricMisconception {
  tag: string;
  description: string;
  remediation: string;
}

export interface RubricConfig {
  key_concepts: string[];
  misconceptions: RubricMisconception[];
  reference_answer: string;
  passing_score: number;
}

export type SandboxEnvironment = "python_wasm" | "javascript_eval" | "parametric_sim";

export interface Option {
  id: string;
  text: string;
}

export interface TestCase {
  name: string;
  input_data?: string | null;
  expected_output: string;
}

export interface SandboxConfig {
  environment: SandboxEnvironment;
  initial_code: string;
  solution_code?: string | null;
  test_cases: TestCase[];
  hints: string[];
}

export interface InterventionVariant {
  tier: number;
  prompt: string;
  hypothesis_prompt?: string | null;
  hypothesis_options: Option[];
  sandbox_config?: SandboxConfig | null;
  correct_answer?: string | string[] | null;
  correct_feedback: string;
  incorrect_feedback: string;
}

export interface Intervention {
  id: string;
  trigger_time: number;
  concept: string;
  difficulty: Difficulty;
  type: InterventionType;
  question: string;
  options: Option[];
  correct_answer?: string | string[] | null;
  correct_feedback: string;
  incorrect_feedback: string;
  sandbox_config?: SandboxConfig | null;
  hypothesis_prompt?: string | null;
  hypothesis_options?: Option[];
  variants?: Record<number, InterventionVariant>;
  policy?: InterventionPolicy;
  resumption_policy?: ResumptionPolicy;
  rubric?: RubricConfig | null;
}

export interface TranscriptSegment {
  start_time: number;
  end_time: number;
  text: string;
}

export interface TimingConfig {
  min_trigger_gap: number;
  tolerance: number;
}

export interface Lecture {
  id: string;
  title: string;
  subject: string;
  grade: string;
  duration_seconds: number;
  video_url: string;
  timing_config: TimingConfig;
  transcript: TranscriptSegment[];
  interventions: Intervention[];
}

export interface LectureSummary {
  id: string;
  title: string;
  subject: string;
  grade: string;
  duration_seconds: number;
  video_url: string;
  intervention_count: number;
}

export interface InterventionSessionState {
  id: string;
  trigger_time: number;
  state: InterventionState;
}

export interface SessionState {
  session_id: string;
  lecture_id: string;
  version: number;
  client_id?: string | null;
  external_user_id?: string | null;
  active_intervention_id: string | null;
  interventions: InterventionSessionState[];
}

export interface ActiveInterventionPayload {
  id: string;
  trigger_time: number;
  concept: string;
  difficulty: Difficulty;
  type: InterventionType;
  question: string;
  options: Option[];
  session_state: SessionState;
  tier?: number;
  hypothesis_prompt?: string | null;
  hypothesis_options?: Option[];
  sandbox_config?: SandboxConfig | null;
  policy?: InterventionPolicy;
  resumption_policy?: ResumptionPolicy;
  rubric?: RubricConfig | null;
}

export interface OpenEndedSubmissionResponse {
  submission_id: string;
  status: SubmissionStatus;
  resumption_policy: ResumptionPolicy;
  ai_score?: number | null;
  is_correct?: boolean | null;
  formative_feedback?: string | null;
  misconceptions_detected: string[];
  session_state?: SessionState | null;
  reference_rubric?: RubricConfig | null;
}

export interface SubmissionStatusResponse {
  submission_id: string;
  status: SubmissionStatus;
  ai_score?: number | null;
  is_correct?: boolean | null;
  formative_feedback?: string | null;
  misconceptions_detected: string[];
  self_assessed: boolean;
  evaluation_latency_ms?: number | null;
  reference_rubric?: RubricConfig | null;
}

export interface EvaluationResult {
  is_correct: boolean;
  feedback: string;
  submitted_answer: string | string[];
  session_state: SessionState;
  tier?: number;
  mastery_delta?: number;
  suggested_next_tier?: number;
}

export interface LearnerProfile {
  user_id: string;
  client_id: string;
  concept_mastery: Record<string, number>;
  streak: number;
  friction_index: number;
  total_interventions: number;
  total_correct: number;
}

export interface TestExecutionResult {
  name: string;
  passed: boolean;
  actual_output?: string;
  expected_output?: string;
}

export interface InquiryExperimentSubmission {
  intervention_id: string;
  idempotency_key: string;
  hypothesis_answer?: string | string[] | null;
  code_submitted?: string | null;
  test_results: TestExecutionResult[];
  passed_tests: boolean;
  reflection?: string | null;
  expected_version?: number | null;
}

export interface B2BTelemetryEvent {
  event_type: string;
  client_id: string;
  user_id: string;
  session_id: string;
  lecture_id: string;
  intervention_id?: string | null;
  timestamp: number;
  payload: Record<string, unknown>;
}
