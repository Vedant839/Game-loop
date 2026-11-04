# V0.4 Specification & Commercial Strategy RFC: The Active-Retention Engine

**Document Status:** INQUIRY, COMMERCIAL STRATEGY & ARCHITECTURE RFC  
**Target Milestone:** `game-loop` V0.4 (The Commercial Bridge to V0.5 Demo)  
**Target Audience:** Independent Video Course Creators, Small EdTech Bootcamps, Cohort-Based Academies  
**Created:** 2026-11-04  

---

## 1. Executive Summary & Core Value Proposition

The foundational thesis of `game-loop`:
> **Passive video watching is broken.** The average completion rate for asynchronous online courses is between 5% and 15%. Learners scrub at 2x speed, tab away, zone out, and retain very little. This results in high refund requests, low student outcomes, weak referral loops, and inability for creators to charge premium pricing.

`game-loop` is not another video player, and it is not a quiz plugin. It is an **Active-Retention Engine** that transforms video consumption into an interactive flow state:
$$\text{Curiosity Priming} \longrightarrow \text{Video Observation} \longrightarrow \text{Active Prediction / Sandbox} \longrightarrow \text{Instant Evaluation} \longrightarrow \text{Mastery Growth} \longrightarrow \text{Verified Proof}$$

### The Commercial Goal for V0.4 & V0.5
- **V0.4 (The Structural & UX Foundation):** Deliver the end-to-end creator onboarding pipeline (URL/video -> auto-transcription -> multi-mode checkpoint generation), the embeddable zero-friction distribution player, the high-delight student flow UX, and the creator retention analytics dashboard.
- **V0.5 (The Commercial Demo):** A turnkey showcase ready for sales pitches and live pilot onboarding, with creator authentication, billing tiers, and verifiable certificates of completion.

---

## 2. The Economic & Architectural Mandate: Zero-Fixed-Cost Scale-to-Zero

The system must satisfy two strict economic constraints:
1. **Zero Cost When Idle ($0.00 / month):** If no students or creators are using the platform, ongoing cloud infrastructure costs must be essentially zero.
2. **High Gross Margins (>85%) on Usage:** When clients drive traffic, operational costs (LLM tokens + serverless compute + lightweight storage) scale linearly with usage while charging subscription or usage-based pricing.

### Architectural Blueprint for Scale-to-Zero

```text
  [ Learner / Creator Browser ]
                 │
                 ▼ (Static SPA / CDN)
  [ Cloudflare Pages / Vercel ]  ──────────> $0.00 / mo (Generous free tier)
                 │
                 ▼ (REST / WebSockets / Server-Sent Events)
  [ Serverless Backend Container ]  ───────> $0.00 / mo when idle (e.g., Google Cloud Run / Fly.io / Modal)
         (Scale to 0 instances)
                 │
        ┌────────┴────────────────────────┐
        ▼                                 ▼
[ Serverless DB / SQLite ]       [ On-Demand AI APIs ]
  - Turso (LibSQL Serverless)      - Gemini 2.5 Flash / Flash Lite (pay per token)
  - OR Embedded SQLite + Cloud     - Whisper / Gemini Audio (pay per minute transcribed)
    R2/GCS backup (Litestream)
  - Cost: $0.00 / mo idle          - Cost: fractions of a cent per session
```

*Crucial Video Storage Rule:* `game-loop` **never pays for video streaming bandwidth**. Videos remain hosted on YouTube (unlisted), Vimeo, Wistia, Mux, Cloudflare Stream, or the creator's S3/GCS bucket. `game-loop` acts as an intelligence and interaction overlay layer.

---

## 3. The "AWS-Like" Creator Lock-In Moat

To achieve high retention and pricing power, creators and edtechs must feel that disabling `game-loop` harms their business:

1. **The Retention & Drop-Off Intelligence Moat:**
   - Instead of basic YouTube/Vimeo view counts, creators get real-time *Attention Heatmaps* showing exactly which sentences caused cognitive overload, where students struggled, and which concepts had high misconception rates.
   - Without `game-loop`, the creator is flying blind.

2. **The "Proof of Active Mastery" Certificate (Anti-Cheating / Anti-Scrubbing):**
   - Standard LMS certificates can be obtained by leaving a video running on mute.
   - `game-loop` issues a tamper-evident, cryptographically signed *Mastery Credential* certifying that the student made predictions, executed sandbox code, and answered freeform questions. EdTechs can guarantee this to hiring partners and employers.

3. **5-Minute Frictionless Creator Onboarding:**
   - Drop in a YouTube link or MP4 $\rightarrow$ AI auto-transcribes $\rightarrow$ AI suggests 4–6 high-impact interactive checkpoints (prediction, coding sandbox, conceptual check) $\rightarrow$ Creator reviews in 60 seconds $\rightarrow$ Generates an embeddable `<iframe>` code or shareable link.

4. **Branded Student Experience & Study Notes Generation:**
   - Every prediction, experiment, and submitted explanation gets automatically synthesized into a downloadable "Personalized Concept Cheat Sheet" for the student, creating high student sentiment and loyalty.

---

## 4. Proposed V0.4 Feature Breakdown

### Epic 1: Creator Onboarding & Automated Pipeline Studio
- **Video Ingestion:** Direct support for YouTube/Vimeo URLs and MP4 uploads.
- **Automated Speech-to-Transcript:** Integration with Gemini Multimodal / Whisper for automatic timestamped transcript generation.
- **Checkpoint Authoring Studio:** Fast visual editor for creators to inspect AI-generated checkpoints, adjust timestamps on a visual timeline, tweak rubrics, and toggle `SKIPPABLE` vs `REQUIRED`.

### Epic 2: Delightful Active-Learning Learner UX
- **Curiosity Priming (The "Heads-Up" Anchor):** 10-second subtle cue alerting the student to pay attention to an incoming concept before the pause.
- **Prediction / "Betting" Mechanic:** Engaging UI where students commit to a hypothesis before code execution or explanation.
- **Rich Feedback & Flow:** Seamless audio decrescendo, animated mastery badges, non-intrusive floating feedback cards, and streak counters.
- **Active Study Notes Drawer:** Auto-compiled summary of questions, student answers, and teacher solutions that learners can export.

### Epic 3: Embeddability & Multi-Platform Distribution
- **Embed Code Generator:** 1-click `<iframe>` embed snippet compatible with Teachable, Kajabi, Skool, Circle, Notion, and custom sites.
- **Standalone Hosted Mode:** Clean distraction-free web page for direct sharing (`app.gameloop.io/w/{slug}`).
- **Lightweight Web Component / Headless Hook:** For custom React/Vue EdTech applications.

### Epic 4: Creator Retention & Analytics Dashboard
- **Cohort Mastery Overview:** Average completion rate, drop-off rates, concept mastery distributions.
- **Intervention Diagnostic Matrix:** Highlights questions where >30% of students failed or skipped, providing actionable course improvement feedback.
- **Student Audit Logs:** Detailed per-student interaction timestamps, answers, and evaluations.

### Epic 5: Zero-Cost Serverless Deployment Architecture
- Dockerfile optimized for Cloud Run / Fly.io scale-to-zero.
- SQLite + Litestream or Turso migration for resilient cloud persistence with $0 idle cost.

