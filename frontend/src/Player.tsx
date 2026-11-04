import React, { useEffect, useRef, useState } from "react";
import { HTML5VideoAdapter, type VideoPlayerAdapter } from "./adapters/PlayerAdapter";
import {
  activateIntervention,
  selfAssessSubmission,
  skipIntervention,
  submitAnswer,
  submitExperiment,
  submitOpenEnded,
  syncPlayback,
} from "./api";
import InterventionOverlay from "./components/InterventionOverlay";
import type {
  ActiveInterventionPayload,
  EvaluationResult,
  InquiryExperimentSubmission,
  InterventionState,
  Lecture,
  OpenEndedSubmissionResponse,
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
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const internalAdapterRef = useRef<HTML5VideoAdapter | null>(null);

  const [isFullscreen, setIsFullscreen] = useState<boolean>(false);
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

  // Fullscreen management: Fullscreen the wrapper so overlays and dialogs remain visible
  useEffect(() => {
    const handleFullscreenChange = () => {
      const isCurrentlyFs =
        Boolean(document.fullscreenElement) &&
        document.fullscreenElement === wrapperRef.current;
      setIsFullscreen(isCurrentlyFs);
    };

    document.addEventListener("fullscreenchange", handleFullscreenChange);
    document.addEventListener("webkitfullscreenchange", handleFullscreenChange);
    return () => {
      document.removeEventListener("fullscreenchange", handleFullscreenChange);
      document.removeEventListener("webkitfullscreenchange", handleFullscreenChange);
    };
  }, []);

  const toggleFullscreen = async () => {
    const wrapper = wrapperRef.current;
    if (!wrapper) return;

    try {
      if (!document.fullscreenElement) {
        if (wrapper.requestFullscreen) {
          await wrapper.requestFullscreen();
        } else if ((wrapper as any).webkitRequestFullscreen) {
          await (wrapper as any).webkitRequestFullscreen();
        }
      } else {
        if (document.exitFullscreen) {
          await document.exitFullscreen();
        } else if ((document as any).webkitExitFullscreen) {
          await (document as any).webkitExitFullscreen();
        }
      }
    } catch (err) {
      console.warn("Fullscreen toggle failed:", err);
    }
  };

  // When an intervention activates, if video element alone was fullscreened by native controls, transfer to wrapper
  useEffect(() => {
    if (activeIntervention && document.fullscreenElement === videoRef.current && wrapperRef.current) {
      document.exitFullscreen().then(() => {
        wrapperRef.current?.requestFullscreen().catch(() => {});
      }).catch(() => {});
    }
  }, [activeIntervention]);

  // Anti-ad immersion: check if an upcoming checkpoint is within 6 seconds
  const isApproachingCheckpoint = sessionState.interventions.some((i) => {
    if (i.state !== "PENDING") return false;
    const diff = i.trigger_time - lastCheckTime;
    return diff > 0 && diff <= 6.0;
  });

  // Anti-ad immersion: 300ms audio decrescendo before pause
  const fadeOutAndPause = async (
    adapter: VideoPlayerAdapter | null,
    video: HTMLVideoElement | null
  ) => {
    if (video) {
      const originalVolume = video.volume;
      const start = performance.now();
      const duration = 300;
      await new Promise<void>((resolve) => {
        const step = (now: number) => {
          const elapsed = now - start;
          if (elapsed < duration) {
            video.volume = Math.max(0, originalVolume * (1 - elapsed / duration));
            requestAnimationFrame(step);
          } else {
            video.volume = 0;
            resolve();
          }
        };
        requestAnimationFrame(step);
      });
      if (adapter) {
        adapter.pause();
      } else {
        video.pause();
      }
      video.volume = originalVolume;
    } else if (adapter) {
      adapter.pause();
    }
  };

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
      // Gentle audio fade-out and pause
      await fadeOutAndPause(adapter, video);
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

  const handleSubmitOpenEnded = async (
    answer: string
  ): Promise<OpenEndedSubmissionResponse> => {
    if (!activeIntervention) {
      throw new Error("No active intervention to submit.");
    }

    const idempotencyKey = `sub_open_${sessionState.session_id}_${activeIntervention.id}_${Date.now()}`;
    const result = await submitOpenEnded(
      sessionState.session_id,
      activeIntervention.id,
      idempotencyKey,
      answer
    );

    if (result.session_state) {
      onSessionStateChange(result.session_state);
    }
    return result;
  };

  const handleSelfAssess = async (
    submissionId: string,
    correct: boolean
  ): Promise<void> => {
    const updatedState = await selfAssessSubmission(
      sessionState.session_id,
      submissionId,
      correct
    );
    onSessionStateChange(updatedState);
  };

  const handleSkipIntervention = async (): Promise<void> => {
    if (!activeIntervention) return;
    const updatedState = await skipIntervention(
      sessionState.session_id,
      activeIntervention.id,
      "learner_skipped"
    );
    onSessionStateChange(updatedState);
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

  const progressPercent =
    lecture.duration_seconds > 0
      ? Math.min(100, Math.max(0, (lastCheckTime / lecture.duration_seconds) * 100))
      : 0;

  const handleTimelineClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (activeIntervention) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const clickX = e.clientX - rect.left;
    const clickRatio = Math.max(0, Math.min(1, clickX / rect.width));
    const targetTime = clickRatio * lecture.duration_seconds;
    const adapter = playerAdapter ?? internalAdapterRef.current;
    const video = videoRef.current;
    if (adapter) {
      adapter.seekTo(targetTime);
    } else if (video) {
      video.currentTime = targetTime;
    }
  };

  return (
    <div className="player-container">
      <div
        ref={wrapperRef}
        className={`video-wrapper ${isApproachingCheckpoint ? "approaching-glow" : ""} ${isFullscreen ? "is-fullscreen" : ""}`}
      >
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

        {/* Custom floating fullscreen button that fullscreens the wrapper */}
        <button
          type="button"
          className="video-floating-fs-btn"
          onClick={toggleFullscreen}
          title={isFullscreen ? "Exit Fullscreen" : "Enter Fullscreen"}
          aria-label={isFullscreen ? "Exit Fullscreen" : "Enter Fullscreen"}
        >
          {isFullscreen ? "✕" : "⛶"}
        </button>

        {activeIntervention && (
          <InterventionOverlay
            intervention={activeIntervention}
            onSubmit={handleSubmitAnswer}
            onSubmitExperiment={handleSubmitExperiment}
            onSubmitOpenEnded={handleSubmitOpenEnded}
            onSelfAssess={handleSelfAssess}
            onSkip={handleSkipIntervention}
            onFeedbackComplete={handleFeedbackComplete}
          />
        )}
      </div>

      {/* Interactive Timeline Progress Bar with Checkpoint Pips */}
      <div
        className="timeline-container"
        onClick={handleTimelineClick}
        title="Interactive Video Timeline"
        data-testid="timeline-container"
      >
        <div className="timeline-track">
          <div
            className="timeline-progress"
            style={{ width: `${progressPercent}%` }}
          />
          {lecture.interventions.map((intv) => {
            const state: InterventionState =
              sessionInterventionById.get(intv.id)?.state ?? "PENDING";
            const leftPercent =
              lecture.duration_seconds > 0
                ? (intv.trigger_time / lecture.duration_seconds) * 100
                : 0;
            const policyClass =
              intv.policy === "required" || intv.policy === "required_with_retry"
                ? "required"
                : "skippable";
            const stateClass = state.toLowerCase();

            return (
              <div
                key={intv.id}
                className={`timeline-pip ${policyClass} ${stateClass}`}
                style={{ left: `${leftPercent}%` }}
                title={`${intv.question} (${formatTime(intv.trigger_time)}) - [${policyClass.toUpperCase()}] ${state}`}
                data-testid={`pip-${intv.id}`}
                onClick={(e) => {
                  e.stopPropagation();
                  if (activeIntervention) return;
                  const adapter = playerAdapter ?? internalAdapterRef.current;
                  const video = videoRef.current;
                  if (adapter) {
                    adapter.seekTo(intv.trigger_time);
                  } else if (video) {
                    video.currentTime = intv.trigger_time;
                  }
                }}
              />
            );
          })}
        </div>
      </div>

      <div className="player-status-bar">
        <span>Current Time: {lastCheckTime.toFixed(1)}s</span>
        <span>Version: {sessionState.version}</span>
        {sessionState.client_id && (
          <span className="client-id-badge">Client: {sessionState.client_id}</span>
        )}
        <button
          type="button"
          className="fullscreen-btn"
          onClick={toggleFullscreen}
          title={isFullscreen ? "Exit Fullscreen" : "Toggle Fullscreen"}
        >
          {isFullscreen ? "Exit Fullscreen" : "⛶ Fullscreen"}
        </button>
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
              const policy = intervention.policy ?? "skippable";

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
                  <span className={`policy-badge ${policy}`}>{policy}</span>
                  <span
                    className={`checkpoint-difficulty ${intervention.difficulty.toLowerCase()}`}
                  >
                    {intervention.difficulty}
                  </span>
                  <span className={`checkpoint-state ${state.toLowerCase()}`}>
                    {state}
                  </span>
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
