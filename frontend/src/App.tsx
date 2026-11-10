import { useCallback, useEffect, useState } from "react";
import {
  createSession,
  fetchHealthStatus,
  fetchLecture,
  fetchLectures,
  generateInterventions,
  getApiBaseUrl,
  hasTabOnlyProgress,
} from "./api";
import Player from "./Player";
import IngestPage from "./studio/IngestPage";
import type { Lecture, LectureSummary, SessionState } from "./types";

type ConnectionState = "connecting" | "available" | "unavailable";
type GenerationState = "idle" | "generating" | "error";

function sortLecturesForPreference(lectures: LectureSummary[]): LectureSummary[] {
  const priority = { math_sample_lecture: 0 };

  return [...lectures].sort((left, right) => {
    const leftPriority = priority[left.id as keyof typeof priority] ?? 99;
    const rightPriority = priority[right.id as keyof typeof priority] ?? 99;

    if (leftPriority !== rightPriority) {
      return leftPriority - rightPriority;
    }

    return left.id.localeCompare(right.id);
  });
}

export default function App() {
  const [connectionState, setConnectionState] = useState<ConnectionState>("connecting");
  const [lectures, setLectures] = useState<LectureSummary[]>([]);
  const [selectedLectureId, setSelectedLectureId] = useState<string | null>(null);
  const [selectedLecture, setSelectedLecture] = useState<Lecture | null>(null);
  const [sessionState, setSessionState] = useState<SessionState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tabOnlyProgress, setTabOnlyProgress] = useState(false);
  const [generationState, setGenerationState] = useState<GenerationState>("idle");
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [showIngestPage, setShowIngestPage] = useState(false);

  // On mount: health check + load lecture list
  useEffect(() => {
    let isCurrent = true;

    async function init() {
      try {
        await fetchHealthStatus();
        if (!isCurrent) return;
        setConnectionState("available");

        const availableLectures = sortLecturesForPreference(await fetchLectures());
        if (!isCurrent) return;
        setLectures(availableLectures);

        if (availableLectures.length > 0) {
          setSelectedLectureId(availableLectures[0].id);
        }
      } catch (err) {
        if (isCurrent) {
          setConnectionState("unavailable");
          setError(err instanceof Error ? err.message : "Failed to connect to backend.");
        }
      }
    }

    void init();
    return () => { isCurrent = false; };
  }, []);

  // Load lecture + create session whenever selectedLectureId changes
  useEffect(() => {
    if (!selectedLectureId) return;
    let isCurrent = true;

    setSelectedLecture(null);
    setSessionState(null);
    setError(null);
    setGenerationError(null);
    setGenerationState("idle");

    async function load() {
      try {
        const fullLecture = await fetchLecture(selectedLectureId!);
        if (!isCurrent) return;
        setSelectedLecture(fullLecture);

        const newSession = await createSession(selectedLectureId!);
        if (!isCurrent) return;
        setTabOnlyProgress(hasTabOnlyProgress());
        setSessionState(newSession);
      } catch (err) {
        if (isCurrent) {
          setError(err instanceof Error ? err.message : "Failed to load lecture.");
        }
      }
    }

    void load();
    return () => { isCurrent = false; };
  }, [selectedLectureId]);

  const handleLectureChange = useCallback((id: string) => {
    setSelectedLectureId(id);
  }, []);

  // Generate interventions with Gemini for the current lecture
  const handleGenerateInterventions = useCallback(async () => {
    if (!selectedLectureId || !selectedLecture) return;
    setGenerationState("generating");
    setGenerationError(null);

    try {
      const lectureWithInterventions = await generateInterventions(selectedLectureId);
      setSelectedLecture(lectureWithInterventions);

      // Create a new session bound to the freshly generated intervention set
      const newSession = await createSession(selectedLectureId);
      setSessionState(newSession);
      setGenerationState("idle");
    } catch (err) {
      setGenerationState("error");
      setGenerationError(
        err instanceof Error ? err.message : "Gemini generation failed."
      );
    }
  }, [selectedLectureId, selectedLecture]);

  const isGenerating = generationState === "generating";

  const handleIngestComplete = useCallback((lecture: Lecture) => {
    setLectures((previous) => [
      ...previous.filter((item) => item.id !== lecture.id),
      {
        id: lecture.id, duration_seconds: lecture.duration_seconds,
        video_url: lecture.video_url, intervention_count: lecture.interventions.length,
      },
    ]);
    setShowIngestPage(false);
    setSelectedLectureId(lecture.id);
  }, []);

  return (
    <main>
      <h1>game-loop</h1>
      {tabOnlyProgress && (
        <p role="status">Progress saved for this tab only. It may not be available after you close this tab.</p>
      )}

      <div className={`status-badge ${connectionState}`}>
        {connectionState === "connecting" && "Connecting to backend..."}
        {connectionState === "available" && "Backend connected"}
        {connectionState === "unavailable" && "Backend unavailable"}
      </div>

      {error && (
        <p role="alert" className="error-message">
          {error}
        </p>
      )}

      {showIngestPage && (
        <IngestPage onComplete={handleIngestComplete} onCancel={() => setShowIngestPage(false)} />
      )}

      {!showIngestPage && connectionState === "available" && lectures.length > 0 && (
        <div className="lecture-selector">
          <label htmlFor="lecture-select">Select Lecture:</label>
          <select
            id="lecture-select"
            value={selectedLectureId ?? ""}
            onChange={(e) => handleLectureChange(e.target.value)}
            disabled={isGenerating}
          >
            {lectures.map((l) => (
              <option key={l.id} value={l.id}>
                {l.video_url} ({l.intervention_count} interactions)
              </option>
            ))}
          </select>

          <button type="button" className="generate-btn" onClick={() => setShowIngestPage(true)}>
            Add video
          </button>

          <button
            id="generate-interventions-btn"
            onClick={handleGenerateInterventions}
            disabled={isGenerating || !selectedLecture}
            className="generate-btn"
          >
            {isGenerating ? "Generating with Gemini…" : "Generate Interventions with Gemini"}
          </button>
        </div>
      )}

      {!showIngestPage && connectionState === "available" && lectures.length === 0 && (
        <button type="button" className="generate-btn" onClick={() => setShowIngestPage(true)}>Add video</button>
      )}

      {generationError && (
        <p role="alert" className="error-message generation-error">
          Generation failed: {generationError}
        </p>
      )}

      {connectionState === "available" && selectedLecture && sessionState && (
        <section className="lecture-card">
          <div className="lecture-header">
            <h2>Lecture</h2>
            <div className="lecture-meta">
              <span>Length: {Math.floor(selectedLecture.duration_seconds / 60)}m {Math.floor(selectedLecture.duration_seconds % 60)}s</span>
              <span>Interactions: {selectedLecture.interventions?.length ?? 0}</span>
            </div>
          </div>

          <Player
            lecture={selectedLecture}
            sessionState={sessionState}
            onSessionStateChange={setSessionState}
            mediaBaseUrl={getApiBaseUrl()}
          />
        </section>
      )}
    </main>
  );
}
