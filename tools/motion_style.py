# Motion-graphics edit: animated B-roll scenes over the voice, face bubble, colour-boxed captions, SFX.
# Usage: motion_style.py plan.json [t1,t2,...]   (times = preview stills only)
import json, sys, re, subprocess, math, wave, numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

P = json.load(open(sys.argv[1]))
ROOT = "/home/user/Edit"
ANTON, INTER = f"{ROOT}/fonts/Anton-Regular.ttf", f"{ROOT}/fonts/Inter.ttf"
W, H, FPS = 1080, 1920, 30
preview = [float(x) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 else None
COL = {"yellow": (255, 205, 60), "orange": (255, 112, 40), "cyan": (60, 205, 255), "white": (245, 245, 245),
       "green": (80, 230, 120), "red": (255, 70, 70)}
DIM = (120, 120, 120)

_f = {}
def font(path, size, var=None):
    k = (path, size, var)
    if k not in _f:
        f = ImageFont.truetype(path, max(4, int(size)))
        if var: f.set_variation_by_name(var)
        _f[k] = f
    return _f[k]
def clamp(a, lo=0.0, hi=1.0): return min(max(a, lo), hi)
def ease_out(a): a = clamp(a); return 1 - (1 - a) ** 3
def ease_io(a): a = clamp(a); return a * a * (3 - 2 * a)
def ease_back(a):
    a = clamp(a); c = 1.7; return 1 + (c + 1) * (a - 1) ** 3 + c * (a - 1) ** 2
def lerp(a, b, x): return a + (b - a) * x
def mix(c1, c2, x): return tuple(int(lerp(c1[k], c2[k], x)) for k in range(3))

# ---------- words / captions ----------
words = json.load(open(P["words"]))["words"]
for i, txt in P.get("word_fixes", {}).items(): words[int(i)]["w"] = txt
words = [w for w in words if w["w"]]
for w in words: w["u"] = re.sub(r"[.,!?;:]+$", "", w["w"]).upper()
span_of = [None] * len(words); col_of = [None] * len(words); sid = 0
for phrase, colour in P["keywords"]:
    toks = phrase.upper().split()
    for i in range(len(words) - len(toks) + 1):
        if all(words[i + k]["u"] == toks[k] for k in range(len(toks))) and all(span_of[i + k] is None for k in range(len(toks))):
            for k in range(len(toks)): span_of[i + k] = sid; col_of[i + k] = colour
            sid += 1
groups, cur = [], []
for i, w in enumerate(words):
    cur.append(i); nxt = i + 1 if i + 1 < len(words) else None
    keep = nxt is not None and span_of[i] is not None and span_of[nxt] == span_of[i]
    if not keep and (re.search(r"[.,!?;:]$", w["w"]) or len(cur) >= P.get("max_words", 3) or nxt is None
                     or words[nxt]["s"] - w["e"] > 0.4):
        groups.append(cur); cur = []
for gi, g in enumerate(groups):
    end = words[groups[gi + 1][0]]["s"] if gi + 1 < len(groups) else words[g[-1]]["e"] + 1.0
    for i in g: words[i]["g_end"] = min(end, words[g[-1]]["e"] + 1.2)

def draw_caption(c, t, cy, size=96, maxw=960):
    g = next((g for g in groups if words[g[0]]["s"] - 0.03 <= t < words[g[0]]["g_end"]), None)
    if g is None: return
    f = font(ANTON, size); sp = int(size * 0.26)
    lines, line, x = [], [], 0
    for i in g:
        wd = f.getbbox(words[i]["u"])[2]
        if line and x + sp + wd > maxw: lines.append(line); line, x = [], 0
        line.append((i, wd)); x += (sp if len(line) > 1 else 0) + wd
    lines.append(line)
    d = ImageDraw.Draw(c); lh = int(size * 1.18); y = cy - lh * len(lines) / 2
    top_off, bot_off = f.getbbox("H")[1], f.getbbox("H")[3]
    for line in lines:
        tw = sum(wd for _, wd in line) + sp * (len(line) - 1); x = (W - tw) / 2; boxes = {}
        for i, wd in line:
            if words[i]["s"] > t + 0.02: x += wd + sp; continue
            a = ease_out((t - words[i]["s"]) / 0.12)
            colour = COL[col_of[i]] if col_of[i] else COL["white"]
            dy = (1 - ease_back((t - words[i]["s"]) / 0.18)) * 18
            d.text((x + 4, y + 6 + dy), words[i]["u"], font=f, fill=(0, 0, 0))
            d.text((x, y + dy), words[i]["u"], font=f, fill=mix(DIM, colour, a))
            if span_of[i] is not None:
                b = boxes.setdefault(span_of[i], [x, x + wd, col_of[i]]); b[1] = x + wd
            x += wd + sp
        for x0, x1, colour in boxes.values():
            pad = 12; d.rectangle((x0 - pad, y + top_off - pad, x1 + pad, y + bot_off + pad), outline=COL[colour], width=5)
        y += lh

# ---------- glow drawing helpers ----------
class Glow:
    """Collect shapes on a sharp layer and a glow layer; glow is blurred at half size for speed."""
    def __init__(self):
        self.sharp = Image.new("RGBA", (W, H), (0, 0, 0, 0)); self.ds = ImageDraw.Draw(self.sharp)
        self.glow = Image.new("RGBA", (W // 2, H // 2), (0, 0, 0, 0)); self.dg = ImageDraw.Draw(self.glow)
    def line(self, pts, col, w, glow=True, alpha=255):
        self.ds.line(pts, fill=col + (alpha,), width=int(w), joint="curve")
        if glow: self.dg.line([(x / 2, y / 2) for x, y in pts], fill=col + (alpha,), width=max(2, int(w * 1.2)), joint="curve")
    def ellipse(self, box, col, fill=True, w=4, glow=True, alpha=255):
        if fill: self.ds.ellipse(box, fill=col + (alpha,))
        else: self.ds.ellipse(box, outline=col + (alpha,), width=int(w))
        if glow: self.dg.ellipse([v / 2 for v in box], fill=col + (alpha,) if fill else None,
                                 outline=None if fill else col + (alpha,), width=max(2, int(w)))
    def rect(self, box, col, fill=True, w=4, glow=True, alpha=255, r=0):
        if fill: self.ds.rounded_rectangle(box, r, fill=col + (alpha,))
        else: self.ds.rounded_rectangle(box, r, outline=col + (alpha,), width=int(w))
        if glow: self.dg.rounded_rectangle([v / 2 for v in box], r / 2, fill=col + (alpha,) if fill else None,
                                           outline=None if fill else col + (alpha,), width=max(2, int(w / 2)))
    def poly(self, pts, col, alpha=255, glow=True):
        self.ds.polygon(pts, fill=col + (alpha,))
        if glow: self.dg.polygon([(x / 2, y / 2) for x, y in pts], fill=col + (alpha,))
    def arc(self, box, a0, a1, col, w, glow=True, alpha=255):
        self.ds.arc(box, a0, a1, fill=col + (alpha,), width=int(w))
        if glow: self.dg.arc([v / 2 for v in box], a0, a1, fill=col + (alpha,), width=max(2, int(w / 2 + 2)))
    def text(self, xy, s, f, col, anchor="mm", glow=True, alpha=255):
        self.ds.text(xy, s, font=f, fill=col + (alpha,), anchor=anchor)
        if glow:
            f2 = font(f.path, f.size / 2, None)
            self.dg.text((xy[0] / 2, xy[1] / 2), s, font=f2, fill=col + (alpha,), anchor=anchor)
    def onto(self, c, strength=2):
        g = self.glow.filter(ImageFilter.GaussianBlur(9)).resize((W, H), Image.BILINEAR)
        for _ in range(strength): c.alpha_composite(g)
        c.alpha_composite(self.sharp)

def burst(gl, t, t0, cx, cy, col, n=18, dist=170, dur=0.6, seed=0):
    """Particles flying out from (cx, cy) after t0."""
    a = (t - t0) / dur
    if not 0 <= a < 1: return
    rng = np.random.default_rng(int(t0 * 1000) + seed)
    for k in range(n):
        ang = rng.uniform(0, 2 * math.pi); sp = rng.uniform(0.5, 1.0); r = dist * sp * ease_out(a)
        x, y = cx + math.cos(ang) * r, cy + math.sin(ang) * r + 60 * a * a
        s = (1 - a) * rng.uniform(5, 11)
        gl.ellipse((x - s, y - s, x + s, y + s), col, alpha=int(255 * (1 - a)))

# ---------- background ----------
_bg = None
def scene_bg(t):
    global _bg
    if _bg is None:
        yy = np.linspace(0, 1, H)[:, None]; xx = np.linspace(-1, 1, W)[None, :]
        v = np.clip(1 - 0.6 * xx ** 2 - 0.45 * (yy - 0.45) ** 2 * 3, 0, 1)
        _bg = np.stack([8 + 14 * v, 10 + 16 * v, 15 + 22 * v], -1).astype(np.uint8)
    c = Image.fromarray(_bg, "RGB").convert("RGBA"); d = ImageDraw.Draw(c)
    off = (t * 24) % 72                                   # slowly drifting grid
    for gx in np.arange(-72, W + 72, 72): d.line([(gx + off, 0), (gx + off, H)], fill=(22, 27, 36, 255))
    for gy in np.arange(-72, H + 72, 72): d.line([(0, gy + off), (W, gy + off)], fill=(22, 27, 36, 255))
    return c

# ---------- calf-raise figure ----------
def calf_figure(gl, cx, base, t, mode, colour, scale=1.0, t_start=0, pause=None, label=None):
    """Side view of a calf raise on a step. mode: full | top | bottom | hold_bottom. Returns heel height (-1..1)."""
    s = scale; tt = t - t_start
    if mode == "full": h = math.sin(tt * 2 * math.pi / 2.0)
    elif mode == "top": h = 0.5 + 0.5 * abs(math.sin(tt * 2 * math.pi / 1.1))          # fast bounces at the top
    elif mode == "bottom": h = -0.5 - 0.5 * math.sin(tt * 2 * math.pi / 2.6) ** 2 * 1.0 + 0.0
    elif mode == "hold_bottom": h = -1.0 if (pause and pause[0] <= t < pause[1]) else math.sin(tt * 2 * math.pi / 2.4)
    else: h = 0
    if mode == "bottom": h = -1 + 1.0 * (0.5 + 0.5 * math.cos(tt * 2 * math.pi / 2.6))   # -1 .. 0, slow
    ang = -math.radians(32) * h                                # positive h = heel up
    # step
    step_top = base
    gl.rect((cx - 40 * s, step_top, cx + 130 * s, step_top + 70 * s), (70, 78, 92), w=4, fill=False, glow=False)
    gl.rect((cx - 40 * s, step_top, cx + 130 * s, step_top + 8 * s), (110, 120, 140), glow=False)
    P0 = (cx, step_top)                                        # ball of foot on the step edge
    rot = lambda x, y: (P0[0] + (x * math.cos(ang) + y * math.sin(ang)) * s, P0[1] + (-x * math.sin(ang) + y * math.cos(ang)) * s)
    heel, ankle, toe = rot(-120, 0), rot(-88, -42), rot(40, 0)
    lift = ankle[1] - (P0[1] - 42 * s)
    knee = (ankle[0] + 18 * s, ankle[1] - 250 * s); hip = (knee[0] - 10 * s, knee[1] - 240 * s)
    sh = (hip[0] + 10 * s, hip[1] - 280 * s); head = (sh[0] + 6 * s, sh[1] - 70 * s)
    white = (235, 240, 255)
    # range-of-motion arc around the ball of the foot
    R = 150 * s
    gl.arc((P0[0] - R, P0[1] - R, P0[0] + R, P0[1] + R), 180 - 34, 180 + 34, (55, 60, 72), 6 * s, glow=False)  # PIL angles: clockwise, y down
    lo, hi = {"full": (-1, 1), "top": (0, 1), "bottom": (-1, 0), "hold_bottom": (-1, 1)}.get(mode, (-1, 1))
    gl.arc((P0[0] - R, P0[1] - R, P0[0] + R, P0[1] + R), 180 + 32 * lo, 180 + 32 * hi, colour, 8 * s)
    hx, hy = P0[0] - R * math.cos(ang), P0[1] + R * math.sin(ang)
    gl.ellipse((hx - 11 * s, hy - 11 * s, hx + 11 * s, hy + 11 * s), colour)
    # body
    for a, b, wdt in ((toe, heel, 16), (ankle, knee, 18), (knee, hip, 22), (hip, sh, 26)):
        gl.line([a, b], white, wdt * s)
    gl.ellipse((head[0] - 48 * s, head[1] - 48 * s, head[0] + 48 * s, head[1] + 48 * s), white)
    gl.line([(sh[0], sh[1] + 30 * s), (sh[0] + 90 * s, sh[1] + 150 * s)], white, 14 * s)
    # calf muscle: brighter / bigger in the stretch
    stretch = clamp((-h + 1) / 2)
    mx, my = lerp(ankle[0], knee[0], 0.62) - 22 * s, lerp(ankle[1], knee[1], 0.62)
    rw, rh = (26 + 10 * stretch) * s, (78 + 6 * stretch) * s
    gl.ellipse((mx - rw, my - rh, mx + rw, my + rh), mix((90, 90, 90), colour, 0.45 + 0.55 * stretch))
    if label:
        f = font(INTER, 34 * s, "ExtraBold"); tw = f.getbbox(label)[2]
        gl.rect((cx - tw / 2 - 18, base + 110 * s, cx + tw / 2 + 18, base + 110 * s + 56), colour, fill=False, w=4)
        gl.text((cx, base + 110 * s + 28), label, f, colour)
    return h

# ---------- scenes ----------
def sc_compare(gl, c, t, S):
    a = ease_back((t - S["t0"]) / 0.4)
    for k, (mode, col, lab, x) in enumerate((("top", "yellow", "HALF REPS", 300), ("full", "white", "FULL REPS", 780))):
        calf_figure(gl, x - 40, 1290 + (1 - a) * 300, t, mode, COL[col], 0.85, S["t0"], label=lab)
    tv = S.get("t_vs", S["t0"] + 1)
    if t >= tv:
        s = ease_back((t - tv) / 0.3); f = font(ANTON, 120 * s)
        gl.text((W / 2, 900), "VS", f, COL["orange"])
    tw = S.get("t_win")
    if tw and t >= tw:
        s = ease_back((t - tw) / 0.35)
        crown = [(200 + dx * s, 470 + dy * s) for dx, dy in ((-60, 30), (-60, -30), (-30, 0), (0, -50), (30, 0), (60, -30), (60, 30))]
        gl.poly(crown, COL["yellow"]); burst(gl, t, tw, 200, 470, COL["yellow"])

def person(gl, x, y, r, col, alpha=255):
    gl.ellipse((x - r * .45, y - r * 1.25, x + r * .45, y - r * .35), col, alpha=alpha, glow=False)
    gl.rect((x - r * .7, y - r * .25, x + r * .7, y + r * .9), col, alpha=alpha, r=int(r * .5), glow=False)

def sc_people(gl, c, t, S):
    cols, rows, gap = 6, 7, 120
    x0, y0 = W / 2 - gap * (cols - 1) / 2, 560
    for k in range(42):
        tk = S["t0"] + 0.04 * k
        if t < tk: continue
        s = ease_back((t - tk) / 0.25); r = 34 * s
        group = k % 3; col = (COL["orange"], COL["white"], COL["cyan"])[group] if t >= S.get("t_split", 1e9) else (200, 205, 215)
        x, y = x0 + gap * (k % cols), y0 + gap * (k // cols)
        person(gl, x, y, r, col)
    n = min(42, int(clamp((t - S["t0"]) / (0.04 * 42)) * 42))
    gl.text((W / 2, 1480), f"{n} PEOPLE", font(ANTON, 110), COL["yellow"])
    tw = S.get("t_weeks")
    if tw and t >= tw:
        a = ease_io((t - tw) / 1.0)
        gl.rect((140, 1600, 940, 1650), (40, 46, 58), glow=False, r=25)
        gl.rect((140, 1600, 140 + 800 * a, 1650), COL["yellow"], r=25)
        for k in range(9):
            x = 140 + 100 * k; on = a * 8 >= k
            gl.ellipse((x - 9, 1616, x + 9, 1634), (20, 20, 20) if on else (90, 90, 90), glow=False)
        gl.text((W / 2, 1720), f"WEEK {max(1, math.ceil(a * 8))} / 8", font(INTER, 44, "ExtraBold"), COL["white"])

def sc_sets(gl, c, t, S):
    for g, (col, lab) in enumerate(((COL["orange"], "BOTTOM HALF"), (COL["white"], "FULL"), (COL["cyan"], "TOP HALF"))):
        x = W * (g + 1) / 4
        for k in range(4):
            tk = S["t0"] + 0.18 * k + 0.05 * g
            if t < tk: continue
            a = ease_out((t - tk) / 0.28); y = 1380 - k * 110 - (1 - a) * 700
            gl.rect((x - 105, y - 85, x + 105, y), col, r=14, alpha=230)
            gl.text((x, y - 42), f"SET {k + 1}", font(INTER, 36, "ExtraBold"), (20, 20, 20), glow=False)
            if a >= 1 and t - tk < 0.5: burst(gl, t, tk + 0.28, x, y, col, n=8, dist=90, dur=0.4, seed=g * 10 + k)
        gl.text((x, 1450), lab, font(INTER, 34, "ExtraBold"), col)
    te = S.get("t_eq")
    if te and t >= te:
        s = ease_back((t - te) / 0.3); gl.text((W / 2, 700), "= SAME SETS =", font(ANTON, 96 * s), COL["green"])

def sc_groups(gl, c, t, S):
    specs = S["groups"]
    for k, g in enumerate(specs):
        if t < g["t"]: continue
        a = ease_back((t - g["t"]) / 0.4); x = W * (k + 1) / 4 - 30
        calf_figure(gl, x, 1220 + (1 - a) * 400, t, g["mode"], COL[g["color"]], 0.7, g["t"], label=g["label"])
        if t - g["t"] < 0.6: burst(gl, t, g["t"] + 0.15, x + 20, 900, COL[g["color"]], n=14, dist=140, seed=k)
        if g.get("note") and t >= g["note"]["t"]:
            s = ease_back((t - g["note"]["t"]) / 0.3); f = font(ANTON, 58 * s)
            gl.text((x + 20, 1440), g["note"]["text"], f, COL[g["color"]])

def sc_bars(gl, c, t, S):
    cols = S["columns"]; base, maxh, bw = 1350, 650, 190
    for k, col in enumerate(cols):
        x = W * (k + 1) / 4; colour = COL[col["color"]]
        f = font(INTER, 34, "ExtraBold"); gl.text((x, base + 60), col["label"], f, colour)
        gl.rect((x - bw / 2, base - maxh, x + bw / 2, base), (60, 66, 80), fill=False, w=4, glow=False, r=12)
        if t >= col["t"]:
            a = ease_out((t - col["t"]) / 0.9); hgt = maxh * col["value"] / S["max_value"] * a
            if hgt > 6: gl.rect((x - bw / 2 + 10, base - hgt, x + bw / 2 - 10, base - 6), colour, r=8)
            gl.text((x, base - hgt - 70), f"+{round(col['value'] * a)}%", font(ANTON, 96), colour)
            if a >= 1 and t - col["t"] < 1.5: burst(gl, t, col["t"] + 0.9, x, base - hgt, colour, n=16, seed=k)
        b = col.get("badge")
        if b and t >= b["t"]:
            s = ease_back((t - b["t"]) / 0.3); f = font(ANTON, 110 * s)
            gl.rect((x - 110 * s, 470 - 75 * s, x + 110 * s, 470 + 75 * s), COL["yellow"], r=int(18 * s))
            gl.text((x, 470), b["text"], f, (20, 20, 20), glow=False)
            burst(gl, t, b["t"], x, 470, COL["yellow"], n=30, dist=260, dur=0.8)

def sc_spring(gl, c, t, S):
    cx, top0 = W / 2, 650; tt = t - S["t0"]
    comp = 0.5 + 0.5 * math.cos(tt * 2 * math.pi / 0.9)       # 1 = stretched, 0 = compressed
    hgt = lerp(330, 680, comp); top = 1350 - hgt
    pts = []; coils = 9
    for k in range(coils * 24 + 1):
        u = k / (coils * 24); pts.append((cx + 150 * math.sin(u * coils * 2 * math.pi), top + hgt * u))
    gl.line(pts, COL["yellow"], 16)
    gl.rect((cx - 220, 1350, cx + 220, 1390), (110, 120, 140), r=10, glow=False)
    gl.rect((cx - 180, top - 40, cx + 180, top), COL["white"], r=10)
    if comp < 0.08: burst(gl, t, t - 0.01, cx, top, COL["yellow"], n=6, dist=60, dur=0.3, seed=int(tt))
    gl.text((cx, 520), "ENERGY STORED → RELEASED", font(INTER, 40, "ExtraBold"), (200, 205, 215))

def sc_energy(gl, c, t, S):
    tt = t - S["t0"]; pulse = 0.5 + 0.5 * math.sin(tt * 2 * math.pi / 1.2)
    for k, (lab, col, val) in enumerate((("TENDON", COL["yellow"], 0.35 + 0.6 * pulse), ("MUSCLE", COL["cyan"], None))):
        x = W * (k + 1) / 3
        if val is None:
            dt = S.get("t_less")
            val = 0.85 if (dt is None or t < dt) else lerp(0.85, 0.3, ease_out((t - dt) / 0.8))
        gl.rect((x - 110, 520, x + 110, 1270), (60, 66, 80), fill=False, w=5, glow=False, r=24)
        gl.rect((x - 95, 1255 - 720 * val, x + 95, 1255), col, r=16)
        gl.text((x, 1350), lab, font(ANTON, 80), col)
        gl.text((x, 1430), f"{round(val * 100)}%", font(INTER, 46, "ExtraBold"), (220, 220, 230))
    for k in range(5):                                        # energy sparks travelling from tendon to muscle
        u = ((tt * 0.9 + k / 5) % 1); x = lerp(W / 3, 2 * W / 3, u); y = 870 - 120 * math.sin(u * math.pi)
        gl.ellipse((x - 10, y - 10, x + 10, y + 10), COL["yellow"], alpha=int(255 * math.sin(u * math.pi)))

def sc_pause(gl, c, t, S):
    pz = S["pause"]
    calf_figure(gl, W / 2 - 60, 1250, t, "hold_bottom", COL["orange"], 1.0, S["t0"], pause=pz)
    cx, cy, r = W / 2 + 270, 640, 120
    gl.arc((cx - r, cy - r, cx + r, cy + r), 0, 360, (55, 60, 72), 16, glow=False)
    if pz[0] <= t:
        a = clamp((t - pz[0]) / (pz[1] - pz[0]))
        gl.arc((cx - r, cy - r, cx + r, cy + r), -90, -90 + 360 * a, COL["orange"], 16)
        gl.text((cx, cy), "PAUSE" if a < 1 else "✓", font(ANTON, 64), COL["orange"] if a < 1 else COL["green"])
    reps = S.get("reps")
    if reps:
        n = sum(1 for x in reps if t >= x)
        gl.text((W / 2 - 250, 640), f"REP {n}", font(ANTON, 90), COL["white"])

SCENES = {"compare": sc_compare, "people": sc_people, "sets": sc_sets, "groups": sc_groups, "bars": sc_bars,
          "spring": sc_spring, "energy": sc_energy, "pause": sc_pause}

# ---------- face bubble ----------
_mask = {}
def bubble(c, src, t, S):
    r = P.get("bubble_r", 150); fx, fy, fr = P.get("face", [540, 820, 360])
    k = 2 * r
    if k not in _mask:
        m = Image.new("L", (k * 2, k * 2), 0); ImageDraw.Draw(m).ellipse((0, 0, k * 2 - 1, k * 2 - 1), fill=255)
        _mask[k] = m.resize((k, k), Image.LANCZOS)
    face = src.crop((fx - fr, fy - fr, fx + fr, fy + fr)).resize((k, k), Image.BICUBIC)
    a = ease_back((t - S["t0"]) / 0.35); cx, cy = W - r - 50, H - r - 130 + (1 - a) * 400
    ring = Image.new("RGBA", (k + 24, k + 24), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((0, 0, k + 23, k + 23), fill=COL["orange"] + (255,))
    c.alpha_composite(ring, (int(cx - r - 12), int(cy - r - 12)))
    c.paste(face, (int(cx - r), int(cy - r)), _mask[k])

# ---------- talk shots ----------
def talk(src, t, S):
    z = 1.0
    for a, b, zz in S.get("punch", []):
        if a <= t < b: z = zz
    for tp in S.get("pulse", []):                           # quick zoom-pulse on a word
        if tp <= t < tp + 0.35: z *= 1 + 0.08 * math.sin(math.pi * (t - tp) / 0.35)
    if abs(z - 1) < 1e-3: return src.convert("RGBA")
    cx, cy = S.get("zoom_center", [0.5, 0.42]); w, h = W / z, H / z
    x0 = clamp(cx * W - w / 2, 0, W - w); y0 = clamp(cy * H - h / 2, 0, H - h)
    return src.crop((int(x0), int(y0), int(x0 + w), int(y0 + h))).resize((W, H), Image.BICUBIC).convert("RGBA")

_grad = None
def top_grad(c):
    global _grad
    if _grad is None:
        g = np.zeros((int(H * .34), W, 4), np.uint8); g[..., 3] = (np.linspace(1, 0, g.shape[0]) ** 1.4 * 190)[:, None]
        _grad = Image.fromarray(g, "RGBA")
    c.alpha_composite(_grad)

def draw_tag(c):
    if not P.get("tag"): return
    f = font(INTER, 26, "ExtraBold"); txt = P["tag"]; tw = f.getbbox(txt)[2]
    d = ImageDraw.Draw(c); x1 = W - 40; x0 = x1 - tw - 36
    d.rounded_rectangle((x0, 40, x1, 86), radius=23, fill=COL["orange"])
    d.text((x0 + 18, 48), txt, font=f, fill=(255, 255, 255))

def seg_at(t):
    for s in P["segments"]:
        if s["t0"] <= t < s["t1"]: return s
    return P["segments"][-1]

def compose(src, t):
    S = seg_at(t)
    if S["kind"] == "talk":
        c = talk(src, t, S); top_grad(c)
        draw_caption(c, t, S.get("cap_y", 0.17) * H)
        ti = S.get("title")
        if ti and t >= ti["t"]:
            s = ease_back((t - ti["t"]) / 0.3); f = font(ANTON, ti.get("size", 230) * max(s, 0.05))
            d = ImageDraw.Draw(c); y = ti.get("y", 0.64) * H
            d.text((W / 2 + 5, y + 8), ti["text"], font=f, fill=(0, 0, 0), anchor="mm")
            d.text((W / 2, y), ti["text"], font=f, fill=COL[ti.get("color", "yellow")], anchor="mm")
    else:
        c = scene_bg(t); gl = Glow()
        SCENES[S["kind"]](gl, c, t, S)
        gl.onto(c)
        draw_caption(c, t, 250)
        if S.get("bubble", True): bubble(c, src, t, S)
    # entrance transition: quick zoom-settle + flash on every segment change
    a = (t - S["t0"]) / 0.18
    if S["t0"] > 0 and a < 1:
        z = 1 + 0.06 * (1 - ease_out(a)); w, h = W / z, H / z
        c = c.crop((int((W - w) / 2), int((H - h) / 2), int((W + w) / 2), int((H + h) / 2))).resize((W, H), Image.BILINEAR)
        c.alpha_composite(Image.new("RGBA", (W, H), (255, 255, 255, int(70 * (1 - a)))))
    draw_tag(c)
    return c.convert("RGB")

VF = "scale=1080:1920:flags=lanczos:in_color_matrix=bt709:in_range=tv:out_range=pc,format=rgb24"
fsize = W * H * 3
if preview:
    for tp in preview:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{tp}", "-i", P["video"], "-vf", VF, "-frames:v", "1",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        compose(Image.frombytes("RGB", (W, H), raw[:fsize]), tp).save(f"{P['preview_dir']}/m_{tp:05.2f}.jpg", quality=88)
    sys.exit()

# ---------- SFX ----------
SR = 48000
dur = float(json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", P["video"]],
                                      capture_output=True).stdout)["format"]["duration"])
sfx = np.zeros(int(SR * (dur + 1)), np.float32); rng = np.random.default_rng(3)
def add(sig, t, g=1.0):
    i = int(max(0, t) * SR); sfx[i:i + len(sig)] += (sig * g)[:max(0, len(sfx) - i)]
def whoosh(d=.32):
    n = int(SR * d); x = rng.standard_normal(n).astype(np.float32); y = np.zeros(n, np.float32); k = 0.0
    a = np.linspace(.02, .35, n)
    for i in range(n): k += a[i] * (x[i] - k); y[i] = k
    return y * np.sin(np.linspace(0, np.pi, n)) ** 2 * .5
def tone(f0, f1, d, decay, amp):
    n = int(SR * d); tt = np.arange(n) / SR; f = f1 + (f0 - f1) * np.exp(-tt * 30)
    return (np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * decay) * amp).astype(np.float32)
def rise(d=.9):
    n = int(SR * d); tt = np.arange(n) / SR
    return (np.sin(2 * np.pi * np.cumsum(250 + 700 * (tt / d) ** 1.5) / SR) * (tt / d) ** .5 * (1 - tt / d) * .22).astype(np.float32)
WH_, POP, TICK, DING = whoosh(), tone(900, 260, .09, 45, .35), tone(2600, 1900, .025, 180, .18), tone(1320, 1320, .6, 7, .16)
for S in P["segments"]:
    if S["t0"] > 0: add(WH_, S["t0"] - .14)
    for tp in S.get("pulse", []): add(WH_, tp - .1, .35)
    k = S["kind"]
    if k == "people":
        for i in range(0, 42, 2): add(TICK, S["t0"] + 0.04 * i)
        if S.get("t_weeks"): add(rise(1.0), S["t_weeks"])
    if k == "sets":
        for g in range(3):
            for i in range(4): add(POP, S["t0"] + 0.18 * i + 0.05 * g + 0.28, .5)
    if k == "groups":
        for g in S["groups"]: add(POP, g["t"])
    if k == "compare":
        for x in (S.get("t_vs"), S.get("t_win")):
            if x: add(POP, x)
        if S.get("t_win"): add(DING, S["t_win"])
    if k == "bars":
        for col in S["columns"]:
            add(rise(), col["t"]); add(POP, col["t"] + .9, .6)
            if col.get("badge"): add(DING, col["badge"]["t"]); add(POP, col["badge"]["t"])
    if k == "pause":
        add(DING, S["pause"][1])
    if S.get("title"): add(POP, S["title"]["t"])
sfx_path = P["out_mp4"].replace(".mp4", "_sfx.wav")
with wave.open(sfx_path, "wb") as wf:
    wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(SR)
    wf.writeframes((np.clip(sfx * P.get("sfx_gain", .35), -1, 1) * 32767).astype(np.int16).tobytes())

dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", P["video"], "-vf", VF, "-r", str(FPS), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                       stdout=subprocess.PIPE)
enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
    "-i", P["video"], "-i", sfx_path, "-filter_complex",
    "[1:a]loudnorm=I=-14:TP=-1.5:LRA=11,aformat=sample_rates=48000:channel_layouts=stereo[a];"
    "[2:a]aformat=sample_rates=48000:channel_layouts=stereo[s];[a][s]amix=inputs=2:normalize=0:duration=first[out]",
    "-map", "0:v", "-map", "[out]", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", P["out_mp4"]], stdin=subprocess.PIPE)
f = 0
while True:
    buf = dec.stdout.read(fsize)
    if len(buf) < fsize: break
    enc.stdin.write(compose(Image.frombytes("RGB", (W, H), buf), f / FPS).tobytes())
    if f % 300 == 0: print("frame", f, flush=True)
    f += 1
dec.wait(); enc.stdin.close(); enc.wait()
print("DONE", f, "frames ->", P["out_mp4"])
