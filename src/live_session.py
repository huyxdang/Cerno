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
    "You are Genie-QA, a visual testing agent. You are looking at a browser window. "
    "Describe what you see in detail: the layout, text content, buttons, forms, colors, "
    "and any visual or accessibility issues you notice. Be concise but thorough."
)

# Proactively reconnect before the 2-minute hard limit
SESSION_TTL_SECONDS = 110


class GeminiSession:
    """Manages a Gemini Live API connection with auto-reconnect and fallback."""

    def __init__(self, api_key: str, model: str = "gemini-live-2.5-flash-preview"):
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._session = None
        self._session_start: float = 0
        self._lock = asyncio.Lock()
        self._connected = False

    async def connect(self) -> None:
        """Open a Live API session."""
        config = types.LiveConnectConfig(
            response_modalities=["TEXT"],
            system_instruction=types.Content(
                parts=[types.Part(text=SYSTEM_INSTRUCTION)]
            ),
        )
        self._session = await self._client.aio.live.connect(
            model=self._model, config=config
        ).__aenter__()
        self._session_start = time.monotonic()
        self._connected = True
        logger.info("Live API session connected (model=%s)", self._model)

    async def disconnect(self) -> None:
        """Close the current session."""
        if self._session:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception:
                pass
            self._session = None
            self._connected = False
            logger.info("Live API session disconnected")

    async def reconnect(self) -> None:
        """Close and reopen the session (handles 2-min limit)."""
        logger.info("Reconnecting Live API session...")
        await self.disconnect()
        await self.connect()

    def _session_expired(self) -> bool:
        return (time.monotonic() - self._session_start) >= SESSION_TTL_SECONDS

    async def send_frame(self, frame_bytes: bytes) -> None:
        """Send a JPEG frame to the Live API session.

        Auto-reconnects if the session TTL has expired.
        """
        async with self._lock:
            if not self._connected or self._session_expired():
                await self.reconnect()

            blob = types.Blob(data=frame_bytes, mime_type="image/jpeg")
            try:
                await self._session.send_realtime_input(media=blob)
            except Exception as e:
                logger.warning("send_frame failed (%s), reconnecting...", e)
                await self.reconnect()
                await self._session.send_realtime_input(media=blob)

    async def receive_responses(self):
        """Async generator that yields text responses from the Live API session."""
        while self._connected and self._session:
            try:
                async for response in self._session.receive():
                    if response.text is not None:
                        yield response.text
            except Exception as e:
                if not self._connected:
                    return
                logger.warning("receive error (%s), will reconnect on next send", e)
                return

    async def generate_content_fallback(self, frame_bytes: bytes) -> Optional[str]:
        """Fallback: single-frame generateContent call (no Live API)."""
        # For fallback, use the non-live model variant
        fallback_model = self._model
        for live_suffix in ("-live-001", "-live-preview"):
            if live_suffix in fallback_model:
                fallback_model = fallback_model.replace(live_suffix, "")
        if "live" in fallback_model:
            fallback_model = "gemini-2.5-flash"

        response = await self._client.aio.models.generate_content(
            model=fallback_model,
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
