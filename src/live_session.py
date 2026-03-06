"""Gemini Live API session management with auto-reconnect and fallback."""

from __future__ import annotations

import asyncio
import time
import logging
from typing import Optional

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = (
    "You are Cerno, a visual testing agent. You are looking at a browser window. "
    "Describe what you see in detail: the layout, text content, buttons, forms, colors, "
    "and any visual or accessibility issues you notice. Be concise but thorough."
)

# Proactively reconnect before the 2-minute hard limit
SESSION_TTL_SECONDS = 110

LIVE_MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"
FALLBACK_MODEL = "gemini-2.5-flash"


async def run_live_session(
    api_key: str,
    frame_queue: asyncio.Queue,
    text_queue: asyncio.Queue,
    model: str = LIVE_MODEL,
):
    """Run a Live API session. Sends frames + user questions, prints responses.

    Uses AUDIO response modality with transcription since the native audio
    model requires it. Frames are sent via send_client_content with inline_data
    (send_realtime_input does not reliably deliver image data to the model).

    Automatically reconnects when the session TTL expires or on errors.
    """
    client = genai.Client(api_key=api_key)
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        output_audio_transcription={},
        system_instruction=types.Content(
            parts=[types.Part(text=SYSTEM_INSTRUCTION)]
        ),
    )

    while True:
        try:
            session_start = time.monotonic()
            logger.info("Opening Live API session (model=%s)...", model)

            async with client.aio.live.connect(model=model, config=config) as session:
                logger.info("Live API session connected")

                async def send_frames():
                    while True:
                        elapsed = time.monotonic() - session_start
                        if elapsed >= SESSION_TTL_SECONDS:
                            logger.info("Session TTL reached (%.0fs), reconnecting...", elapsed)
                            return

                        frame = await frame_queue.get()
                        msg = types.Content(parts=[
                            types.Part(
                                inline_data=types.Blob(
                                    data=frame, mime_type="image/jpeg"
                                )
                            ),
                        ])
                        await session.send_client_content(
                            turns=msg, turn_complete=False
                        )

                async def send_text():
                    while True:
                        text = await text_queue.get()
                        # Include latest frame with the question
                        parts = [types.Part(text=text)]
                        try:
                            frame = frame_queue.get_nowait()
                            parts.insert(0, types.Part(
                                inline_data=types.Blob(
                                    data=frame, mime_type="image/jpeg"
                                )
                            ))
                        except asyncio.QueueEmpty:
                            pass
                        msg = types.Content(parts=parts)
                        await session.send_client_content(
                            turns=msg, turn_complete=True
                        )

                async def receive_responses():
                    async for response in session.receive():
                        if response.server_content:
                            sc = response.server_content
                            if sc.output_transcription and sc.output_transcription.text:
                                print(sc.output_transcription.text, end="", flush=True)

                done, pending = await asyncio.wait(
                    [asyncio.ensure_future(send_frames()),
                     asyncio.ensure_future(send_text()),
                     asyncio.ensure_future(receive_responses())],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                for task in done:
                    if task.exception():
                        raise task.exception()

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("Live session error (%s), reconnecting in 1s...", e)
            await asyncio.sleep(1)


async def run_fallback_once(
    client: genai.Client,
    frame_bytes: bytes,
    model: str = FALLBACK_MODEL,
) -> Optional[str]:
    """Single-frame generateContent call (no Live API)."""
    response = await client.aio.models.generate_content(
        model=model,
        contents=[
            types.Content(
                parts=[
                    types.Part(text="Describe what you see in this screenshot in detail."),
                    types.Part(
                        inline_data=types.Blob(
                            data=frame_bytes, mime_type="image/jpeg"
                        )
                    ),
                ]
            )
        ],
    )
    if response.text:
        return response.text
    return None
