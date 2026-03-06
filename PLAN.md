# Genie-QA — Technical Specification & Build Plan

---

## 1. System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        DEVELOPER MACHINE                        │
│                                                                 │
│  ┌──────────────┐    ┌──────────────────┐    ┌──────────────┐  │
│  │  Browser      │───▶│  Local Executor   │───▶│ Coding Agent │  │
│  │  (localhost)  │    │  (Python)         │    │ (Gemini CLI, │  │
│  │              ◀┤    │                   │    │  Cursor, etc)│  │
│  │  hot-reload   │    │  • Screen capture │    │              │  │
│  └──────────────┘    │  • Mouse/keyboard │    │  Reads:      │  │
│                      │  • Frame streaming│    │  bug-report/ │  │
│                      └────────┬──────────┘    └──────────────┘  │
│                               │                                  │
└───────────────────────────────┼──────────────────────────────────┘
                                │ Frames ↑ Actions ↓
                                │ (WebSocket / gRPC)
                    ┌───────────┴───────────┐
                    │   GOOGLE CLOUD RUN     │
                    │                        │
                    │  ┌──────────────────┐  │
                    │  │  Agent Controller │  │
                    │  │                  │  │
                    │  │  • State machine │  │
                    │  │  • Goal planner  │  │
                    │  │  • Critique gen  │  │
                    │  └───────┬──────────┘  │
                    │          │              │
                    │  ┌───────┴──────────┐  │
                    │  │  Gemini API       │  │
                    │  │  (GenAI SDK)      │  │
                    │  │                  │  │
                    │  │  • Live API      │  │
                    │  │  • Vision model  │  │
                    │  │  • Image Gen*    │  │
                    │  └──────────────────┘  │
                    └────────────────────────┘
                              * Stretch goal
```

### Component Responsibilities

**Local Executor (Python, runs on developer machine)**
- Captures browser window frames using `mss` (screenshot) or `Playwright` in headed mode.
- Streams frames to the Cloud Run agent via WebSocket.
- Receives action commands and executes them using `pyautogui` (mouse move, click, type, scroll).
- Monitors the shared output directory and writes `bug-report.md` / JSON files for the coding agent.

**Agent Controller (Cloud Run)**
- Manages the agent state machine (idle → testing → critiquing → waiting_for_fix → verifying).
- Receives frames from the local executor, forwards them to Gemini via the Live API.
- Parses Gemini's action/critique responses and routes them back to the local executor.
- Handles goal decomposition: breaks a natural language test goal into a sequence of visual checkpoints.

**Gemini (via GenAI SDK)**
- Multimodal Live API: ingests the video/frame stream, produces action commands and visual observations.
- Vision reasoning: identifies UI elements by pixel location, reads rendered text, detects layout anomalies.
- Critique generation: produces structured QA output (JSON/Markdown) when issues are found.
- Image generation (NanoBanana, stretch): generates corrected UI mockups from flawed screenshots.

---

## 2. Key Technical Specs

### 2.1 Live API Frame Protocol

```
Frame payload (Local Executor → Cloud Run → Gemini Live API):
{
  "frame": "<base64 encoded PNG>",
  "timestamp_ms": 1720000000000,
  "resolution": { "width": 1920, "height": 1080 },
  "frame_index": 42
}

Action payload (Gemini → Cloud Run → Local Executor):
{
  "action": "CLICK" | "TYPE" | "SCROLL" | "WAIT" | "SCREENSHOT" | "DONE",
  "params": {
    "x": 500,             // for CLICK/SCROLL
    "y": 300,             // for CLICK/SCROLL
    "text": "hello",      // for TYPE
    "duration_ms": 2000   // for WAIT
  },
  "reasoning": "Clicking the submit button to test form validation"
}
```

**Frame rate strategy:** Start with 1-2 fps (screenshot polling). This is reliable and sufficient for UI testing. Upgrade to continuous streaming only if latency permits and the Live API connection is stable. The judges care about the Live API being used, not raw framerate.

**Fallback:** If the Live API WebSocket drops, fall back to single-frame request/response using standard `generateContent` with image input.

### 2.2 Agent State Machine

```
                ┌───────────┐
                │   IDLE     │
                └─────┬─────┘
                      │ receive_goal(goal_text)
                      ▼
                ┌───────────┐
                │  PLANNING  │  Gemini decomposes goal into steps
                └─────┬─────┘
                      │
                      ▼
            ┌──────────────────┐
            │    EXECUTING     │ ◀──────────────────────┐
            │ (action loop)    │                         │
            └─────┬────────────┘                         │
                  │ issue_found OR test_complete          │
                  ▼                                      │
            ┌──────────────┐                             │
            │  CRITIQUING   │  Generate structured report│
            └─────┬────────┘                             │
                  │                                      │
                  ▼                                      │
        ┌──────────────────┐                             │
        │ WAITING_FOR_FIX  │  Write bug-report.md        │
        │ (monitor reload) │  Coding agent picks it up   │
        └─────┬────────────┘                             │
              │ hot_reload_detected                      │
              ▼                                          │
        ┌──────────────────┐                             │
        │   VERIFYING      │  Re-run the same test flow  │
        └─────┬────────────┘                             │
              │                                          │
         pass │         fail                             │
              ▼              └───────────────────────────┘
        ┌───────────┐
        │   DONE     │  Output: final verification report
        └───────────┘
```

### 2.3 Critique Output Schema

```json
{
  "test_goal": "Test login form with invalid credentials",
  "status": "FAIL",
  "issues": [
    {
      "id": "issue-001",
      "type": "accessibility",
      "severity": "critical",
      "description": "Error message text has insufficient contrast ratio. Dark grey (#666) on dark background (#333) fails WCAG AA.",
      "location": {
        "description": "Error message below the password field",
        "approx_coordinates": { "x": 400, "y": 520 }
      },
      "screenshot_b64": "<base64 encoded cropped screenshot>",
      "suggested_fix": "Change the error message text color to #EF4444 (red-500) or #FFFFFF on the dark background to meet WCAG AA contrast ratio of 4.5:1.",
      "wcag_criterion": "1.4.3 Contrast (Minimum)"
    }
  ],
  "passing_checks": [
    "Login form renders correctly",
    "Email and password fields accept input",
    "Submit button is clickable"
  ],
  "summary": "1 critical accessibility issue found. The login flow is functionally correct but the error state has a contrast violation."
}
```

This JSON is also rendered as a human-readable `bug-report.md` for the coding agent.

### 2.4 Coding Agent Handoff

**MVP approach — directory-based file sharing:**

```
project-root/
├── .genie-qa/
│   ├── bug-report.md          # Human-readable critique (coding agent reads this)
│   ├── bug-report.json        # Machine-readable (same data, structured)
│   ├── screenshots/
│   │   └── issue-001.png      # Annotated screenshot of the issue
│   └── status.json            # { "state": "waiting_for_fix" | "verifying" | "done" }
```

The coding agent (Gemini CLI, Cursor, Claude Code) is instructed to:
1. Read `.genie-qa/bug-report.md`.
2. Apply fixes to the codebase.
3. The dev server hot-reloads automatically.
4. Genie-QA detects the reload (via frame change detection) and re-enters VERIFYING state.

**Reload detection:** After writing the bug report, the local executor polls screenshots at 1fps. When pixel difference between consecutive frames exceeds a threshold (indicating the page reloaded/changed), it signals the agent controller to re-test.

### 2.5 System Prompts (Key Excerpts)

**Visual Execution Prompt:**
```
You are Genie-QA, a visual testing agent. You are looking at a browser window.

Your goal: {goal_text}

You can perform these actions. Respond with EXACTLY ONE action per turn as JSON:
- CLICK: {"action": "CLICK", "params": {"x": <int>, "y": <int>}, "reasoning": "<why>"}
- TYPE: {"action": "TYPE", "params": {"text": "<string>"}, "reasoning": "<why>"}
- SCROLL: {"action": "SCROLL", "params": {"x": <int>, "y": <int>, "direction": "up"|"down"}, "reasoning": "<why>"}
- WAIT: {"action": "WAIT", "params": {"duration_ms": <int>}, "reasoning": "<why>"}
- DONE: {"action": "DONE", "reasoning": "<why>"}

Rules:
- Identify UI elements by their visual appearance and position, NOT by DOM or CSS selectors.
- If you see a visual or accessibility issue (contrast, overlapping, alignment, missing states), note it—you will be asked to critique after the test flow completes.
- Be precise with coordinates. Describe what you see at each step.
```

**Critique Prompt:**
```
You have just completed a visual test of a frontend application.

Goal: {goal_text}
Observations during test: {observations_log}
Final screenshot: [attached image]

Generate a detailed QA critique in the following JSON schema: {critique_schema}

Evaluation criteria:
1. Functional correctness: Did the UI behave as expected for the test goal?
2. Visual quality: Are elements properly aligned, sized, and spaced?
3. Accessibility: Check WCAG AA compliance — contrast ratios, focus indicators, text sizing, alt text indicators.
4. Responsiveness: Are there overflow, clipping, or layout-breaking issues visible?

Be specific. Reference exact visual locations. Provide actionable fix suggestions a coding agent can execute without further clarification.
```

---

## 3. Google Cloud Run Deployment

### Container Structure

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

ENV PORT=8080
EXPOSE 8080

CMD ["python", "src/server.py"]
```

### Deployment Script (IaC — Bonus Points)

```bash
#!/bin/bash
# deploy.sh — Automated Cloud Run deployment

set -euo pipefail

PROJECT_ID="genie-qa-hackathon"
REGION="us-central1"
SERVICE_NAME="genie-qa-agent"
IMAGE="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

echo "Building container image..."
gcloud builds submit --tag "${IMAGE}" --project "${PROJECT_ID}"

echo "Deploying to Cloud Run..."
gcloud run deploy "${SERVICE_NAME}" \
  --image "${IMAGE}" \
  --region "${REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_API_KEY=${GOOGLE_API_KEY}" \
  --memory 1Gi \
  --cpu 1 \
  --timeout 300 \
  --project "${PROJECT_ID}"

echo "Deployment complete."
gcloud run services describe "${SERVICE_NAME}" --region "${REGION}" --format="value(status.url)"
```

---

## 4. Phased Build Plan

### Phase 1 — Vision Pipeline (Days 1–2)

**Goal: Prove Genie-QA can see and describe a browser window through the Live API.**

- [ ] Set up project scaffolding:
  ```
  genie-qa/
  ├── local/              # Local executor (Python)
  │   ├── executor.py     # Screen capture + action execution
  │   ├── streamer.py     # Frame streaming to Cloud Run
  │   └── requirements.txt
  ├── cloud/              # Cloud Run agent
  │   ├── server.py       # WebSocket server + Gemini API orchestration
  │   ├── agent.py        # State machine + prompt management
  │   ├── Dockerfile
  │   └── requirements.txt
  ├── deploy.sh
  └── README.md
  ```
- [ ] Implement screen capture using `mss` (grab browser window region, encode as base64 PNG).
- [ ] Connect to the Gemini Multimodal Live API via the GenAI SDK. Send a single frame, receive a description.
- [ ] Implement frame polling loop: capture → send → receive observation, at 1-2 fps.
- [ ] Create a simple test target: a local HTML page with obvious elements (buttons, forms, text) to validate that Gemini correctly identifies what it sees.
- [ ] **Milestone: Run the script, point it at a browser window, and Gemini accurately describes the page contents.**

### Phase 2 — Action Execution (Days 3–4)

**Goal: Genie-QA can navigate a web page autonomously using vision-only coordination.**

- [ ] Implement the action protocol: parse Gemini's JSON action responses into `pyautogui` calls.
  - `CLICK(x, y)` → `pyautogui.click(x, y)`
  - `TYPE(text)` → `pyautogui.typewrite(text)`
  - `SCROLL(x, y, direction)` → `pyautogui.scroll()`
  - `WAIT(ms)` → `time.sleep(ms/1000)`
- [ ] Build the action loop: send frame → receive action → execute → capture new frame → send → repeat until `DONE`.
- [ ] Write the visual execution system prompt (Section 2.5). Iterate on it with test cases.
- [ ] Create a sample "broken app" for testing: a login form with known issues (wrong error colors, overlapping elements, missing focus states).
- [ ] Handle edge cases: Gemini outputs malformed JSON, coordinates are out of bounds, action timeout.
- [ ] **Milestone: Give Genie-QA the goal "fill in the login form and submit", and it autonomously clicks the fields, types credentials, and clicks submit—all from vision.**

### Phase 3 — Critique Engine (Days 5–6)

**Goal: Genie-QA produces structured, actionable bug reports that a coding agent can directly execute on.**

- [ ] Implement the critique phase: after the action loop completes (or an issue is detected mid-flow), switch to critique mode.
- [ ] Write the critique system prompt (Section 2.5). Define the JSON schema for the output.
- [ ] Implement observation logging: during the action loop, accumulate a log of what Gemini saw and did at each step. Feed this into the critique prompt.
- [ ] Build the critique output pipeline:
  - Parse Gemini's critique response.
  - Save annotated screenshots for each issue.
  - Write `bug-report.json` and render `bug-report.md` into the `.genie-qa/` directory.
- [ ] Test against the broken sample app. Verify that the critique correctly identifies the planted bugs and the suggested fixes are actionable.
- [ ] Add WCAG-specific evaluation: prompt Gemini to check contrast ratios, focus indicators, font sizes, and touch target sizes from the visual information alone.
- [ ] **Milestone: Genie-QA tests the broken app, and outputs a `bug-report.md` that contains each planted issue with accurate descriptions and fix suggestions.**

### Phase 4 — Agent Loop & Cloud Deploy (Days 7–8)

**Goal: Full autonomous loop — Genie-QA finds bugs, coding agent fixes them, Genie-QA verifies. Deployed on Cloud Run.**

- [ ] Implement reload detection: after writing the bug report, the local executor monitors for visual changes (frame pixel diff > threshold) indicating the app hot-reloaded.
- [ ] Implement the verification flow: on reload detected, re-run the same test goal and produce a new critique. If all issues pass, output a "PASS" report.
- [ ] End-to-end loop test: start with the broken app → Genie-QA critiques → manually apply the fix → Genie-QA verifies. Then do it with a real coding agent reading the `.genie-qa/` directory.
- [ ] Dockerize the cloud component. Write `deploy.sh`. Deploy to Cloud Run.
- [ ] Verify the local executor ↔ Cloud Run ↔ Gemini API pipeline works over the network (not just localhost).
- [ ] Implement status signaling: `.genie-qa/status.json` so the coding agent knows the current state (testing, waiting_for_fix, verifying, done).
- [ ] **Milestone: Record a screen capture of the full loop running autonomously — Genie-QA finds issues, coding agent fixes them, Genie-QA confirms. Cloud Run logs show the agent state transitions.**

### Phase 5 — Polish, Demo & Content (Days 9–10)

**Goal: Demo-ready project with documentation and blog post.**

- [ ] Record the demo video: show the complete flow end-to-end with a realistic sample app (not just a toy login form—ideally something like a checkout page or dashboard).
- [ ] Write the README: installation, setup, usage, architecture diagram, demo GIF/video.
- [ ] Write the blog post (bonus points): how Genie-QA was built with Gemini, Live API, and Cloud Run. Must mention it's for the Gemini Hackathon.
- [ ] Ensure the deploy script and Dockerfile are in the public repo (bonus points for IaC).
- [ ] **Stretch: NanoBanana integration.** If time permits:
  - [ ] After critique, send the flawed screenshot to Gemini image generation with the prompt: "Generate a corrected version of this UI where {issue_description}."
  - [ ] Include the generated mockup in the bug report payload.
  - [ ] Demo the coding agent receiving both text critique and target image.
- [ ] Final cleanup: remove debug prints, add error handling, test on a clean machine.
- [ ] **Milestone: Public repo with working code, automated deploy, demo video, and blog post. All hackathon checkboxes ticked.**

---

## 5. Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| Live API latency too high for real-time feel | Demo feels sluggish | Fall back to 1fps polling; pre-record smooth sections of demo if needed |
| Gemini outputs inaccurate coordinates | Actions miss their targets | Add coordinate calibration step; use Playwright's viewport for precise window positioning; add retry logic |
| Gemini critique is too vague for coding agent | Fix loop doesn't close | Heavy prompt engineering in Phase 3; include few-shot examples of good critiques in the system prompt |
| Cloud Run cold start delays | Demo has awkward pause at start | Set min-instances=1; warm up the service before demo |
| Coding agent doesn't pick up bug report | Loop stalls | For demo, use explicit agent instructions; file watcher as backup; worst case, manual trigger |
| Live API WebSocket drops mid-test | Test flow breaks | Implement reconnection logic; fall back to single-frame `generateContent` calls |

---

## 6. Dependencies & Environment

```
# local/requirements.txt
google-genai>=1.0.0       # GenAI SDK (Gemini API + Live API)
pyautogui>=0.9.54         # Mouse/keyboard automation
mss>=9.0.0                # Fast screen capture
Pillow>=10.0.0            # Image processing
websockets>=12.0          # WebSocket client to Cloud Run
numpy>=1.26.0             # Frame diff calculation for reload detection

# cloud/requirements.txt
google-genai>=1.0.0       # GenAI SDK
fastapi>=0.110.0          # HTTP + WebSocket server
uvicorn>=0.29.0           # ASGI server
websockets>=12.0          # WebSocket handling
```

**Python version:** 3.12+
**Gemini models:** `gemini-2.5-pro` for critique quality, `gemini-2.5-flash` for action loop speed (lower latency).
**Test target:** Any locally-served frontend app (React, Next.js, plain HTML).