"""Scene illustrations, drawn from primitives so every pixel is original.

Each scene is a function returning an RGB canvas a little larger than the frame
(so the renderer can slowly zoom and pan over it). Scenes that need motion also
register a `dynamic` function that draws on a copy of the canvas per frame.
"""

import math
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OVERSCAN = 1.10
CW, CH = int(1080 * OVERSCAN), int(1920 * OVERSCAN)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def vgrad(top, bottom, w=CW, h=CH):
    t = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    a, b = np.array(top, np.float32), np.array(bottom, np.float32)
    arr = (a * (1 - t) + b * t).repeat(w, axis=1)
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8), "RGB")


def X(f):  # relative -> canvas pixels
    return int(CW * f)


def Y(f):
    return int(CH * f)


def glow(img, cx, cy, r, color, strength=0.6):
    layer = Image.new("RGB", img.size, (0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
    layer = layer.filter(ImageFilter.GaussianBlur(r * 0.45))
    a = np.asarray(img, np.float32) + np.asarray(layer, np.float32) * strength
    return Image.fromarray(a.clip(0, 255).astype(np.uint8))


def vignette(img, amount=0.45):
    w, h = img.size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = ((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2
    m = 1 - amount * np.clip(d - 0.35, 0, 1)
    a = np.asarray(img, np.float32) * m[..., None]
    return Image.fromarray(a.clip(0, 255).astype(np.uint8))


def grain(img, amount=10, seed=1):
    rng = np.random.default_rng(seed)
    n = rng.normal(0, amount, (img.size[1], img.size[0], 1)).astype(np.float32)
    a = np.asarray(img, np.float32) + n
    return Image.fromarray(a.clip(0, 255).astype(np.uint8))


def sepia(img, strength=0.85):
    a = np.asarray(img, np.float32)
    m = np.array([[0.393, 0.769, 0.189], [0.349, 0.686, 0.168], [0.272, 0.534, 0.131]])
    s = a @ m.T
    out = a * (1 - strength) + s * strength
    return Image.fromarray(out.clip(0, 255).astype(np.uint8))


def as_photo(scene, table, border=46, bottom=150, angle=-3.0, scale=0.80):
    """Put an illustration inside a printed-photo border on a table surface."""
    pw, ph = int(CW * scale), int(CH * scale * 0.78)
    pic = scene.resize((pw, int(pw * scene.height / scene.width)))
    pic = pic.crop((0, (pic.height - ph) // 2, pw, (pic.height - ph) // 2 + ph))
    card = Image.new("RGB", (pw + border * 2, ph + border + bottom), (245, 241, 230))
    card.paste(pic, (border, border))
    card = card.convert("RGBA").rotate(angle, expand=True, resample=Image.BICUBIC)
    shadow = Image.new("RGBA", card.size, (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 120), mask=card.split()[3])
    shadow = shadow.filter(ImageFilter.GaussianBlur(22))
    out = table.convert("RGBA")
    x, y = (CW - card.width) // 2, (CH - card.height) // 2 - 40
    out.alpha_composite(shadow, (x + 18, y + 26))
    out.alpha_composite(card, (x, y))
    return out.convert("RGB")


def poly(d, pts, fill):
    d.polygon([(X(a), Y(b)) for a, b in pts], fill=fill)


# --------------------------------------------------------------------------
# scenes
# --------------------------------------------------------------------------

def office():
    img = vgrad((214, 196, 166), (176, 152, 118))
    d = ImageDraw.Draw(img)
    # window with blinds
    d.rectangle((X(.08), Y(.10), X(.52), Y(.42)), fill=(150, 190, 220))
    for i in range(14):
        y = Y(.10) + i * (Y(.42) - Y(.10)) // 14
        d.rectangle((X(.08), y, X(.52), y + 18), fill=(232, 226, 210))
    d.rectangle((X(.075), Y(.095), X(.525), Y(.425)), outline=(120, 100, 76), width=14)
    # framed certificate on the wall
    d.rectangle((X(.66), Y(.15), X(.88), Y(.31)), fill=(120, 96, 66))
    d.rectangle((X(.68), Y(.165), X(.86), Y(.295)), fill=(244, 238, 222))
    for i in range(4):
        d.rectangle((X(.71), Y(.2) + i * 34, X(.83), Y(.2) + i * 34 + 10), fill=(200, 190, 170))
    # desk
    d.rectangle((0, Y(.62), CW, CH), fill=(104, 72, 46))
    d.rectangle((0, Y(.62), CW, Y(.635)), fill=(140, 102, 70))
    # monitor (switched off)
    d.rectangle((X(.12), Y(.40), X(.50), Y(.58)), fill=(40, 42, 48))
    d.rectangle((X(.14), Y(.415), X(.48), Y(.565)), fill=(18, 20, 26))
    d.rectangle((X(.29), Y(.58), X(.33), Y(.62)), fill=(60, 62, 70))
    d.rectangle((X(.23), Y(.612), X(.39), Y(.622)), fill=(60, 62, 70))
    # the box: someone is packing up
    poly(d, [(.55, .50), (.92, .50), (.92, .64), (.55, .64)], (176, 132, 82))
    poly(d, [(.55, .50), (.92, .50), (.86, .465), (.61, .465)], (196, 152, 98))
    d.rectangle((X(.70), Y(.50), X(.77), Y(.64)), fill=(204, 170, 120))
    # things sticking out of the box: a plant, a frame
    d.rectangle((X(.62), Y(.40), X(.70), Y(.49)), fill=(70, 70, 76))
    d.rectangle((X(.635), Y(.41), X(.685), Y(.48)), fill=(160, 190, 210))
    for a in range(-60, 61, 30):
        r = math.radians(a - 90)
        d.ellipse((X(.82) + int(140 * math.cos(r)) - 40, Y(.44) + int(140 * math.sin(r)) - 70,
                   X(.82) + int(140 * math.cos(r)) + 40, Y(.44) + int(140 * math.sin(r)) + 70),
                  fill=(70, 140, 80))
    # mug
    d.rectangle((X(.07), Y(.66), X(.15), Y(.73)), fill=(232, 228, 220))
    d.arc((X(.13), Y(.675), X(.18), Y(.715)), -90, 90, fill=(232, 228, 220), width=14)
    img = glow(img, X(.3), Y(.25), 380, (255, 230, 180), 0.35)
    return vignette(img, 0.5)


def ice():
    img = vgrad((150, 200, 240), (236, 246, 252))
    img = glow(img, X(.72), Y(.24), 260, (255, 255, 240), 0.9)
    d = ImageDraw.Draw(img)
    poly(d, [(0, .50), (.12, .38), (.22, .45), (.36, .33), (.5, .44), (.62, .36),
             (.78, .46), (.9, .37), (1, .43), (1, .56), (0, .56)], (190, 210, 228))
    poly(d, [(0, .58), (.18, .44), (.32, .54), (.46, .42), (.6, .55), (.76, .45),
             (1, .57), (1, .62), (0, .62)], (232, 240, 248))
    poly(d, [(.18, .44), (.25, .5), (.2, .55), (.1, .55)], (196, 214, 232))
    poly(d, [(.46, .42), (.52, .49), (.45, .55), (.38, .52)], (196, 214, 232))
    poly(d, [(.76, .45), (.84, .51), (.78, .56), (.7, .52)], (196, 214, 232))
    d.rectangle((0, Y(.61), CW, CH), fill=(242, 248, 252))
    for i in range(9):
        y = Y(.65 + i * .04)
        d.line((X(.05 + (i % 3) * .2), y, X(.4 + (i % 4) * .15), y + 6), fill=(214, 228, 240), width=5)
    return img


def retro_1987():
    scene = vgrad((196, 180, 150), (160, 140, 110))
    d = ImageDraw.Draw(scene)
    d.rectangle((0, Y(.66), CW, CH), fill=(120, 92, 64))
    # beige CRT
    d.rounded_rectangle((X(.18), Y(.26), X(.78), Y(.58)), 40, fill=(222, 212, 186))
    d.rounded_rectangle((X(.24), Y(.30), X(.72), Y(.52)), 30, fill=(20, 40, 24))
    mono = ImageFont.truetype(str(_font("VT323-Regular.ttf")), 64)
    lines = ["C:\\> DIR", "HPWORK   DOC", "REPORT   TXT", "C:\\> _"]
    for i, ln in enumerate(lines):
        if mono:
            d.text((X(.27), Y(.32) + i * 70), ln, font=mono, fill=(110, 230, 120))
        else:
            d.rectangle((X(.27), Y(.33) + i * 70, X(.27) + 30 * len(ln), Y(.33) + i * 70 + 26),
                        fill=(110, 230, 120))
    d.rectangle((X(.40), Y(.58), X(.56), Y(.62)), fill=(200, 190, 164))
    d.rectangle((X(.14), Y(.62), X(.82), Y(.665)), fill=(212, 202, 176))
    # keyboard keys
    d.rounded_rectangle((X(.16), Y(.69), X(.84), Y(.77)), 14, fill=(214, 204, 178))
    for r in range(3):
        for c in range(14):
            x = X(.18) + c * int(CW * .045)
            y = Y(.70) + r * 52
            d.rounded_rectangle((x, y, x + int(CW * .037), y + 40), 6, fill=(188, 178, 152))
    # floppy disks
    for i, col in enumerate([(40, 40, 46), (60, 60, 120)]):
        x = X(.84) - i * 40
        d.rectangle((x, Y(.80) + i * 30, x + 150, Y(.80) + i * 30 + 150), fill=col)
        d.rectangle((x + 30, Y(.80) + i * 30, x + 120, Y(.80) + i * 30 + 50), fill=(170, 170, 176))
    scene = grain(sepia(scene, 0.75), 9, 7)
    table = vgrad((48, 38, 30), (26, 20, 16))
    return vignette(as_photo(scene, table, angle=-3.5), 0.55)


def rejection_base():
    img = vgrad((26, 28, 36), (10, 11, 16))
    img = glow(img, X(.5), Y(.42), 520, (90, 120, 200), 0.35)
    d = ImageDraw.Draw(img)
    # laptop screen
    d.rounded_rectangle((X(.07), Y(.16), X(.93), Y(.68)), 30, fill=(30, 32, 38))
    d.rectangle((X(.09), Y(.175), X(.91), Y(.665)), fill=(246, 247, 250))
    # mail app chrome
    d.rectangle((X(.09), Y(.175), X(.91), Y(.215)), fill=(228, 232, 240))
    for i, c in enumerate([(236, 96, 90), (240, 190, 70), (96, 196, 110)]):
        d.ellipse((X(.11) + i * 40, Y(.188), X(.11) + i * 40 + 24, Y(.188) + 24), fill=c)
    ui = ImageFont.truetype(str(_font("Inter.ttf")), 40)
    ui.set_variation_by_name("Bold")
    d.text((X(.14), Y(.228)), "Inbox", font=ui, fill=(30, 32, 40))
    # keyboard deck
    poly(d, [(.02, .68), (.98, .68), (1.06, .78), (-.06, .78)], (56, 58, 66))
    d.rectangle((X(.40), Y(.735), X(.60), Y(.765)), fill=(70, 72, 82))
    return img


REJECTIONS = [
    ("Talent Team", "Update on your application"),
    ("Recruiting", "Thank you for your interest"),
    ("Careers", "Your application status"),
    ("Hiring Team", "Regarding the Senior Manager role"),
    ("Talent Acquisition", "Application update"),
    ("People Ops", "Thanks for applying"),
    ("Recruiting", "We've reviewed your profile"),
    ("Careers", "Position update"),
]


def rejection_dynamic(img, p, t=0.0):
    """Emails stack up as the scene runs."""
    d = ImageDraw.Draw(img)
    f_b = ImageFont.truetype(str(_font("Inter.ttf")), 34)
    f_b.set_variation_by_name("SemiBold")
    f_r = ImageFont.truetype(str(_font("Inter.ttf")), 28)
    f_t = ImageFont.truetype(str(_font("Inter.ttf")), 24)
    f_t.set_variation_by_name("Bold")
    n = min(len(REJECTIONS), 1 + int(p * 1.25 * len(REJECTIONS)))
    row_h = 118
    top = Y(.27)
    for i in range(n):
        sender, subj = REJECTIONS[n - 1 - i]       # newest on top
        y = top + i * row_h
        if y + row_h > Y(.66):
            break
        if i == 0:
            d.rectangle((X(.09), y, X(.91), y + row_h - 6), fill=(255, 246, 240))
        d.ellipse((X(.12), y + 22, X(.12) + 64, y + 86), fill=(200, 205, 220))
        d.text((X(.12) + 20, y + 32), sender[0], font=f_b, fill=(60, 64, 80))
        d.text((X(.21), y + 16), subj, font=f_b, fill=(24, 26, 34))
        d.text((X(.21), y + 62), "Unfortunately, we have decided to move forward with…",
               font=f_r, fill=(120, 124, 136))
        tw = f_t.getlength("NOT SELECTED")
        d.rounded_rectangle((X(.89) - tw - 30, y + 22, X(.89), y + 60), 18, fill=(232, 72, 72))
        d.text((X(.89) - tw - 15, y + 27), "NOT SELECTED", font=f_t, fill=(255, 255, 255))
        d.line((X(.10), y + row_h - 4, X(.90), y + row_h - 4), fill=(226, 228, 234), width=2)
    # unread badge climbing
    badge = 3 + int(p * 44)
    tw = f_t.getlength(str(badge))
    d.rounded_rectangle((X(.26), Y(.228), X(.26) + tw + 36, Y(.228) + 44), 22, fill=(232, 72, 72))
    d.text((X(.26) + 18, Y(.228) + 9), str(badge), font=f_t, fill=(255, 255, 255))


def penguin(d, cx, cy, s, facing=1):
    d.ellipse((cx - 46 * s, cy - 110 * s, cx + 46 * s, cy + 70 * s), fill=(24, 26, 32))
    d.ellipse((cx - 30 * s + facing * 6 * s, cy - 60 * s, cx + 30 * s + facing * 6 * s, cy + 64 * s),
              fill=(248, 248, 244))
    d.ellipse((cx - 30 * s, cy - 150 * s, cx + 30 * s, cy - 90 * s), fill=(24, 26, 32))
    d.ellipse((cx + facing * 8 * s - 5 * s, cy - 130 * s, cx + facing * 8 * s + 5 * s, cy - 120 * s),
              fill=(255, 255, 255))
    bx = cx + facing * 26 * s
    d.polygon([(bx, cy - 124 * s), (bx + facing * 30 * s, cy - 116 * s), (bx, cy - 108 * s)],
              fill=(240, 150, 40))
    d.ellipse((cx - 34 * s, cy + 58 * s, cx - 6 * s, cy + 74 * s), fill=(240, 150, 40))
    d.ellipse((cx + 6 * s, cy + 58 * s, cx + 34 * s, cy + 74 * s), fill=(240, 150, 40))


def antarctica_holiday():
    scene = vgrad((90, 160, 230), (200, 228, 248))
    d = ImageDraw.Draw(scene)
    # glacier wall with blue faces
    poly(d, [(0, .40), (.2, .34), (.42, .38), (.6, .31), (.82, .36), (1, .33), (1, .56), (0, .56)],
         (236, 244, 252))
    for x0 in (.06, .24, .44, .63, .82):
        poly(d, [(x0, .42), (x0 + .06, .40), (x0 + .09, .56), (x0 + .01, .56)], (130, 190, 228))
    # sea, then rocky shore
    d.rectangle((0, Y(.56), CW, Y(.66)), fill=(30, 70, 120))
    for i in range(6):
        d.line((X(.05 + i * .17), Y(.6 + (i % 2) * .02), X(.15 + i * .17), Y(.6 + (i % 2) * .02)),
               fill=(80, 130, 180), width=5)
    poly(d, [(0, .66), (.3, .64), (.6, .665), (1, .65), (1, 1), (0, 1)], (110, 104, 100))
    poly(d, [(0, .74), (.4, .72), (1, .75), (1, 1), (0, 1)], (236, 240, 244))
    for (x, y, s, f) in [(.22, .79, 1.6, 1), (.38, .82, 1.9, -1), (.56, .78, 1.4, 1),
                         (.70, .84, 2.1, -1), (.84, .80, 1.5, -1), (.12, .86, 2.0, 1)]:
        penguin(d, X(x), Y(y), s, f)
    scene = grain(scene, 5, 3)
    table = vgrad((214, 226, 236), (170, 190, 208))
    return vignette(as_photo(scene, table, angle=2.5), 0.3)


def mcmurdo():
    img = vgrad((196, 206, 216), (232, 236, 240))
    d = ImageDraw.Draw(img)
    # dark volcanic hill behind the station
    poly(d, [(0, .46), (.18, .33), (.34, .30), (.5, .38), (.7, .35), (.9, .42), (1, .44), (1, .55), (0, .55)],
         (96, 90, 88))
    poly(d, [(.18, .33), (.26, .31), (.24, .36)], (240, 242, 244))
    # boxy station buildings
    rng = random.Random(4)
    x = .02
    for col in [(150, 112, 70), (70, 110, 150), (176, 150, 100), (120, 80, 60), (90, 130, 140), (160, 120, 80)]:
        w = rng.uniform(.13, .19)
        h = rng.uniform(.07, .11)
        d.rectangle((X(x), Y(.55 - h), X(x + w), Y(.56)), fill=col)
        for wx in range(3):
            for wy in range(2):
                d.rectangle((X(x + .02 + wx * w / 3.4), Y(.55 - h + .015 + wy * .03),
                             X(x + .02 + wx * w / 3.4) + 30, Y(.55 - h + .015 + wy * .03) + 26),
                            fill=(230, 220, 170))
        x += w + .015
    # snowfield
    d.rectangle((0, Y(.56), CW, CH), fill=(244, 247, 250))
    # shipping containers
    def container(x0, y0, w, h, col):
        d.rectangle((X(x0), Y(y0), X(x0 + w), Y(y0 + h)), fill=col)
        for k in range(1, 9):
            xx = X(x0) + k * (X(x0 + w) - X(x0)) // 9
            d.line((xx, Y(y0) + 8, xx, Y(y0 + h) - 8), fill=tuple(int(c * .78) for c in col), width=6)
    container(.05, .63, .40, .07, (210, 98, 40))
    container(.10, .56, .34, .07, (40, 96, 160))
    container(.52, .64, .40, .07, (60, 130, 90))
    # forklift
    d.rectangle((X(.62), Y(.74), X(.80), Y(.80)), fill=(236, 186, 40))
    d.rectangle((X(.66), Y(.69), X(.76), Y(.74)), outline=(40, 40, 40), width=10)
    d.rectangle((X(.80), Y(.66), X(.815), Y(.82)), fill=(60, 60, 64))
    d.rectangle((X(.815), Y(.80), X(.90), Y(.81)), fill=(60, 60, 64))
    d.rectangle((X(.82), Y(.76), X(.89), Y(.80)), fill=(176, 132, 82))
    for wx in (.65, .77):
        d.ellipse((X(wx) - 44, Y(.80) - 44, X(wx) + 44, Y(.80) + 44), fill=(30, 30, 34))
    # deep snow drifts in front
    for (cx, cy, rw, rh) in [(.15, .90, .4, .08), (.55, .93, .5, .09), (.92, .89, .3, .07)]:
        d.ellipse((X(cx - rw / 2), Y(cy - rh / 2), X(cx + rw / 2), Y(cy + rh / 2)), fill=(252, 253, 255))
    return img


def broadcast_base():
    img = vgrad((22, 24, 32), (8, 9, 13))
    d = ImageDraw.Draw(img)
    # ON AIR sign
    d.rounded_rectangle((X(.28), Y(.10), X(.72), Y(.17)), 24, fill=(90, 20, 24))
    f = ImageFont.truetype(str(_font("Anton-Regular.ttf")), 120)
    tw = f.getlength("ON AIR")
    d.text(((CW - tw) / 2, Y(.104)), "ON AIR", font=f, fill=(255, 90, 90))
    # equipment rack
    d.rectangle((X(.10), Y(.22), X(.90), Y(.62)), fill=(34, 36, 44))
    for i in range(5):
        y = Y(.24) + i * Y(.075)
        d.rectangle((X(.12), y, X(.88), y + Y(.06)), fill=(48, 50, 60))
        for k in range(6):
            cx = X(.18) + k * X(.07)
            d.ellipse((cx - 22, y + Y(.03) - 22, cx + 22, y + Y(.03) + 22), fill=(120, 124, 136))
    # mixing desk
    poly(d, [(.0, .70), (1, .70), (1.05, .92), (-.05, .92)], (40, 42, 52))
    for k in range(10):
        x = X(.07) + k * X(.09)
        d.rectangle((x, Y(.73), x + 16, Y(.89)), fill=(20, 20, 26))
    img = glow(img, X(.5), Y(.13), 300, (255, 60, 60), 0.5)
    return img


def broadcast_dynamic(img, p, t):
    d = ImageDraw.Draw(img)
    # VU meters on the rack
    for i in range(5):
        y = Y(.24) + i * Y(.075)
        level = 0.35 + 0.6 * abs(math.sin(t * (3.1 + i * 0.7) + i))
        bars = int(12 * level)
        for b in range(12):
            col = (70, 220, 120) if b < 8 else (240, 200, 60) if b < 10 else (240, 70, 70)
            if b >= bars:
                col = (30, 34, 40)
            x = X(.60) + b * 22
            d.rectangle((x, y + 20, x + 14, y + Y(.06) - 20), fill=col)
    # fader caps drift
    for k in range(10):
        x = X(.07) + k * X(.09)
        pos = 0.5 + 0.35 * math.sin(t * 0.8 + k * 0.9)
        y = Y(.74) + int((Y(.87) - Y(.74)) * pos)
        d.rectangle((x - 22, y, x + 38, y + 28), fill=(220, 222, 230))


def horizon():
    img = vgrad((40, 60, 120), (250, 176, 150))
    img = glow(img, X(.5), Y(.58), 360, (255, 210, 150), 0.9)
    d = ImageDraw.Draw(img)
    d.ellipse((X(.5) - 90, Y(.585) - 90, X(.5) + 90, Y(.585) + 90), fill=(255, 236, 200))
    poly(d, [(0, .60), (.1, .575), (.18, .59), (.3, .58), (.42, .595), (1, .6), (1, .61), (0, .61)],
         (120, 110, 150))
    d.rectangle((0, Y(.605), CW, CH), fill=(220, 214, 230))
    ice = vgrad((236, 210, 210), (196, 200, 226), CW, CH - Y(.605))
    img.paste(ice, (0, Y(.605)))
    d = ImageDraw.Draw(img)
    for i in range(12):   # sun's reflection streak
        w = 160 - i * 10
        d.rectangle((X(.5) - w, Y(.62) + i * 34, X(.5) + w, Y(.62) + i * 34 + 10), fill=(255, 226, 200))
    return img


# --------------------------------------------------------------------------
# registry
# --------------------------------------------------------------------------

def _font(name):
    from pathlib import Path
    return Path(__file__).resolve().parent.parent / "assets" / "fonts" / name


def _has(name):
    try:
        ImageFont.truetype(name, 10)
        return True
    except OSError:
        return False


SCENES = {
    "office": {"base": office, "snow": False},
    "ice": {"base": ice, "snow": True},
    "retro_1987": {"base": retro_1987, "snow": False},
    "rejections": {"base": rejection_base, "dynamic": rejection_dynamic, "snow": False},
    "antarctica_holiday": {"base": antarctica_holiday, "snow": False},
    "mcmurdo": {"base": mcmurdo, "snow": True},
    "broadcast": {"base": broadcast_base, "dynamic": broadcast_dynamic, "snow": False},
    "horizon": {"base": horizon, "snow": True},
}
