import React, { useEffect, useRef, useState } from "react";
import { HTML5VideoAdapter, type VideoPlayerAdapter } from "./adapters/PlayerAdapter";
import { activateIntervention, submitAnswer, submitExperiment, syncPlayback } from "./api";
import InterventionOverlay from "./components/InterventionOverlay";
import type {
  ActiveInterventionPayload,
  EvaluationResult,
  InquiryExperimentSubmission,
  InterventionState,
  Lecture,
  SessionState,
} from "./types";

export interface PlayerProps {
  lecture: Lecture;
  sessionState: SessionState;
  onSessionStateChange: (newState: SessionState) => void;
  mediaBaseUrl: string;
  /** Optional custom player adapter for B2B host integration */
  playerAdapter?: VideoPlayerAdapter;
}

export default function Player({
  lecture,
  sessionState,
  onSessionStateChange,
  mediaBaseUrl,
  playerAdapter,
}: PlayerProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const internalAdapterRef = useRef<HTML5VideoAdapter | null>(null);
  const activeAdapter = playerAdapter ?? internalAdapterRef.current;

  const [activeIntervention, setActiveIntervention] =
    useState<ActiveInterventionPayload | null>(null);
  const [suppressedInterventions, setSuppressedInterventions] = useState<Set<string>>(
    new Set()
  );
  const [lastCheckTime, setLastCheckTime] = useState<number>(0);
  const activeLockTimeRef = useRef<number | null>(null);

  const videoSrc = lecture.video_url.startsWith("http")
    ? lecture.video_url
    : `${mediaBaseUrl}${lecture.video_url}`;

  const tolerance = lecture.timing_config.tolerance;
  const sessionInterventionById = new Map(
    sessionState.interventions.map((intervention) => [intervention.id, intervention])
  );

  const formatTime = (seconds: number) => {
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = Math.floor(seconds % 60);
    return `${minutes}:${remainingSeconds.toString().padStart(2, "0")}`;
  };

  // Attach internal HTML5 adapter when videoRef is available and no external adapter provided
  useEffect(() => {
    if (!playerAdapter && videoRef.current) {
      if (!internalAdapterRef.current) {
        internalAdapterRef.current = new HTML5VideoAdapter(videoRef.current);
      } else {
        internalAdapterRef.current.attach(videoRef.current);
      }
    }
    return () => {
      internalAdapterRef.current?.detach();
    };
  }, [playerAdapter]);

  // Trigger window detection on timeupdate
  const handleTimeUpdate = async () => {
    const adapter = playerAdapter ?? internalAdapterRef.current;
    const video = videoRef.current;
    const currentTime = adapter ? adapter.getCurrentTime() : (video?.currentTime ?? 0);

    if (activeIntervention) return;
    setLastCheckTime(currentTime);

    // Look for eligible PENDING interventions whose trigger window covers currentTime
    const pendingSessionState = sessionState.interventions.find((i) => {
      if (i.state !== "PENDING") return false;
      if (suppressedInterventions.has(i.id)) return false;
      const windowStart = i.trigger_time - tolerance;
      const windowEnd = i.trigger_time + tolerance;
      return currentTime >= windowStart && currentTime <= windowEnd;
    });

    if (pendingSessionState) {
      // Pause video immediately (optimistic pause) via adapter
      if (adapter) {
        adapter.pause();
      } else if (video) {
        video.pause();
      }
      activeLockTimeRef.current = currentTime;

      try {
        const payload = await activateIntervention(
          sessionState.session_id,
          pendingSessionState.id,
          currentTime
        );
        setActiveIntervention(payload);
        onSessionStateChange(payload.session_state);
      } catch {
        // Activation rejected: suppress duplicate activation for this window & resume
        setSuppressedInterventions((prev) => new Set(prev).add(pendingSessionState.id));
        activeLockTimeRef.current = null;
        if (adapter) {
          void adapter.play().catch(() => {});
        } else if (video) {
          void video.play().catch(() => {});
        }
      }
    }
  };

  // Seeking sync
  const handleSeeking = async () => {
    const adapter = playerAdapter ?? internalAdapterRef.current;
    const video = videoRef.current;
    const currentTime = adapter ? adapter.getCurrentTime() : (video?.currentTime ?? 0);

    // If an intervention is ACTIVE, disable seeking away
    if (activeIntervention && activeLockTimeRef.current !== null) {
      if (adapter) {
        adapter.seekTo(activeLockTimeRef.current);
      } else if (video) {
        video.currentTime = activeLockTimeRef.current;
      }
      return;
    }

    try {
      const updatedState = await syncPlayback(sessionState.session_id, currentTime);
      onSessionStateChange(updatedState);
    } catch {
      // Ignore sync errors during seek
    }
  };

  const handleSubmitAnswer = async (
    answer: string | string[]
  ): Promise<EvaluationResult> => {
    if (!activeIntervention) {
      throw new Error("No active intervention to submit.");
    }

    const idempotencyKey = `sub_${sessionState.session_id}_${activeIntervention.id}_${Date.now()}`;
    const result = await submitAnswer(
      sessionState.session_id,
      activeIntervention.id,
      idempotencyKey,
      answer
    );

    onSessionStateChange(result.session_state);
    return result;
  };

  const handleSubmitExperiment = async (
    submission: InquiryExperimentSubmission
  ): Promise<EvaluationResult> => {
    if (!activeIntervention) {
      throw new Error("No active intervention to submit.");
    }

    const result = await submitExperiment(sessionState.session_id, submission);
    onSessionStateChange(result.session_state);
    return result;
  };

  const handleFeedbackComplete = () => {
    setActiveIntervention(null);
    activeLockTimeRef.current = null;
    const adapter = playerAdapter ?? internalAdapterRef.current;
    const video = videoRef.current;
    if (adapter) {
      void adapter.play().catch(() => {});
    } else if (video) {
      void video.play().catch(() => {});
    }
  };

  return (
    <div className="player-container">
      <div className="video-wrapper">
        <video
          ref={videoRef}
          src={videoSrc}
          controls={!activeIntervention}
          onTimeUpdate={handleTimeUpdate}
          onSeeking={handleSeeking}
          className="lecture-video"
          data-testid="lecture-video"
        >
          Your browser does not support the video tag.
        </video>

        {activeIntervention && (
          <InterventionOverlay
            intervention={activeIntervention}
            onSubmit={handleSubmitAnswer}
            onSubmitExperiment={handleSubmitExperiment}
            onFeedbackComplete={handleFeedbackComplete}
          />
        )}
      </div>

      <div className="player-status-bar">
        <span>Current Time: {lastCheckTime.toFixed(1)}s</span>
        <span>Version: {sessionState.version}</span>
        {sessionState.client_id && (
          <span className="client-id-badge">Client: {sessionState.client_id}</span>
        )}
      </div>

      <section className="intervention-checkpoints" aria-label="Intervention checkpoints">
        <div className="checkpoints-header">
          <h3>Intervention checkpoints</h3>
          <span>{lecture.interventions.length}</span>
        </div>

        {lecture.interventions.length > 0 ? (
          <ol className="checkpoints-list">
            {lecture.interventions.map((intervention) => {
              const state: InterventionState =
                sessionInterventionById.get(intervention.id)?.state ?? "PENDING";

              return (
                <li
                  key={intervention.id}
                  className={`checkpoint-item ${state.toLowerCase()}`}
                >
                  <span className="checkpoint-time">
                    {formatTime(intervention.trigger_time)}
                  </span>
                  <span className="checkpoint-copy">
                    <span className="checkpoint-concept">{intervention.concept}</span>
                    <span className="checkpoint-question">{intervention.question}</span>
                  </span>
                  <span className={`checkpoint-difficulty ${intervention.difficulty.toLowerCase()}`}>
                    {intervention.difficulty}
                  </span>
                  <span className={`checkpoint-state ${state.toLowerCase()}`}>{state}</span>
                </li>
              );
            })}
          </ol>
        ) : (
          <p className="empty-checkpoints">No checkpoints yet.</p>
        )}
      </section>
    </div>
  );
}
