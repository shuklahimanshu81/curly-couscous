"""Render a scene-by-scene story Reel from a JSON spec.

    python story.py ../stories/may-lee-antarctica.json --out reel.mp4
    python story.py SPEC --out reel.mp4 --fake-audio    # no network, for layout checks

Each scene has its own voiceover line, on-screen text and illustration(s). Scene
length follows the voiceover: the narrator never gets cut off and never trails
into dead air, so the timestamps in a written script are a guide, not a contract.
"""

import argparse
import json
import math
import random
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import art
import config
import video
from video import Word

W, H, FPS = 1080, 1920, 30
GAP = 0.35            # breath between scenes
TAIL = 0.9            # hold on the last frame
TEXT_Y = 300          # top of the on-screen text card
CAPTION_Y = 1560      # centre of the voiceover captions
SNOWFLAKE = "❄"


# --------------------------------------------------------------------------
# audio
# --------------------------------------------------------------------------

def scene_audio(scenes, tmp: Path, fake: bool):
    """Voice each scene; return per-scene (wav path, duration, words)."""
    out = []
    for i, sc in enumerate(scenes):
        mp3 = tmp / f"vo_{i}.mp3"
        if fake:
            dur = max(len(sc["vo"].split()) / 2.7, 1.5)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                            "-i", f"sine=frequency={160 + 20 * i}:duration={dur}",
                            "-af", "volume=0.04", str(mp3)], check=True)
            words = video.estimate_timings(sc["vo"], dur)
        else:
            words = video.tts(sc["vo"], mp3)
            dur = video.audio_duration(mp3)
            words = (video.attach_punctuation(words, sc["vo"]) if words
                     else video.estimate_timings(sc["vo"], dur))
        out.append((mp3, dur, words))
    return out


def stitch_audio(parts, durations, tmp: Path) -> Path:
    """Pad every scene's voice to its scene length, then concatenate."""
    padded = []
    for i, ((mp3, _, _), d) in enumerate(zip(parts, durations)):
        wav = tmp / f"pad_{i}.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3),
                        "-af", f"apad=whole_dur={d:.3f},atrim=0:{d:.3f}",
                        "-ar", "44100", "-ac", "1", str(wav)], check=True)
        padded.append(wav)
    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in padded))
    full = tmp / "voice.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(full)], check=True)
    return full


# --------------------------------------------------------------------------
# overlays
# --------------------------------------------------------------------------

def draw_snowflake(d, cx, cy, r, color, width):
    for k in range(6):
        a = math.radians(k * 60 + 90)
        x2, y2 = cx + r * math.cos(a), cy - r * math.sin(a)
        d.line((cx, cy, x2, y2), fill=color, width=width)
        for frac in (0.55,):
            bx, by = cx + r * frac * math.cos(a), cy - r * frac * math.sin(a)
            for s in (-1, 1):
                b = a + s * math.radians(40)
                d.line((bx, by, bx + r * .35 * math.cos(b), by - r * .35 * math.sin(b)),
                       fill=color, width=width)


def text_card(text: str) -> Image.Image:
    """Scene's on-screen text: bold caps on a dark rounded card."""
    flake = SNOWFLAKE in text
    clean = text.replace("\ufe0f", "").replace(SNOWFLAKE, "").strip().upper()
    clean = clean.replace('"', "\u201c", 1).replace('"', "\u201d", 1)
    max_w = 900
    # Prefer one sentence per line ("LESS MONEY." / "MORE LIFE.") over a greedy wrap.
    import re as _re
    sentences = [s for s in _re.split(r"(?<=[.!?])\s+", clean) if s]
    texts = None
    if 1 < len(sentences) <= 2:
        for size in (104, 94, 84, 76, 68):
            font = ImageFont.truetype(str(video.DISPLAY_FONT), size)
            room = max_w - (size if flake else 0)
            if all(font.getlength(s) <= room for s in sentences):
                texts = sentences
                break
    if texts is None:
        for size in (104, 94, 84, 76, 68):
            font = ImageFont.truetype(str(video.DISPLAY_FONT), size)
            lines = video._wrap(clean.split(), font, max_w - (size if flake else 0),
                                font.getlength(" "))
            if len(lines) <= 2:
                break
        words = clean.split()
        texts = [" ".join(words[i] for i in ln) for ln in lines]
    line_h = int(size * 1.12)
    widths = [font.getlength(t) for t in texts]
    extra = int(size * 0.95) if flake else 0
    cw = int(max(widths[:-1] + [widths[-1] + extra])) + 96
    ch = line_h * len(texts) + 70
    layer = Image.new("RGBA", (W, ch + 40), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x0 = (W - cw) // 2
    d.rounded_rectangle((x0, 20, x0 + cw, 20 + ch), 34, fill=(10, 12, 20, 238))
    d.rectangle((x0 + 34, 20, x0 + 140, 30), fill=video.HIGHLIGHT)
    y = 20 + 36
    for i, t in enumerate(texts):
        tw = widths[i] + (extra if (flake and i == len(texts) - 1) else 0)
        x = (W - tw) / 2
        d.text((x, y), t, font=font, fill=(255, 255, 255, 255))
        if flake and i == len(texts) - 1:
            draw_snowflake(d, x + widths[i] + extra * 0.58, y + size * 0.62,
                           size * 0.36, (150, 210, 255, 255), max(5, size // 14))
        y += line_h
    return layer


class Snow:
    def __init__(self, n=140, seed=3):
        rng = random.Random(seed)
        self.p = [(rng.uniform(0, W), rng.uniform(0, H), rng.uniform(2.5, 7.5),
                   rng.uniform(40, 120), rng.uniform(0, 6.28)) for _ in range(n)]

    def draw(self, d, t):
        for x, y, r, speed, ph in self.p:
            yy = (y + speed * t) % H
            xx = (x + 26 * math.sin(t * 0.7 + ph)) % W
            d.ellipse((xx - r, yy - r, xx + r, yy + r), fill=(255, 255, 255, 200))


def bottom_shade() -> Image.Image:
    """Darken the lower third so captions stay legible on white snow."""
    h = 760
    a = (np.linspace(0, 1, h) ** 1.6 * 175).astype(np.uint8)
    arr = np.zeros((h, W, 4), np.uint8)
    arr[..., 3] = a[:, None]
    return Image.fromarray(arr, "RGBA")


def caption_layer(texts, active):
    """Voiceover captions: same style as the trend Reels, a size smaller."""
    for size in (98, 90, 82, 74, 66):
        font = ImageFont.truetype(str(video.DISPLAY_FONT), size)
        space = font.getlength(" ") * 1.1
        lines = video._wrap(texts, font, 940, space)
        if len(lines) <= 2:
            break
    stroke = max(5, size // 15)
    line_h = int(size * 1.1)
    layer = Image.new("RGBA", (W, line_h * len(lines) + 40), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for li, ln in enumerate(lines):
        lw = sum(font.getlength(texts[i]) for i in ln) + space * (len(ln) - 1)
        x = (W - lw) / 2
        for i in ln:
            fill = video.HIGHLIGHT if i == active else (255, 255, 255, 255)
            d.text((x, 20 + li * line_h), texts[i], font=font, fill=fill,
                   stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
            x += font.getlength(texts[i]) + space
    return layer


# --------------------------------------------------------------------------
# render
# --------------------------------------------------------------------------

def render(spec: dict, out: Path, fake_audio: bool = False) -> Path:
    scenes = spec["scenes"]
    if spec.get("voice"):
        config.TTS_VOICE = spec["voice"]
    if spec.get("rate"):
        config.TTS_RATE = spec["rate"]

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        parts = scene_audio(scenes, tmp, fake_audio)
        durs = [d + GAP for _, d, _ in parts]
        durs[-1] += TAIL
        audio = stitch_audio(parts, durs, tmp)

        starts = np.cumsum([0] + durs[:-1]).tolist()
        total = sum(durs)
        n_frames = int(math.ceil(total * FPS))

        # global word list with absolute times, grouped into caption chunks per scene
        scene_chunks = []
        for (mp3, d, words), s0, sd in zip(parts, starts, durs):
            shifted = [Word(w.text, w.start + s0, w.end + s0) for w in words]
            chunks = video.build_chunks(shifted, s0 + sd, max_words=3, max_chars=20)
            if chunks:
                chunks[0].start = s0
            scene_chunks.append(chunks)

        # pre-render every scene's artwork and text card once
        bases = {}
        for sc in scenes:
            for v in sc["visuals"]:
                if v["art"] not in bases:
                    bases[v["art"]] = art.SCENES[v["art"]]["base"]()
        cards = [text_card(sc["text"]) if sc.get("text") else None for sc in scenes]
        shade = bottom_shade()
        snow = Snow()
        cap_cache = {}

        cmd = ["ffmpeg", "-y", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
               "-i", "-", "-i", str(audio),
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-pix_fmt", "yuv420p", "-profile:v", "high",
               "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
               "-t", f"{total:.3f}", "-movflags", "+faststart", str(out)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

        si = 0
        prev_visual = None
        try:
            for f in range(n_frames):
                t = f / FPS
                while si + 1 < len(scenes) and t >= starts[si + 1]:
                    si += 1
                sc = scenes[si]
                lt = t - starts[si]
                p = lt / durs[si]

                # which visual within the scene (supports a mid-scene hard cut)
                vi = 0
                for k, v in enumerate(sc["visuals"]):
                    vi = k
                    if p < v.get("until", 1.0):
                        break
                vis = sc["visuals"][vi]
                lo = sc["visuals"][vi - 1].get("until", 0.0) if vi else 0.0
                hi = vis.get("until", 1.0)
                vp = (p - lo) / max(hi - lo, 1e-6)
                spec_art = art.SCENES[vis["art"]]

                canvas = bases[vis["art"]]
                if "dynamic" in spec_art:
                    canvas = canvas.copy()
                    spec_art["dynamic"](canvas, vp, t)

                # slow push-in, alternating pan direction scene to scene
                z = 1.0 + 0.07 * vp
                cw, ch = art.CW / z, art.CH / z
                direction = 1 if (si + vi) % 2 == 0 else -1
                cx = art.CW / 2 + direction * (art.CW - cw) / 2 * 0.7
                cy = art.CH / 2 - (art.CH - ch) / 2 * 0.3
                box = (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)
                frame = canvas.resize((W, H), Image.BILINEAR, box=box).convert("RGBA")

                d = ImageDraw.Draw(frame)
                if spec_art.get("snow"):
                    snow.draw(d, t)

                frame.alpha_composite(shade, (0, H - shade.height))

                # on-screen text card: slides up and fades in
                card = cards[si]
                if card is not None and lt > 0.25:
                    k = min((lt - 0.25) / 0.3, 1.0)
                    ease = 1 - (1 - k) ** 3
                    c = card
                    if ease < 1:
                        c = card.copy()
                        c.putalpha(Image.eval(c.split()[3], lambda a: int(a * ease)))
                    frame.alpha_composite(c, (0, int(TEXT_Y + 40 * (1 - ease))))

                # captions
                chunks = scene_chunks[si]
                if chunks:
                    ci = 0
                    for k2, chk in enumerate(chunks):
                        if t >= chk.start:
                            ci = k2
                    chk = chunks[ci]
                    active = 0
                    for k3, w in enumerate(chk.words):
                        if t >= w.start:
                            active = k3
                    key = (si, ci, active)
                    if key not in cap_cache:
                        cap_cache[key] = caption_layer(
                            [video.display(w.text) for w in chk.words], active)
                    cap = cap_cache[key]
                    frame.alpha_composite(cap, (0, CAPTION_Y - cap.height // 2))

                # a single bright frame sells the hook's hard cut
                if (si, vi) != prev_visual and prev_visual is not None and prev_visual[0] == si:
                    frame.alpha_composite(Image.new("RGBA", (W, H), (255, 255, 255, 150)))
                prev_visual = (si, vi)

                d = ImageDraw.Draw(frame)
                d.rectangle((0, H - 12, int(W * t / total), H), fill=video.HIGHLIGHT)

                proc.stdin.write(frame.convert("RGB").tobytes())
        finally:
            proc.stdin.close()
            rc = proc.wait()
        if rc != 0:
            raise RuntimeError(f"ffmpeg exited with {rc}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--out", default="story.mp4")
    ap.add_argument("--fake-audio", action="store_true")
    a = ap.parse_args()
    spec = json.loads(Path(a.spec).read_text())
    out = render(spec, Path(a.out), a.fake_audio)
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
