import { useCallback, useEffect, useState } from "react";
import {
  createLecture,
  createSession,
  fetchHealthStatus,
  fetchLecture,
  fetchLectures,
  generateInterventions,
  getApiBaseUrl,
  hasTabOnlyProgress,
} from "./api";
import Player from "./Player";
import type { Lecture, LectureSummary, SessionState } from "./types";

const createLectureFormDefaults = {
  id: "linear_algebra_fundamentals",
  title: "Linear Algebra Fundamentals",
  subject: "Linear Algebra",
  grade: "Grade 12",
  duration_seconds: "300",
  video_url: "/media/math_sample_lecture.mp4",
  transcript: "Welcome to the lecture.\nWe begin with vector notation and component operations.\nWe then review scalar multiplication and dot products.\nFinally, we connect these tools to linear independence and span.",
};

function makeLectureId(title: string): string {
  const base = title
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "") || "custom_lecture";

  return base.length > 40 ? base.slice(0, 40).replace(/_+$/, "") : base;
}

function buildLectureFromForm(form: typeof createLectureFormDefaults): Lecture {
  const duration = Number(form.duration_seconds) || 300;
  const transcriptLines = form.transcript
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean);

  const segmentCount = Math.max(transcriptLines.length, 1);
  const segmentDuration = duration / segmentCount;

  const transcript = transcriptLines.map((text, index) => ({
    start_time: index * segmentDuration,
    end_time: (index + 1) * segmentDuration,
    text,
  }));

  return {
    id: (form.id && form.id.trim()) || makeLectureId(form.title),
    title: form.title.trim(),
    subject: form.subject.trim() || "Linear Algebra",
    grade: form.grade.trim() || "Grade 12",
    duration_seconds: duration,
    video_url: form.video_url.trim() || "/media/math_sample_lecture.mp4",
    timing_config: { min_trigger_gap: 15.0, tolerance: 2.0 },
    transcript,
    interventions: [],
  } satisfies Lecture;
}

type ConnectionState = "connecting" | "available" | "unavailable";
type GenerationState = "idle" | "generating" | "error";

function sortLecturesForPreference(lectures: LectureSummary[]): LectureSummary[] {
  const priority = { linear_algebra_vectors: 0, linux_command_line: 1, math_sample_lecture: 2 };

  return [...lectures].sort((left, right) => {
    const leftPriority = priority[left.id as keyof typeof priority] ?? 99;
    const rightPriority = priority[right.id as keyof typeof priority] ?? 99;

    if (leftPriority !== rightPriority) {
      return leftPriority - rightPriority;
    }

    return left.title.localeCompare(right.title);
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
  const [showAddLectureForm, setShowAddLectureForm] = useState(false);
  const [newLectureForm, setNewLectureForm] = useState(createLectureFormDefaults);

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

  const handleAddLecture = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const createdLecture = buildLectureFromForm(newLectureForm);

      try {
        const savedLecture = await createLecture(createdLecture);
        const savedLectureInterventionCount = Array.isArray(savedLecture.interventions)
          ? savedLecture.interventions.length
          : 0;

        setLectures((previousLectures) => {
          const existing = previousLectures.some((lecture) => lecture.id === savedLecture.id);
          return existing
            ? previousLectures
            : [
                ...previousLectures,
                {
                  id: savedLecture.id,
                  title: savedLecture.title,
                  subject: savedLecture.subject,
                  grade: savedLecture.grade,
                  duration_seconds: savedLecture.duration_seconds,
                  video_url: savedLecture.video_url,
                  intervention_count: savedLectureInterventionCount,
                },
              ];
        });
        setSelectedLectureId(savedLecture.id);
        setShowAddLectureForm(false);
        setNewLectureForm(createLectureFormDefaults);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to create lecture.");
      }
    },
    [newLectureForm]
  );

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

      {connectionState === "available" && lectures.length > 0 && (
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
                {l.title} ({l.intervention_count} interventions)
              </option>
            ))}
          </select>

          <button
            type="button"
            id="add-lecture-btn"
            onClick={() => setShowAddLectureForm((previous) => !previous)}
            className="generate-btn"
          >
            {showAddLectureForm ? "Hide lecture form" : "Add Lecture"}
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

      {showAddLectureForm && (
        <form onSubmit={handleAddLecture} className="add-lecture-form">
          <h3>Add a lecture</h3>
          <div className="form-grid">
            <label>
              Lecture ID
              <input
                value={newLectureForm.id}
                onChange={(event) =>
                  setNewLectureForm((previous) => ({ ...previous, id: event.target.value }))
                }
              />
            </label>
            <label>
              Lecture Title
              <input
                value={newLectureForm.title}
                onChange={(event) =>
                  setNewLectureForm((previous) => ({ ...previous, title: event.target.value }))
                }
              />
            </label>
            <label>
              Subject
              <input
                value={newLectureForm.subject}
                onChange={(event) =>
                  setNewLectureForm((previous) => ({ ...previous, subject: event.target.value }))
                }
              />
            </label>
            <label>
              Grade
              <input
                value={newLectureForm.grade}
                onChange={(event) =>
                  setNewLectureForm((previous) => ({ ...previous, grade: event.target.value }))
                }
              />
            </label>
            <label>
              Duration
              <input
                type="number"
                min="60"
                value={newLectureForm.duration_seconds}
                onChange={(event) =>
                  setNewLectureForm((previous) => ({
                    ...previous,
                    duration_seconds: event.target.value,
                  }))
                }
              />
            </label>
            <label>
              Video URL
              <input
                value={newLectureForm.video_url}
                onChange={(event) =>
                  setNewLectureForm((previous) => ({ ...previous, video_url: event.target.value }))
                }
              />
            </label>
          </div>
          <label>
            Transcript
            <textarea
              rows={6}
              value={newLectureForm.transcript}
              onChange={(event) =>
                setNewLectureForm((previous) => ({ ...previous, transcript: event.target.value }))
              }
            />
          </label>
          <button type="submit" className="generate-btn">Create Lecture</button>
        </form>
      )}

      {generationError && (
        <p role="alert" className="error-message generation-error">
          Generation failed: {generationError}
        </p>
      )}

      {connectionState === "available" && selectedLecture && sessionState && (
        <section className="lecture-card">
          <div className="lecture-header">
            <h2>{selectedLecture.title}</h2>
            <div className="lecture-meta">
              <span>Subject: {selectedLecture.subject}</span>
              <span>
                Topic:{" "}
                {selectedLecture.title.includes(" - ")
                  ? selectedLecture.title.split(" - ").slice(1).join(" - ")
                  : selectedLecture.title}
              </span>
              <span>Grade: {selectedLecture.grade}</span>
              <span>Duration: {selectedLecture.duration_seconds}s</span>
              <span>Interventions: {selectedLecture.interventions.length}</span>
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
