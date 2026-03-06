# Genie-QA
> We built the eyes for your coding agent.

---

## 1. Problem

Front-end testing is broken in three compounding ways:

1. **Fragile selectors.** DOM-based tools (Selenium, Cypress, Playwright assertions) break the moment a class name or element ID changes. Teams spend more time maintaining test scripts than writing features.
2. **Blind to what users actually see.** Traditional test runners assert against the DOM tree, not the rendered pixels. They cannot catch overlapping text, broken layouts, poor color contrast, missing focus rings, or any visual/accessibility regression that only manifests on-screen.
3. **The fix cycle is still manual.** When a test fails, a developer reads the log, context-switches into the codebase, writes a fix, re-runs the suite, and hopes it passes. Every round-trip costs minutes—often hours—and the cycle repeats for each issue.

The result: **developers either under-test their UI or waste enormous time maintaining a test suite that still misses real visual bugs.**

---

## 2. Solution

**Cerno** is a pure-vision, multimodal computer-use agent (CUA) that visually tests frontend applications, audits UI/UX quality, and autonomously guides coding agents to fix the issues it finds. 

Instead of lossy video streams, Cerno uses **high-resolution screenshots** processed by Gemini 2.5 Pro. This allows for pixel-perfect analysis, enabling the agent to catch subtle 1px misalignments, WCAG color contrast failures, and typography issues that compressed video would blur.

It acts as an **Autonomous UI Critic** that pairs directly with any coding agent (Gemini CLI, Cursor, Claude Code) to close the feedback loop from bug detection to verified fix—without human intervention.

### Core Loop

```text
Developer sets a goal
        │
        ▼
┌──────────────────┐
│ Observe & Act    │  ← Genie-QA takes a high-res screenshot, plans,
│ (Vision CUA)     │    and emits coordinate clicks/keystrokes.
└───────┬──────────┘
        │
        ▼
┌──────────────────┐
│ Critique & Report│  ← Analyzes pixels for bugs, accessibility, UX.
│ (Structured QA)  │    Outputs detailed, machine-readable critique.
└───────┬──────────┘
        │
        ▼
┌──────────────────┐
│ Autonomous Fix   │  ← Coding agent reads the critique,
│ (Coding Agent)   │    modifies the codebase.
└───────┬──────────┘
        │
        ▼
┌──────────────────┐
│ Visual Verify    │  ← App hot-reloads. Genie-QA captures a fresh
│ (Re-test Loop)   │    screenshot to verify the fix. Loop continues.
└──────────────────┘
```

---

## 3. Core Features

### 3.1 Pure-Vision Testing (No DOM Parsing)
Genie-QA never inspects the DOM. It analyzes crisp, uncompressed screenshots of the browser window using Gemini 2.5 Pro, identifying elements, reading text, and detecting layout purely from pixels—exactly like a human tester looking at a monitor.

### 3.2 Natural Language Test Goals
No test scripts to write or maintain. The developer provides a plain-English goal:
> *"Test the checkout flow with an expired credit card. Verify the error message is visible and accessible."*

Genie-QA autonomously plans the tests, steps, executes them visually, and evaluates the result.

### 3.3 High-Fidelity, Structured Critiques
Because it relies on high-res images rather than compressed video, Gemini 2.5 Pro can generate deeply insightful critiques. When issues are found, Genie-QA produces a detailed Markdown report containing the issue description, severity, precise visual coordinates, cropped screenshots of the bug, WCAG violation details, and a suggested fix—formatted for direct consumption by a coding agent.

### 3.4 Coding Agent Handoff & Autonomous Fix
The critique is handed to the paired coding agent (via shared directory or tool call). The coding agent reads the report, modifies the code, and triggers a hot-reload. No human in the loop.

### 3.5 Iterative Visual Verification
After the fix is applied and the app reloads, Genie-QA automatically takes a fresh screenshot of the new state. It cross-references the new UI against the critique and confirms if the issue is resolved. The loop only terminates when the UI passes all visual checks.

### 3.6 Generative UI Remediation (NanoBanana) — Stretch Goal
"Show, don't just tell." When Genie-QA finds an aesthetic or accessibility issue, it pipes the flawed screenshot to Gemini's image generation (NanoBanana) to produce a mockup of the corrected UI. The coding agent receives both the critique text and a target image, enabling pixel-accurate fixes.

---

## 4. Tech Stack — Built on Google

| Layer | Technology | Role |
| --- | --- | --- |
| **AI Engine** | **Gemini 2.5 Pro via Google GenAI SDK** | High-res vision reasoning, spatial action planning, complex critique generation |
| **Vision Input** | **Discrete Screenshot Loop (`mss` / `Playwright`)** | Captures pristine UI frames for pixel-perfect QA analysis |
| **Image Generation**| **Gemini Pro (NanoBanana)** — Stretch | Generates "target UI" mockups from flawed screenshots |
| **Cloud Hosting** | **Google Cloud Run** | Hosts agentic orchestration, state management, and API routing |
| **Local Executor** | Python (`pyautogui` or `Playwright` headed) | Executes Gemini's coordinate-based mouse/keyboard action tool-calls |
| **Agent Handoff** | Directory-based `.md` / JSON file sharing | Coding agent reads Genie-QA's critique and acts on it |
| **Deployment** | Dockerfile + `gcloud run deploy` script | Automated, reproducible cloud deployment (IaC bonus) |

### Why GenAI SDK over ADK?
The GenAI SDK provides direct access to standard `generateContent` endpoints, which is perfect for managing the discrete ReAct (Reason + Act) loop. It handles multimodal inputs (images + text) and structured JSON outputs (function calling for coordinates) cleanly, without the overhead of higher-level abstractions that the ADK might enforce.

---

## 5. Workflow

### Phase 1 — The Core Loop (Hackathon MVP)
1. **Goal Extraction.** Developer inputs a natural language test goal.
2. **Visual Execution.** Genie-QA captures a high-res screenshot, sends it to Gemini 2.5 Pro, and receives coordinate-based actions. The Python script executes the actions to navigate the flow.
3. **The Critique.** Upon reaching the end state (or spotting an error), Gemini evaluates the screen for functional correctness, visual quality, and accessibility, outputting a structured `bug-report.md`.
4. **The Handoff.** The coding agent picks up the report, applies fixes, and the app hot-reloads.
5. **Verification.** Genie-QA captures a fresh screenshot, re-evaluates the UI, and confirms the fix. Loop repeats until all issues pass.

### Phase 2 — Generative UI Remediation (Stretch Goal)
1. **Sub-Agent Invocation.** The coding agent calls Genie-QA programmatically as a tool: `await run_visual_tester({ url: "localhost:3000" })`.
2. **Visual Test + Image Generation.** Genie-QA tests the UI. For aesthetic/accessibility issues, it sends the screenshot to NanoBanana, which generates a corrected mockup.
3. **Structured Tool Response.** Genie-QA returns a JSON payload directly into the coding agent's context: the critique, the generated target image (base64), and a directive to match the mockup.
4. **Image-Guided Fix.** The coding agent analyzes the target image alongside its codebase and writes a visually-accurate fix.

---

## 6. Why This Wins

* **Pixel-Perfect Reasoning.** By leveraging Gemini 2.5 Pro on high-resolution images instead of compressed video, Cerno catches the subtle, real-world visual bugs that developers actually care about.
* **Novel agent architecture.** Not just another API wrapper—a multi-agent system where a vision agent and a coding agent collaborate autonomously in a closed loop.
* **Real problem, real users.** Every front-end developer has felt the pain of flaky Selenium tests and manual visual QA. Genie-QA eliminates both.
* **Deep Google stack integration.** GenAI SDK for ReAct logic, Gemini 2.5 Pro for state-of-the-art vision capabilities, Cloud Run for hosting, and Gemini Image Gen for mockups.
* **Live, verifiable demo.** The system can be demonstrated end-to-end: break a UI, watch Genie-QA find it, watch the coding agent fix it, watch Genie-QA confirm—all autonomously.

---

# Requirements

- [ ] New Concept of AI Agent
- [ ] Solve a complex problem / create new UX
- [ ] Use Gemini multimodal capability
    - Interpret screen shots/recordings
    - Output executable actions
- [ ] Agents are hosted on Google Cloud
- [ ] Agents built w/ either GenAI SDK / ADK

# Bonus Points

- [ ] Publish a piece of content
    - How was the project built?
    - Must say it’s for the hackathon
- [ ] Automate Cloud Deployment
- [x] Sign up for GDG