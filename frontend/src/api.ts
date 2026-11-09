import type {
  ActiveInterventionPayload,
  EvaluationResult,
  Lecture,
  LectureSummary,
  OpenEndedSubmissionResponse,
  SessionState,
  SubmissionStatusResponse,
} from "./types";

export type HealthStatus = {
  status: "ok";
};

const defaultApiBaseUrl = "http://localhost:8000";
const DEFAULT_REQUEST_TIMEOUT_MS = 15000;

async function fetchWithTimeout(
  input: RequestInfo | URL,
  init: RequestInit = {},
  timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS
): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error(`Request timed out after ${timeoutMs}ms.`);
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

export function getApiBaseUrl(): string {
  return (import.meta.env.VITE_API_BASE_URL ?? defaultApiBaseUrl).replace(/\/$/, "");
}

export async function fetchHealthStatus(): Promise<HealthStatus> {
  const response = await fetchWithTimeout(`${getApiBaseUrl()}/api/health`);
  if (!response.ok) {
    throw new Error("Backend health request failed.");
  }
  const payload: unknown = await response.json();
  if (
    typeof payload !== "object" ||
    payload === null ||
    !("status" in payload) ||
    payload.status !== "ok"
  ) {
    throw new Error("Backend health response was invalid.");
  }
  return { status: "ok" };
}

export async function fetchLectures(): Promise<LectureSummary[]> {
  const response = await fetchWithTimeout(`${getApiBaseUrl()}/api/lectures`);
  if (!response.ok) {
    throw new Error("Failed to fetch lectures list.");
  }
  return (await response.json()) as LectureSummary[];
}

export async function fetchLecture(lectureId: string): Promise<Lecture> {
  const response = await fetchWithTimeout(`${getApiBaseUrl()}/api/lectures/${lectureId}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch lecture '${lectureId}'.`);
  }
  return (await response.json()) as Lecture;
}

export async function createLecture(lecture: Lecture): Promise<Lecture> {
  const response = await fetchWithTimeout(`${getApiBaseUrl()}/api/lectures`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(lecture),
  });
  if (!response.ok) {
    const errorData = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(errorData.detail ?? "Failed to create lecture.");
  }
  return (await response.json()) as Lecture;
}

let tabOnlyProgress = false;
const memoryLearnerIds = new Map<string, string>();

export function hasTabOnlyProgress(): boolean {
  return tabOnlyProgress;
}

export function getLearnerId(creatorId = "default_client"): string {
  const key = `gl_learner_${creatorId}`;
  tabOnlyProgress = false;
  try {
    const existing = window.localStorage.getItem(key);
    if (existing) return existing;
    const learnerId = window.crypto.randomUUID();
    window.localStorage.setItem(key, learnerId);
    return learnerId;
  } catch {
    tabOnlyProgress = true;
  }

  try {
    const existing = window.sessionStorage.getItem(key);
    if (existing) return existing;
    const learnerId = window.crypto.randomUUID();
    window.sessionStorage.setItem(key, learnerId);
    return learnerId;
  } catch {
    const existing = memoryLearnerIds.get(key);
    if (existing) return existing;
    const learnerId = window.crypto.randomUUID();
    memoryLearnerIds.set(key, learnerId);
    return learnerId;
  }
}

export async function createSession(
  lectureId: string,
  clientId: string = "default_client",
  learnerId: string = getLearnerId(clientId),
  tierOverride?: number
): Promise<SessionState> {
  const response = await fetchWithTimeout(`${getApiBaseUrl()}/api/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      lecture_id: lectureId,
      client_id: clientId,
      learner_id: learnerId,
      tier_override: tierOverride,
    }),
  });
  if (!response.ok) {
    throw new Error("Failed to create session.");
  }
  return (await response.json()) as SessionState;
}

export async function getSession(sessionId: string): Promise<SessionState> {
  const response = await fetchWithTimeout(`${getApiBaseUrl()}/api/sessions/${sessionId}`);
  if (!response.ok) {
    throw new Error(`Failed to get session '${sessionId}'.`);
  }
  return (await response.json()) as SessionState;
}

export async function activateIntervention(
  sessionId: string,
  interventionId: string,
  playbackPosition: number
): Promise<ActiveInterventionPayload> {
  const response = await fetchWithTimeout(`${getApiBaseUrl()}/api/sessions/${sessionId}/activate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      intervention_id: interventionId,
      playback_position: playbackPosition,
    }),
  });
  if (!response.ok) {
    const errorData = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(errorData.detail ?? "Failed to activate intervention.");
  }
  return (await response.json()) as ActiveInterventionPayload;
}

export async function syncPlayback(
  sessionId: string,
  playbackPosition: number
): Promise<SessionState> {
  const response = await fetchWithTimeout(`${getApiBaseUrl()}/api/sessions/${sessionId}/sync`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ playback_position: playbackPosition }),
  });
  if (!response.ok) {
    throw new Error("Failed to sync playback position.");
  }
  return (await response.json()) as SessionState;
}

export async function submitAnswer(
  sessionId: string,
  interventionId: string,
  idempotencyKey: string,
  answer: string | string[]
): Promise<EvaluationResult> {
  const response = await fetchWithTimeout(`${getApiBaseUrl()}/api/sessions/${sessionId}/submit`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      intervention_id: interventionId,
      idempotency_key: idempotencyKey,
      answer,
    }),
  });
  if (!response.ok) {
    const errorData = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(errorData.detail ?? "Failed to submit answer.");
  }
  return (await response.json()) as EvaluationResult;
}

export async function submitExperiment(
  sessionId: string,
  submission: import("./types").InquiryExperimentSubmission
): Promise<EvaluationResult> {
  const response = await fetchWithTimeout(
    `${getApiBaseUrl()}/api/sessions/${sessionId}/experiment`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(submission),
    }
  );
  if (!response.ok) {
    const errorData = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(errorData.detail ?? "Failed to submit experiment.");
  }
  return (await response.json()) as EvaluationResult;
}

export async function fetchLearnerProfile(
  clientId: string,
  userId: string
): Promise<import("./types").LearnerProfile> {
  const response = await fetchWithTimeout(
    `${getApiBaseUrl()}/api/learners/${encodeURIComponent(clientId)}/${encodeURIComponent(userId)}`
  );
  if (!response.ok) {
    throw new Error("Failed to fetch learner profile.");
  }
  return (await response.json()) as import("./types").LearnerProfile;
}

export async function generateInterventions(lectureId: string): Promise<Lecture> {
  const response = await fetchWithTimeout(
    `${getApiBaseUrl()}/api/lectures/${lectureId}/generate_interventions`,
    { method: "POST" },
    90000
  );
  if (!response.ok) {
    const errorData = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(errorData.detail ?? "Failed to generate interventions.");
  }
  return (await response.json()) as Lecture;
}

export async function skipIntervention(
  sessionId: string,
  interventionId: string,
  reason?: string
): Promise<SessionState> {
  const response = await fetchWithTimeout(
    `${getApiBaseUrl()}/api/sessions/${sessionId}/interventions/${interventionId}/skip`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    }
  );
  if (!response.ok) {
    const errorData = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(errorData.detail ?? "Failed to skip intervention.");
  }
  return (await response.json()) as SessionState;
}

export async function submitOpenEnded(
  sessionId: string,
  interventionId: string,
  idempotencyKey: string,
  answer: string
): Promise<OpenEndedSubmissionResponse> {
  const response = await fetchWithTimeout(
    `${getApiBaseUrl()}/api/sessions/${sessionId}/submissions/open-ended`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        intervention_id: interventionId,
        idempotency_key: idempotencyKey,
        user_answer: answer,
      }),
    }
  );
  if (!response.ok) {
    const errorData = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(errorData.detail ?? "Failed to submit open-ended answer.");
  }
  return (await response.json()) as OpenEndedSubmissionResponse;
}

export async function getSubmissionStatus(
  sessionId: string,
  submissionId: string
): Promise<SubmissionStatusResponse> {
  const response = await fetchWithTimeout(
    `${getApiBaseUrl()}/api/sessions/${sessionId}/submissions/${submissionId}`
  );
  if (!response.ok) {
    const errorData = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(errorData.detail ?? "Failed to get submission status.");
  }
  return (await response.json()) as SubmissionStatusResponse;
}

export async function selfAssessSubmission(
  sessionId: string,
  submissionId: string,
  selfAssessedCorrect: boolean
): Promise<SessionState> {
  const response = await fetchWithTimeout(
    `${getApiBaseUrl()}/api/sessions/${sessionId}/submissions/${submissionId}/self-assess`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ self_assessed_correct: selfAssessedCorrect }),
    }
  );
  if (!response.ok) {
    const errorData = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(errorData.detail ?? "Failed to self-assess submission.");
  }
  return (await response.json()) as SessionState;
}
