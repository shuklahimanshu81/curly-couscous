"""Render a Reel locally: neural voiceover + word-synced captions over motion graphics.

No avatar service, no stock footage, no licensed music. Everything on screen is
drawn here, which keeps the video free of copyright risk.

Pipeline:
  1. edge-tts speaks the script and reports when each word starts and ends.
  2. Words are grouped into short caption chunks (2-3 words, broken at punctuation).
  3. Each frame is drawn with numpy + Pillow: drifting gradient background, a
     "trending" header with the topic, the active caption chunk with the spoken
     word highlighted, and a progress bar.
  4. Raw frames are piped into ffmpeg and muxed with the voiceover as H.264/AAC,
     which is what Instagram and YouTube both want.

edge-tts talks to the same speech endpoint the Edge browser's Read Aloud uses. It
is free and needs no key, but it is not an official API, so it can change without
notice. tts() is the only function that touches it; swap in Google Cloud TTS or
ElevenLabs there if it ever breaks.
"""

import asyncio
import math
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import config

W, H, FPS = 1080, 1920, 30
FONT_DIR = Path(config.REPO_ROOT) / "assets" / "fonts"
DISPLAY_FONT = FONT_DIR / "Anton-Regular.ttf"
UI_FONT = FONT_DIR / "Inter.ttf"

# palette
BG_TOP = np.array([12, 16, 34], dtype=np.float32)
BG_BOTTOM = np.array([4, 5, 12], dtype=np.float32)
GLOW_A = np.array([235, 60, 70], dtype=np.float32)    # warm red
GLOW_B = np.array([40, 110, 255], dtype=np.float32)   # electric blue
WHITE = (255, 255, 255, 255)
HIGHLIGHT = (255, 214, 0, 255)                         # caption highlight yellow
ACCENT = (235, 60, 70, 255)
MUTED = (200, 205, 220, 255)

CAPTION_MAX_W = 940
CAPTION_Y = 1030           # vertical centre of the caption block
POP_FRAMES = 4             # caption entrance animation length


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Chunk:
    words: list[Word]
    start: float
    end: float


# --------------------------------------------------------------------------
# 1. voice
# --------------------------------------------------------------------------

def tts(script: str, out_path: Path) -> list[Word]:
    """Synthesize speech to out_path; return per-word timings in seconds."""
    import edge_tts

    async def _run() -> list[Word]:
        comm = edge_tts.Communicate(
            script,
            voice=config.TTS_VOICE,
            rate=config.TTS_RATE,
            boundary="WordBoundary",
        )
        words: list[Word] = []
        with open(out_path, "wb") as fh:
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    fh.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    start = chunk["offset"] / 1e7          # 100-ns ticks -> s
                    dur = chunk["duration"] / 1e7
                    words.append(Word(chunk["text"], start, start + dur))
        return words

    words = asyncio.run(_run())
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError("edge-tts returned no audio")
    return words


def audio_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def estimate_timings(script: str, duration: float) -> list[Word]:
    """Fallback when the TTS gives no word boundaries: spread words by length."""
    tokens = script.split()
    weights = [len(t) + 2 for t in tokens]
    total = sum(weights)
    t, words = 0.15, []
    span = max(duration - 0.3, 0.5)
    for tok, w in zip(tokens, weights):
        d = span * w / total
        words.append(Word(tok, t, t + d))
        t += d
    return words


# --------------------------------------------------------------------------
# 2. caption chunks
# --------------------------------------------------------------------------

_STRIP = re.compile(r"[^\w'%&\-.]", re.UNICODE)


def _norm(s: str) -> str:
    return re.sub(r"[^\w]", "", s.lower())


def attach_punctuation(words: list[Word], script: str) -> list[Word]:
    """Boundary events usually drop punctuation. Re-align against the script
    tokens so chunks can break at commas and full stops."""
    tokens = script.split()
    ti = 0
    out = []
    for w in words:
        target = _norm(w.text)
        match = None
        for j in range(ti, min(ti + 4, len(tokens))):
            if _norm(tokens[j]).startswith(target) or target.startswith(_norm(tokens[j])):
                match = j
                break
        if match is not None and target:
            out.append(Word(tokens[match], w.start, w.end))
            ti = match + 1
        else:
            out.append(w)
    return out


def build_chunks(words: list[Word], total: float, max_words: int = 3,
                 max_chars: int = 18) -> list[Chunk]:
    chunks: list[Chunk] = []
    cur: list[Word] = []
    for w in words:
        cur.append(w)
        text_len = sum(len(x.text) for x in cur) + len(cur) - 1
        ends_clause = w.text.rstrip("\"'”’").endswith((".", ",", "!", "?", ";", ":"))
        if len(cur) >= max_words or text_len >= max_chars or ends_clause:
            chunks.append(Chunk(cur, cur[0].start, cur[-1].end))
            cur = []
    if cur:
        chunks.append(Chunk(cur, cur[0].start, cur[-1].end))

    # each chunk stays on screen until the next one starts, so there are no gaps
    for i, c in enumerate(chunks):
        c.end = chunks[i + 1].start if i + 1 < len(chunks) else total
    if chunks:
        chunks[0].start = 0.0
    return chunks


def display(word: str) -> str:
    return _STRIP.sub("", word).strip(".-").upper() or word.upper()


# --------------------------------------------------------------------------
# 3. drawing
# --------------------------------------------------------------------------

def _font(path: Path, size: int, weight: str | None = None) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(path), size)
    if weight:
        try:
            f.set_variation_by_name(weight)
        except Exception:
            pass
    return f


def _wrap(words: list[str], font, max_w: int, space: float) -> list[list[int]]:
    """Greedy line wrap; returns word indices per line."""
    lines, cur, cur_w = [], [], 0.0
    for i, w in enumerate(words):
        ww = font.getlength(w)
        add = ww if not cur else cur_w + space + ww
        if cur and add > max_w:
            lines.append(cur)
            cur, cur_w = [i], ww
        else:
            cur.append(i)
            cur_w = add
    if cur:
        lines.append(cur)
    return lines


def render_caption(texts: list[str], active: int) -> Image.Image:
    """One caption state as a transparent RGBA layer, sized to fit."""
    fitted = None
    for max_lines, sizes in ((1, (150, 138, 126, 116)), (2, (140, 126, 112, 100, 90))):
        for size in sizes:
            font = _font(DISPLAY_FONT, size)
            space = font.getlength(" ") * 1.1
            lines = _wrap(texts, font, CAPTION_MAX_W, space)
            if len(lines) <= max_lines:
                fitted = (size, font, space, lines)
                break
        if fitted:
            break
    if not fitted:
        fitted = (size, font, space, lines[:2])
    size, font, space, lines = fitted

    stroke = max(6, size // 16)
    line_h = int(size * 1.08)
    pad = stroke * 3
    layer = Image.new("RGBA", (W, line_h * len(lines) + pad * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    for li, ln in enumerate(lines):
        line_w = sum(font.getlength(texts[i]) for i in ln) + space * (len(ln) - 1)
        x = (W - line_w) / 2
        y = pad + li * line_h
        for i in ln:
            fill = HIGHLIGHT if i == active else WHITE
            # soft shadow, then stroked text
            draw.text((x + 6, y + 8), texts[i], font=font, fill=(0, 0, 0, 140))
            draw.text((x, y), texts[i], font=font, fill=fill,
                      stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
            x += font.getlength(texts[i]) + space
    return layer


def render_header(topic: str) -> Image.Image:
    """Static top block: TRENDING IN SPORTS pill + the topic."""
    layer = Image.new("RGBA", (W, 520), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    pill_font = _font(UI_FONT, 34, "Bold")
    label = "TRENDING IN SPORTS"
    tw = pill_font.getlength(label)
    px, py, ph = 70, 40, 66
    draw.rounded_rectangle((px, py, px + tw + 76, py + ph), radius=ph // 2, fill=ACCENT)
    draw.ellipse((px + 24, py + 25, px + 40, py + 41), fill=WHITE)  # live dot
    draw.text((px + 52, py + 14), label, font=pill_font, fill=WHITE)

    title = topic.upper()
    for size in (104, 92, 82, 72, 64):
        font = _font(DISPLAY_FONT, size)
        words = title.split()
        lines = _wrap(words, font, W - 140, font.getlength(" "))
        if len(lines) <= 2:
            break
    lines = lines[:2]
    y = py + ph + 34
    for ln in lines:
        draw.text((70, y), " ".join(words[i] for i in ln), font=font, fill=WHITE)
        y += int(size * 1.1)

    # accent rule under the title
    draw.rectangle((70, y + 26, 190, y + 34), fill=HIGHLIGHT)
    return layer


def render_footer(handle: str) -> Image.Image:
    layer = Image.new("RGBA", (W, 140), (0, 0, 0, 0))
    if handle:
        draw = ImageDraw.Draw(layer)
        font = _font(UI_FONT, 36, "SemiBold")
        tw = font.getlength(handle)
        draw.text(((W - tw) / 2, 74), handle, font=font, fill=MUTED)
    return layer


class Background:
    """Vertical gradient with two slow-drifting colour glows."""

    def __init__(self):
        t = np.linspace(0, 1, H, dtype=np.float32)[:, None]
        self.base = (BG_TOP * (1 - t) + BG_BOTTOM * t)[:, None, :].repeat(W, axis=1)
        r = 760
        yy, xx = np.mgrid[-r:r, -r:r].astype(np.float32)
        d2 = (xx**2 + yy**2) / r**2
        blob = np.exp(-d2 / (2 * 0.36**2)) * np.clip(1 - d2, 0, 1) ** 2
        self.blob, self.r = blob[..., None], r

    def _add(self, img, cx, cy, color, strength):
        r = self.r
        x0, y0 = int(cx - r), int(cy - r)
        x1, y1 = x0 + 2 * r, y0 + 2 * r
        sx0, sy0 = max(0, -x0), max(0, -y0)
        dx0, dy0 = max(0, x0), max(0, y0)
        dx1, dy1 = min(W, x1), min(H, y1)
        if dx1 <= dx0 or dy1 <= dy0:
            return
        patch = self.blob[sy0:sy0 + (dy1 - dy0), sx0:sx0 + (dx1 - dx0)]
        img[dy0:dy1, dx0:dx1] += patch * color * strength

    def frame(self, t: float) -> np.ndarray:
        img = self.base.copy()
        self._add(img, W * (0.25 + 0.18 * math.sin(t * 0.35)),
                  H * (0.30 + 0.08 * math.cos(t * 0.27)), GLOW_A, 0.42)
        self._add(img, W * (0.78 + 0.15 * math.cos(t * 0.31)),
                  H * (0.72 + 0.07 * math.sin(t * 0.23)), GLOW_B, 0.38)
        return np.clip(img, 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------
# 4. compose + encode
# --------------------------------------------------------------------------

def compose(words: list[Word], audio: Path, topic: str, out: Path,
            duration: float | None = None) -> Path:
    total = (duration or audio_duration(audio)) + 0.6     # short tail after the last word
    chunks = build_chunks(words, total)
    n_frames = int(math.ceil(total * FPS))

    bg = Background()
    header = render_header(topic)
    footer = render_footer(config.CHANNEL_HANDLE)
    cache: dict[tuple[int, int], Image.Image] = {}

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
        "-i", "-",
        "-i", str(audio),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-profile:v", "high",
        "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
        "-af", "apad",                     # silence under the tail frames
        "-t", f"{total:.3f}",
        "-movflags", "+faststart",
        str(out),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    ci = 0
    try:
        for f in range(n_frames):
            t = f / FPS
            while ci + 1 < len(chunks) and t >= chunks[ci + 1].start:
                ci += 1
            frame = Image.fromarray(bg.frame(t))
            frame.paste(header, (0, 120), header)
            frame.paste(footer, (0, H - 220), footer)

            if chunks:
                ch = chunks[ci]
                active = 0
                for k, w in enumerate(ch.words):
                    if t >= w.start:
                        active = k
                key = (ci, active)
                if key not in cache:
                    cache[key] = render_caption([display(w.text) for w in ch.words], active)
                cap = cache[key]

                # quick scale-up "pop" as each new chunk lands
                since = t - ch.start
                if 0 <= since < POP_FRAMES / FPS:
                    s = 0.86 + 0.14 * (since * FPS / POP_FRAMES)
                    cap = cap.resize((int(cap.width * s), int(cap.height * s)),
                                     Image.BILINEAR)
                frame.paste(cap, ((W - cap.width) // 2, CAPTION_Y - cap.height // 2), cap)

            # progress bar
            d = ImageDraw.Draw(frame)
            d.rectangle((0, H - 14, W, H), fill=(255, 255, 255, 30))
            d.rectangle((0, H - 14, int(W * min(t / total, 1.0)), H), fill=HIGHLIGHT)

            proc.stdin.write(frame.tobytes())
    finally:
        proc.stdin.close()
        rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"ffmpeg exited with {rc}")

    # drop old caption layers held across chunks
    cache.clear()
    return out


def render(script: str, topic: str, out_path: Path) -> Path:
    """Full pipeline: script text in, finished MP4 out."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not installed")
    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / "voice.mp3"
        words = tts(script, audio)
        duration = audio_duration(audio)
        if words:
            words = attach_punctuation(words, script)
        else:
            words = estimate_timings(script, duration)
        return compose(words, audio, topic, out_path, duration)
