import { useState } from "react";
import { ingestLecture, type IngestLecturePayload } from "../api";
import { readVideoDuration } from "../adapters/videoDuration";
import type { Lecture } from "../types";

type Props = { onComplete: (lecture: Lecture) => void; onCancel: () => void };
type Stage = "ready" | "reading_duration" | "transcribing" | "generating" | "error";
const GEMINI_KEY_SLOT = "gl_creator_gemini_key";

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Could not read the audio file."));
    reader.onload = () => {
      const result = String(reader.result ?? "");
      resolve(result.slice(result.indexOf(",") + 1));
    };
    reader.readAsDataURL(file);
  });
}

async function transcribeAudio(file: File, apiKey: string): Promise<string> {
  if (!apiKey.trim()) throw new Error("Enter a Gemini key to transcribe audio in your browser.");
  if (file.size > 15 * 1024 * 1024) throw new Error("Audio files must be 15 MB or smaller for browser transcription.");
  const response = await fetch(
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent",
    {
      method: "POST",
      headers: { "Content-Type": "application/json", "x-goog-api-key": apiKey.trim() },
      body: JSON.stringify({ contents: [{ role: "user", parts: [
        { text: "Transcribe the spoken words accurately. Return only the transcript text." },
        { inlineData: { mimeType: file.type || "audio/mpeg", data: await fileToBase64(file) } },
      ] }] }),
    }
  );
  if (!response.ok) throw new Error("Gemini could not transcribe this audio file.");
  const result = await response.json() as { candidates?: Array<{ content?: { parts?: Array<{ text?: string }> } }> };
  const text = result.candidates?.[0]?.content?.parts?.map((part) => part.text ?? "").join("").trim();
  if (!text) throw new Error("Gemini returned an empty transcript.");
  return text;
}

export default function IngestPage({ onComplete, onCancel }: Props) {
  const [stage, setStage] = useState<Stage>("ready");
  const [error, setError] = useState<string | null>(null);
  const [creatorToken, setCreatorToken] = useState("");
  const [geminiKey, setGeminiKey] = useState(() => {
    try {
      const saved = window.localStorage.getItem(GEMINI_KEY_SLOT);
      if (saved) return saved;
      // Migrate a key saved by earlier builds, which only lasted for the tab session.
      const legacy = window.sessionStorage.getItem(GEMINI_KEY_SLOT) ?? "";
      if (legacy) {
        window.localStorage.setItem(GEMINI_KEY_SLOT, legacy);
        window.sessionStorage.removeItem(GEMINI_KEY_SLOT);
      }
      return legacy;
    } catch { return ""; }
  });
  const [useLectureKey, setUseLectureKey] = useState(false);
  const [lectureGeminiKey, setLectureGeminiKey] = useState("");
  const [videoUrl, setVideoUrl] = useState("");
  const [intensity, setIntensity] = useState<IngestLecturePayload["intensity"]>("standard");
  const [captionFile, setCaptionFile] = useState<File | null>(null);
  const [audioFile, setAudioFile] = useState<File | null>(null);
  const [transcript, setTranscript] = useState("");

  const saveKey = (value: string) => {
    setGeminiKey(value);
    try {
      if (value) window.localStorage.setItem(GEMINI_KEY_SLOT, value);
      else window.localStorage.removeItem(GEMINI_KEY_SLOT);
    } catch { /* Keep the key in component memory for this page. */ }
  };

  const activeGeminiKey = useLectureKey ? lectureGeminiKey : geminiKey;

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    try {
      setStage("reading_duration");
      const durationSeconds = await readVideoDuration(videoUrl);
      let captions = transcript;
      let captionsFormat: IngestLecturePayload["captions_format"] = "text";
      if (captionFile) {
        captions = await captionFile.text();
        captionsFormat = captionFile.name.toLowerCase().endsWith(".vtt") ? "vtt" : "srt";
      } else if (audioFile) {
        setStage("transcribing");
        captions = await transcribeAudio(audioFile, activeGeminiKey);
        setTranscript(captions);
      }
      setStage("generating");
      const lecture = await ingestLecture({
        video_url: videoUrl, duration_seconds: durationSeconds,
        captions, captions_format: captionsFormat, intensity,
      }, creatorToken, activeGeminiKey);
      onComplete(lecture);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Lecture ingestion failed.");
      setStage("error");
    }
  };

  const busy = stage === "reading_duration" || stage === "transcribing" || stage === "generating";
  return (
    <section className="ingest-page" aria-labelledby="ingest-title">
      <h2 id="ingest-title">Create a lecture</h2>
      <p>Paste a video link. Its length is read automatically; add captions or transcribe audio if available. Leave the key blank to use the key configured for this app. A key entered here is saved in this browser for future lectures.</p>
      <form onSubmit={handleSubmit}>
        <label>Creator token<input type="password" autoComplete="off" required value={creatorToken} onChange={(e) => setCreatorToken(e.target.value)} /></label>
        <label>Default Gemini key (saved for future lectures)<input type="password" autoComplete="off" value={geminiKey} onChange={(e) => saveKey(e.target.value)} /></label>
        <label><input type="checkbox" checked={useLectureKey} onChange={(e) => setUseLectureKey(e.target.checked)} /> Use a different Gemini key for this lecture only</label>
        {useLectureKey && <label>Gemini key for this lecture<input type="password" autoComplete="off" value={lectureGeminiKey} onChange={(e) => setLectureGeminiKey(e.target.value)} /></label>}
        <label>Video URL<input type="url" required value={videoUrl} onChange={(e) => setVideoUrl(e.target.value)} placeholder="https://…" /></label>
        <label>Checkpoint intensity<select value={intensity} onChange={(e) => setIntensity(e.target.value as typeof intensity)}>
          <option value="light">Light · 5–6 minutes apart</option><option value="standard">Standard · 3–4 minutes apart</option><option value="intense">Intense · 2–3 minutes apart</option>
        </select></label>
        <label>Caption file (SRT or VTT)<input type="file" accept=".srt,.vtt,text/vtt,application/x-subrip" onChange={(e) => { setCaptionFile(e.target.files?.[0] ?? null); setAudioFile(null); }} /></label>
        <label>Or audio for browser transcription<input type="file" accept="audio/*" onChange={(e) => { setAudioFile(e.target.files?.[0] ?? null); setCaptionFile(null); }} /></label>
        <label>Or paste transcript text<textarea rows={5} value={transcript} onChange={(e) => { setTranscript(e.target.value); setCaptionFile(null); setAudioFile(null); }} /></label>
        {busy && <p role="status">{stage === "reading_duration" ? "Reading video length…" : stage === "transcribing" ? "Transcribing audio in your browser…" : "Generating and saving checkpoints…"}</p>}
        {error && <p role="alert" className="error-message">{error}</p>}
        <div className="ingest-actions"><button type="submit" disabled={busy}>{busy ? "Working…" : "Generate lecture"}</button><button type="button" onClick={onCancel} disabled={busy}>Cancel</button></div>
      </form>
    </section>
  );
}
