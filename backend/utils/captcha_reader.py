"""Iter 96h — AI-vision captcha reader for government portals (EPFO / ESIC).

These portals use simple distorted *text* captchas (alphanumeric), NOT
Google reCAPTCHA — so a vision LLM reads them reliably. Uses the Emergent
Universal LLM key (OpenAI vision, gpt-5.4) — the SAME key the OCR module
already uses, so there is no extra credential to configure.

Public API:
    await read_captcha(image_base64, hint=...) -> str   # cleaned captcha text
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

logger = logging.getLogger("captcha_reader")


def _clean(text: str, alphanumeric_only: bool = True) -> str:
    text = (text or "").strip()
    # Model sometimes wraps in quotes / says "The captcha is: ABCD".
    m = re.search(r"[:=]\s*([A-Za-z0-9]{3,12})\s*$", text)
    if m:
        text = m.group(1)
    text = text.strip().strip('"').strip("'").strip()
    if alphanumeric_only:
        text = re.sub(r"[^A-Za-z0-9]", "", text)
    return text


async def read_captcha(
    image_base64: str,
    *,
    hint: str = "",
    numeric_only: bool = False,
    session_id: str = "captcha",
) -> Optional[str]:
    """Read the text shown in a captcha image. Returns the cleaned string
    (letters/digits) or None if the reader is unavailable / fails."""
    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        logger.warning("[captcha] EMERGENT_LLM_KEY not set — cannot read captcha")
        return None

    if "," in image_base64 and image_base64.startswith("data:"):
        image_base64 = image_base64.split(",", 1)[1]

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent
    except Exception as exc:  # noqa: BLE001
        logger.warning("[captcha] emergentintegrations unavailable: %s", exc)
        return None

    charset = "digits (0-9)" if numeric_only else "letters and digits (A-Z, a-z, 0-9)"
    system_prompt = (
        "You are a precise captcha OCR engine. You are shown a single "
        "distorted-text captcha image from an Indian government portal. "
        "Read the characters EXACTLY as shown. Respond with ONLY the "
        "characters — no words, no spaces, no punctuation, no explanation. "
        f"The captcha uses {charset}. Preserve upper/lower case exactly."
    )
    user_text = "Read this captcha and output only its characters."
    if hint:
        user_text += f" Hint: {hint}"

    chat = LlmChat(
        api_key=api_key,
        session_id=f"captcha-{session_id}",
        system_message=system_prompt,
    ).with_model("openai", "gpt-5.4")

    try:
        response = await chat.send_message(
            UserMessage(text=user_text, file_contents=[ImageContent(image_base64=image_base64)])
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[captcha] LLM read failed: %s", exc)
        return None

    text = _clean(response or "", alphanumeric_only=True)
    if numeric_only:
        text = re.sub(r"[^0-9]", "", text)
    if not text or len(text) < 3:
        logger.info("[captcha] unusable read: %r", response)
        return None
    logger.info("[captcha] read %d chars", len(text))
    return text
