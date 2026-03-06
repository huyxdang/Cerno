"""Cerno Phase 1 — Vision Pipeline entry point.

Captures screen frames and streams them to Gemini for visual description.
"""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env before any other imports (genai reads env vars at import time)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import argparse
import asyncio
import logging
import sys
from typing import Optional

from google import genai

from capture import capture_screen
from live_session import (
    run_live_session,
    run_fallback_once,
    LIVE_MODEL,
    FALLBACK_MODEL,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cerno")


def parse_args():
    p = argparse.ArgumentParser(description="Cerno — Vision Pipeline")
    p.add_argument("--fps", type=float, default=1.0, help="Frames per second (default: 1)")
    p.add_argument("--no-live", action="store_true", help="Use generateContent fallback instead of Live API")
    p.add_argument("--model", default=None, help="Gemini model to use")
    p.add_argument(
        "--region",
        type=str,
        default=None,
        help="Screen region as top,left,width,height (e.g. 0,0,1920,1080)",
    )
    return p.parse_args()


def parse_region(region_str: Optional[str]) -> Optional[dict]:
    if not region_str:
        return None
    parts = [int(x.strip()) for x in region_str.split(",")]
    if len(parts) != 4:
        print("ERROR: --region must be top,left,width,height")
        sys.exit(1)
    return {"top": parts[0], "left": parts[1], "width": parts[2], "height": parts[3]}


async def run_fallback(api_key: str, fps: float, region: Optional[dict], model: str):
    """Polling loop using generateContent (no Live API)."""
    interval = 1.0 / fps
    client = genai.Client(api_key=api_key)
    logger.info("Running in fallback mode (generateContent) at %.1f FPS, model=%s", fps, model)

    while True:
        frame = capture_screen(region)
        logger.info("Captured frame (%d bytes), sending...", len(frame))
        try:
            description = await run_fallback_once(client, frame, model=model)
            if description:
                print(f"\n--- Description ---\n{description}\n")
        except Exception as e:
            logger.error("generateContent failed: %s", e)
        await asyncio.sleep(interval)


async def read_stdin(text_queue: asyncio.Queue):
    """Read lines from stdin in a thread and put them on the text queue."""
    loop = asyncio.get_event_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        line = line.strip()
        if line:
            await text_queue.put(line)


async def run_live(api_key: str, fps: float, region: Optional[dict], model: str):
    """Live API loop with concurrent frame capture, user input, and response streaming."""
    interval = 1.0 / fps
    logger.info("Running in Live API mode at %.1f FPS", fps)
    print("Session active. Type a question and press Enter to ask about what's on screen.")
    print("Press Ctrl+C to exit.\n")

    frame_queue = asyncio.Queue(maxsize=2)
    text_queue = asyncio.Queue()

    async def capture_loop():
        while True:
            frame = capture_screen(region)
            if frame_queue.full():
                try:
                    frame_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            await frame_queue.put(frame)
            await asyncio.sleep(interval)

    capture_task = asyncio.ensure_future(capture_loop())
    input_task = asyncio.ensure_future(read_stdin(text_queue))
    session_task = asyncio.ensure_future(
        run_live_session(api_key, frame_queue, text_queue, model=model)
    )

    try:
        await asyncio.gather(capture_task, input_task, session_task)
    except asyncio.CancelledError:
        pass
    finally:
        capture_task.cancel()
        input_task.cancel()
        session_task.cancel()


async def main():
    args = parse_args()

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("ERROR: GOOGLE_API_KEY environment variable is not set.")
        print("Set it with: export GOOGLE_API_KEY=your_key_here")
        sys.exit(1)

    region = parse_region(args.region)

    if args.no_live:
        model = args.model or FALLBACK_MODEL
        await run_fallback(api_key, args.fps, region, model)
    else:
        model = args.model or LIVE_MODEL
        try:
            await run_live(api_key, args.fps, region, model)
        except Exception as e:
            logger.warning("Live API failed (%s), falling back to generateContent", e)
            await run_fallback(api_key, args.fps, region, args.model or FALLBACK_MODEL)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting gracefully.")
