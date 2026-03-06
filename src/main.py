"""Cerno Phase 1 — Vision Pipeline entry point.

Captures screen frames and streams them to Gemini for visual description.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from typing import Optional

from capture import capture_screen
from live_session import GeminiSession

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cerno")


def parse_args():
    p = argparse.ArgumentParser(description="Cerno — Vision Pipeline")
    p.add_argument("--fps", type=float, default=1.0, help="Frames per second (default: 1)")
    p.add_argument("--no-live", action="store_true", help="Use generateContent fallback instead of Live API")
    p.add_argument("--model", default="gemini-live-2.5-flash-preview", help="Gemini model to use")
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


async def run_fallback(session: GeminiSession, fps: float, region: Optional[dict]):
    """Polling loop using generateContent (no Live API)."""
    interval = 1.0 / fps
    logger.info("Running in fallback mode (generateContent) at %.1f FPS", fps)

    while True:
        frame = capture_screen(region)
        logger.info("Captured frame (%d bytes), sending...", len(frame))
        try:
            description = await session.generate_content_fallback(frame)
            if description:
                print(f"\n--- Description ---\n{description}\n")
        except Exception as e:
            logger.error("generateContent failed: %s", e)
        await asyncio.sleep(interval)


async def run_live(session: GeminiSession, fps: float, region: Optional[dict]):
    """Live API loop using asyncio.TaskGroup for concurrent send/receive."""
    interval = 1.0 / fps
    logger.info("Running in Live API mode at %.1f FPS", fps)

    await session.connect()

    stop_event = asyncio.Event()

    async def send_frames():
        while not stop_event.is_set():
            frame = capture_screen(region)
            try:
                await session.send_frame(frame)
            except Exception as e:
                logger.error("Failed to send frame: %s", e)
                # Session will auto-reconnect on next send
            await asyncio.sleep(interval)

    async def receive_responses():
        while not stop_event.is_set():
            try:
                async for text in session.receive_responses():
                    print(text, end="", flush=True)
                # Generator ended (disconnect/error) — pause before retry
                # Session reconnect happens in send_frame
                await asyncio.sleep(1)
            except Exception as e:
                logger.warning("Receive loop error: %s", e)
                await asyncio.sleep(1)

    try:
        await asyncio.gather(send_frames(), receive_responses())
    except asyncio.CancelledError:
        pass
    finally:
        stop_event.set()
        await session.disconnect()


async def main():
    args = parse_args()

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("ERROR: GOOGLE_API_KEY environment variable is not set.")
        print("Set it with: export GOOGLE_API_KEY=your_key_here")
        sys.exit(1)

    region = parse_region(args.region)
    session = GeminiSession(api_key=api_key, model=args.model)

    if args.no_live:
        await run_fallback(session, args.fps, region)
    else:
        try:
            await run_live(session, args.fps, region)
        except Exception as e:
            logger.warning("Live API failed (%s), falling back to generateContent", e)
            await run_fallback(session, args.fps, region)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting gracefully.")
