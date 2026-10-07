"""Turn a trending sports topic into a spoken script plus an Instagram caption."""

import json
import re

import config
from trends import Trend

# ~2.6 words per second is a realistic pace for a synthetic presenter voice.
WORDS_PER_SECOND = 2.6

SYSTEM = """You write scripts for a short daily sports news Reel delivered to camera \
by a single presenter.

Rules for the script:
- Spoken words only. No scene directions, no speaker labels, no emoji, no hashtags,
  no markdown. Every character you write will be read aloud.
- Open with a hook in the first sentence that earns the next three seconds.
- Stick to what the supplied headlines actually support. If a detail is not in the
  brief, leave it out rather than guessing a score, a stat or a quote.
- Attribute anything contested: "reports suggest", "according to early coverage".
- Close with one line inviting a reply or an opinion.
- Conversational Indian English. Short sentences. No cliches like "buckle up" or
  "let that sink in".

Rules for the caption:
- Two short lines, then 4-6 relevant hashtags.

Return ONLY a JSON object, no prose and no code fences:
{"script": "...", "caption": "...", "headline": "..."}
where "headline" is a 6-word-max description of the story for internal logging."""


def _target_words() -> int:
    return int(config.TARGET_SECONDS * WORDS_PER_SECOND)


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object in model output: {text[:300]}")
    return json.loads(text[start : end + 1])


def generate(trend: Trend) -> dict:
    """Return {'script', 'caption', 'headline'} for one trend."""
    import anthropic  # lazy so the length/JSON helpers are testable standalone

    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    words = _target_words()

    prompt = (
        f"{trend.context}\n\n"
        f"Write the script to run about {config.TARGET_SECONDS} seconds when spoken, "
        f"which is roughly {words} words. Do not exceed {words + 15} words."
    )

    msg = client.messages.create(
        model=config.SCRIPT_MODEL,
        max_tokens=1200,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in msg.content if block.type == "text")
    data = _extract_json(text)

    for key in ("script", "caption", "headline"):
        if not data.get(key):
            raise ValueError(f"Model response missing '{key}'")

    data["script"] = _enforce_length(data["script"])
    data["estimated_seconds"] = round(len(data["script"].split()) / WORDS_PER_SECOND, 1)
    return data


def _enforce_length(script: str) -> str:
    """Hard guard against overruns -- the Instagram API rejects Reels over 90s."""
    cap = int(85 * WORDS_PER_SECOND)
    words = script.split()
    if len(words) <= cap:
        return script.strip()
    truncated = " ".join(words[:cap])
    # cut back to the last sentence boundary so it does not stop mid-thought
    last = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"))
    return (truncated[: last + 1] if last > 0 else truncated).strip()
