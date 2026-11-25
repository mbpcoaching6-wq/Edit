# Reel-style edit: graphic cards, split screens, punch-in zooms, word captions, pill captions, SFX.
# Usage: reel_style.py plan.json
# The plan lists timed segments; see plans/B87A62EA.json for an example.
import json, sys, re, subprocess, math, wave, numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

P = json.load(open(sys.argv[1]))
ROOT = "/home/user/Edit"
INTER = f"{ROOT}/fonts/Inter.ttf"
W, H, FPS = 1080, 1920, 30
preview = [float(x) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 else None  # times for stills

BG = (237, 237, 237)
YEL, YEL_D, YEL_DD = (246, 197, 72), (226, 168, 40), (200, 140, 25)
INK = (34, 34, 34)
PILL = (118, 118, 118, 235)

_fonts = {}
def font(size, weight="Bold"):
    k = (size, weight)
    if k not in _fonts:
        f = ImageFont.truetype(INTER, size); f.set_variation_by_name(weight); _fonts[k] = f
    return _fonts[k]

def ease_back(a):            # overshoot pop, a in 0..1
    a = min(max(a, 0), 1); c = 1.9
    return 1 + (c + 1) * (a - 1) ** 3 + c * (a - 1) ** 2

def ease_out(a):
    a = min(max(a, 0), 1); return 1 - (1 - a) ** 3

# ---------- sprites (RGBA, cached) ----------
_spr = {}
def cached(key, fn):
    if key not in _spr: _spr[key] = fn()
    return _spr[key]

def text_sprite(text, size, fill, weight="Bold", shadow=0):
    def mk():
        f = font(size, weight); l, t, r, b = f.getbbox(text)
        pad = shadow * 3 + 4
        im = Image.new("RGBA", (r - l + 2 * pad, b - t + 2 * pad), (0, 0, 0, 0))
        if shadow:
            sh = Image.new("L", im.size, 0)
            ImageDraw.Draw(sh).text((pad - l, pad - t + shadow // 2), text, font=f, fill=170)
            sh = sh.filter(ImageFilter.GaussianBlur(shadow))
            im.paste((0, 0, 0, 255), (0, 0), sh)
        ImageDraw.Draw(im).text((pad - l, pad - t), text, font=f, fill=fill)
        return im
    return cached(("t", text, size, fill, weight, shadow), mk)

def pill_sprite(text, size=56, fill=PILL, color=(255, 255, 255)):
    def mk():
        f = font(size); l, t, r, b = f.getbbox(text)
        px, py = int(size * 0.32), int(size * 0.18)
        im = Image.new("RGBA", (r - l + 2 * px, b - t + 2 * py), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((0, 0, im.width - 1, im.height - 1), radius=int(size * 0.22), fill=fill)
        d.text((px - l, py - t), text, font=f, fill=color)
        return im
    return cached(("p", text, size, fill, color), mk)

def glyph(d, kind, cx, cy, s, col=INK):
    """Small dark symbol drawn flat at (cx, cy), size s."""
    if kind == "dumbbell":
        d.rounded_rectangle((cx - s * .55, cy - s * .06, cx + s * .55, cy + s * .06), s * .05, fill=col)
        for sx in (-1, 1):
            d.rounded_rectangle((cx + sx * s * .42 - s * .08, cy - s * .3, cx + sx * s * .42 + s * .08, cy + s * .3), s * .05, fill=col)
            d.rounded_rectangle((cx + sx * s * .6 - s * .06, cy - s * .2, cx + sx * s * .6 + s * .06, cy + s * .2), s * .04, fill=col)
    elif kind == "warn":
        d.polygon([(cx, cy - s * .45), (cx + s * .5, cy + s * .4), (cx - s * .5, cy + s * .4)], fill=col)
        d.rounded_rectangle((cx - s * .05, cy - s * .18, cx + s * .05, cy + s * .14), s * .03, fill=YEL)
        d.ellipse((cx - s * .06, cy + s * .2, cx + s * .06, cy + s * .32), fill=YEL)
    elif kind == "check":
        d.line([(cx - s * .38, cy), (cx - s * .1, cy + s * .28), (cx + s * .42, cy - s * .3)], fill=col, width=max(3, int(s * .16)), joint="curve")
    elif kind == "down":
        d.rectangle((cx - s * .1, cy - s * .42, cx + s * .1, cy + s * .05), fill=col)
        d.polygon([(cx - s * .34, cy), (cx + s * .34, cy), (cx, cy + s * .42)], fill=col)
    elif kind == "up":
        d.polygon([(cx - s * .5, cy + s * .35), (cx - s * .1, cy - s * .05), (cx + s * .1, cy + s * .12), (cx + s * .45, cy - s * .3)],
                  outline=None, fill=None)
        d.line([(cx - s * .5, cy + s * .35), (cx - s * .1, cy - s * .05), (cx + s * .1, cy + s * .12), (cx + s * .42, cy - s * .25)],
               fill=col, width=max(3, int(s * .13)), joint="curve")
        d.polygon([(cx + s * .5, cy - s * .38), (cx + s * .22, cy - s * .32), (cx + s * .44, cy - s * .1)], fill=col)

def tile_sprite(kind, s=320):
    """Flat isometric yellow tile (like the reel's diamond icons) with a symbol on top."""
    def mk():
        th = int(s * .09); w, h = s, int(s * .5)
        im = Image.new("RGBA", (w + 40, h + th + 60), (0, 0, 0, 0))
        ox, oy = 20, 20
        sh = Image.new("L", im.size, 0)
        ImageDraw.Draw(sh).polygon([(ox + w / 2, oy + th + 18), (ox + w, oy + h / 2 + th + 18), (ox + w / 2, oy + h + th + 18), (ox, oy + h / 2 + th + 18)], fill=70)
        im.paste((0, 0, 0, 255), (0, 0), sh.filter(ImageFilter.GaussianBlur(14)))
        d = ImageDraw.Draw(im)
        top = [(ox + w / 2, oy), (ox + w, oy + h / 2), (ox + w / 2, oy + h), (ox, oy + h / 2)]
        d.polygon([top[3], top[2], (top[2][0], top[2][1] + th), (top[3][0], top[3][1] + th)], fill=YEL_D)
        d.polygon([top[2], top[1], (top[1][0], top[1][1] + th), (top[2][0], top[2][1] + th)], fill=YEL_DD)
        d.polygon(top, fill=YEL)
        glyph(d, kind, ox + w / 2, oy + h / 2, s * .32)
        return im
    return cached(("tile", kind, s), mk)

def cube_sprite(kind, s=270):
    def mk():
        im = Image.new("RGBA", (s + 40, int(s * 1.15) + 60), (0, 0, 0, 0))
        ox, oy = 20, 20; w = s; q = s * .29
        sh = Image.new("L", im.size, 0)
        ImageDraw.Draw(sh).ellipse((ox + w * .1, oy + s * 1.0, ox + w * .9, oy + s * 1.12), fill=80)
        im.paste((0, 0, 0, 255), (0, 0), sh.filter(ImageFilter.GaussianBlur(12)))
        d = ImageDraw.Draw(im)
        A, B, C, D = (ox + w / 2, oy), (ox + w, oy + q), (ox + w / 2, oy + 2 * q), (ox, oy + q)
        dn = s * .58
        d.polygon([D, C, (C[0], C[1] + dn), (D[0], D[1] + dn)], fill=YEL_D)
        d.polygon([C, B, (B[0], B[1] + dn), (C[0], C[1] + dn)], fill=YEL_DD)
        d.polygon([A, B, C, D], fill=YEL)
        glyph(d, kind, ox + w / 2, oy + q, s * .26)
        return im
    return cached(("cube", kind, s), mk)

def row_sprite(text, kind="check", w=720):
    def mk():
        f = font(48, "SemiBold"); rh = 104
        im = Image.new("RGBA", (w, rh), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        d.rounded_rectangle((0, 0, w - 1, rh - 1), radius=20, fill=(255, 255, 255))
        d.ellipse((24, rh / 2 - 28, 80, rh / 2 + 28), fill=YEL)
        glyph(d, kind, 52, rh / 2, 40)
        l, t, r, b = f.getbbox(text)
        d.text((108 - l, (rh - (b - t)) / 2 - t), text, font=f, fill=INK)
        return im
    return cached(("row", text, kind, w), mk)

def paste(canvas, spr, cx, cy, scale=1.0, alpha=1.0, anchor="c"):
    if scale <= 0.01 or alpha <= 0.01: return
    if abs(scale - 1) > 0.005:
        spr = spr.resize((max(1, int(spr.width * scale)), max(1, int(spr.height * scale))), Image.BICUBIC)
    if alpha < 1:
        spr = spr.copy(); spr.putalpha(spr.getchannel("A").point(lambda v: int(v * alpha)))
    x = int(cx - spr.width / 2); y = int(cy - spr.height / 2) if anchor == "c" else int(cy)
    canvas.alpha_composite(spr, (x, y)) if 0 <= x and 0 <= y and x + spr.width <= canvas.width and y + spr.height <= canvas.height \
        else canvas.paste(spr, (x, y), spr)

def pop(t, t0, dur=0.28):    # entrance: scale with overshoot + fade
    a = (t - t0) / dur
    if a < 0: return 0, 0
    return ease_back(a), ease_out(a * 1.6)

# ---------- words / captions ----------
words = json.load(open(P["words"]))["words"]
for i, txt in P.get("word_fixes", {}).items(): words[int(i)]["w"] = txt

def groups_in(t0, t1, maxw=3):
    ws = [w for w in words if t0 - 0.05 <= w["s"] < t1]
    gs, cur = [], []
    for k, w in enumerate(ws):
        cur.append(w); nxt = ws[k + 1] if k + 1 < len(ws) else None
        if re.search(r"[.,!?;:]$", w["w"]) or len(cur) == maxw or nxt is None or nxt["s"] - w["e"] > 0.35:
            gs.append(cur); cur = []
    return gs

def clean(s): return re.sub(r"[.,!?;:]+$", "", s)

def segment_at(t):
    for s in P["segments"]:
        if s["t0"] <= t < s["t1"]: return s
    return P["segments"][-1]

# ---------- footage ----------
def footage_frame(src, t, seg):
    z = seg.get("zoom", 1.0)
    if isinstance(z, list):                       # slow push: [start, end]
        a = (t - seg["t0"]) / (seg["t1"] - seg["t0"]); z = z[0] + (z[1] - z[0]) * ease_out(a) if a < 1 else z[1]
    for p in seg.get("punch", []):                # hard punch-ins inside a segment
        if p[0] <= t < p[1]: z = p[2]
    if z == 1.0: return src
    cx, cy = seg.get("zoom_center", [0.5, 0.5])
    w, h = W / z, H / z
    x0 = min(max(cx * W - w / 2, 0), W - w); y0 = min(max(cy * H - h / 2, 0), H - h)
    return src.crop((int(x0), int(y0), int(x0 + w), int(y0 + h))).resize((W, H), Image.BICUBIC)

# ---------- segment painters ----------
def draw_word_captions(c, t, seg):
    y = seg.get("cap_y", 0.47) * H
    for w in words:
        nxt = next((x for x in words if x["s"] > w["s"]), None)
        end = min(nxt["s"] if nxt else w["e"] + 0.4, w["e"] + 0.6)
        if w["s"] <= t < end and seg["t0"] - 0.05 <= w["s"] < seg["t1"]:
            sc, al = pop(t, w["s"], 0.16)
            paste(c, text_sprite(clean(w["w"]), 92, (255, 255, 255), "ExtraBold", shadow=10), W / 2, y, 0.85 + 0.15 * sc, al)

def draw_pill_captions(c, t, seg, y):
    for g in groups_in(seg["t0"], seg["t1"]):
        g_end = g[-1]["e"] + 0.5
        if g[0]["s"] <= t < g_end:
            nxt = [x for x in groups_in(seg["t0"], seg["t1"]) if x[0]["s"] > g[0]["s"]]
            if nxt and t >= nxt[0][0]["s"]: continue
            text = " ".join(w["w"] for w in g if w["s"] <= t + 0.02)
            paste(c, pill_sprite(clean(text)), W / 2, y)

def draw_graphic(c, t, seg, top, bottom):
    """Heading + icon (+ rows / flow) laid out in the band [top, bottom]."""
    g = seg["graphic"]; mid = (top + bottom) / 2
    rows = g.get("rows", []); flow = g.get("flow")
    icon_h = 300 if g.get("icon_type") == "cube" else 200
    block = 110 + icon_h + (len(rows) * 122 + 40 if rows else 0) + (150 if flow else 0)
    y = mid - block / 2
    sc, al = pop(t, g.get("t", seg["t0"]))
    paste(c, text_sprite(g["heading"], 84, INK, "ExtraBold"), W / 2, y + 45, sc, al)
    y += 110
    spr = cube_sprite(g["icon"]) if g.get("icon_type") == "cube" else tile_sprite(g["icon"])
    sc2, al2 = pop(t, g.get("t", seg["t0"]) + 0.08)
    bob = 6 * math.sin((t - seg["t0"]) * 2.4)
    paste(c, spr, W / 2, y + icon_h / 2 + bob, sc2, al2)
    y += icon_h + 20
    if flow:
        a, b, ta, tb = flow["from"], flow["to"], flow["t_from"], flow["t_to"]
        s1, a1 = pop(t, ta); s2, a2 = pop(t, tb)
        paste(c, pill_sprite(a, 56, (255, 255, 255, 255), INK), W / 2 - 230, y + 60, s1, a1)
        paste(c, pill_sprite(b, 56, (226, 84, 64, 255), (255, 255, 255)), W / 2 + 230, y + 60, s2, a2)
        if t >= ta:
            prog = ease_out((t - ta) / max(0.3, tb - ta))
            d = ImageDraw.Draw(c); x0, x1 = W / 2 - 110, W / 2 - 110 + 220 * prog
            d.line([(x0, y + 60), (x1, y + 60)], fill=INK, width=8)
            if prog > 0.9: d.polygon([(x1 + 4, y + 60), (x1 - 22, y + 44), (x1 - 22, y + 76)], fill=INK)
    if rows:
        pw = 800; ph = len(rows) * 122 + 34
        shown = [r for r in rows if t >= r["t"]]
        if shown:
            s0, a0 = pop(t, rows[0]["t"])
            panel = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
            ImageDraw.Draw(panel).rounded_rectangle((0, 0, pw - 1, ph - 1), radius=28, fill=YEL)
            paste(c, panel, W / 2, y + ph / 2, 0.9 + 0.1 * s0, a0)
            for k, r in enumerate(shown):
                sr, ar = pop(t, r["t"], 0.22)
                paste(c, row_sprite(r["text"], r.get("icon", "check")), W / 2, y + 17 + 52 + k * 122, sr, ar)

_grad = None
def draw_title(c, t, seg, ti):
    global _grad
    if _grad is None:
        g = np.zeros((int(H * .32), W, 4), np.uint8); g[..., 3] = (np.linspace(1, 0, g.shape[0]) ** 1.5 * 170)[:, None]
        _grad = Image.fromarray(g, "RGBA")
    c.alpha_composite(_grad, (0, 0))
    s, a = pop(t, ti["t"], 0.35)
    y = ti.get("y", 0.09) * H
    paste(c, text_sprite(ti["small"], 66, (255, 255, 255), "Bold", shadow=12), W / 2, y, s, a)
    paste(c, text_sprite(ti["big"], ti.get("size", 170), (255, 255, 255), "Black", shadow=18), W / 2, y + 140, s, a)

def draw_chips(c, t, seg):
    for ch in seg.get("chips", []):
        if ch["t"] <= t < ch.get("t_end", seg["t1"]):
            s, a = pop(t, ch["t"], 0.22)
            col = tuple(ch.get("bg", [20, 20, 20, 225])); fg = tuple(ch.get("fg", [255, 255, 255]))
            spr = pill_sprite(ch["text"], ch.get("size", 54), col, fg)
            if ch.get("icon"):
                spr2 = Image.new("RGBA", (spr.width + 70, spr.height), (0, 0, 0, 0))
                d = ImageDraw.Draw(spr2); d.rounded_rectangle((0, 0, spr2.width - 1, spr2.height - 1), radius=int(spr.height * .3), fill=col)
                d.ellipse((16, spr.height / 2 - 24, 64, spr.height / 2 + 24), fill=YEL)
                glyph(d, ch["icon"], 40, spr.height / 2, 34)
                spr2.alpha_composite(spr.crop((10, 0, spr.width, spr.height)), (70, 0)); spr = spr2
            paste(c, spr, ch.get("x", 0.5) * W, ch.get("y", 0.7) * H, s, a)

def compose(src, t):
    seg = segment_at(t); kind = seg["kind"]
    if kind == "footage":
        c = footage_frame(src, t, seg).convert("RGBA")
        if seg.get("title"): draw_title(c, t, seg, seg["title"])
        draw_chips(c, t, seg)
        if seg.get("captions", "words") == "words": draw_word_captions(c, t, seg)
        elif seg.get("captions") == "pill": draw_pill_captions(c, t, seg, 0.80 * H)
    elif kind == "split":
        split = seg.get("split_y", 0.42) * H
        c = Image.new("RGBA", (W, H), BG + (255,))
        crop_c = seg.get("crop_center", 0.62) * H; hh = H - split
        y0 = int(min(max(crop_c - hh / 2, 0), H - hh))
        fr = footage_frame(src, t, seg).crop((0, y0, W, y0 + int(hh)))
        c.paste(fr, (0, int(split)))
        draw_graphic(c, t, seg, 60, split - 40)
        draw_pill_captions(c, t, seg, split)
    else:  # card
        c = Image.new("RGBA", (W, H), BG + (255,))
        draw_graphic(c, t, seg, 0.12 * H, 0.74 * H)
        draw_pill_captions(c, t, seg, 0.83 * H)
    return c.convert("RGB")

# ---------- render ----------
VF = ("zscale=w=1080:h=1920:filter=lanczos,zscale=tin=arib-std-b67:min=bt2020nc:pin=bt2020:rin=tv:t=linear:npl=203,"
      "format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=pc,format=rgb24") \
     if P.get("hdr", True) else "scale=1080:1920,format=rgb24"
fsize = W * H * 3

if preview:
    for tp in preview:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{tp}", "-i", P["video"], "-vf", VF, "-frames:v", "1",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        compose(Image.frombytes("RGB", (W, H), raw[:fsize]), tp).save(f"{P['preview_dir']}/p_{tp:05.2f}.jpg", quality=88)
    sys.exit()

# SFX: synthesized whoosh on every cut to a graphic, soft pop on every element entrance
SR = 48000
dur = float(json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", P["video"]],
                                      capture_output=True).stdout)["format"]["duration"])
sfx = np.zeros(int(SR * (dur + 1)), np.float32); rng = np.random.default_rng(1)
def add(sig, t):
    i = int(t * SR); sfx[i:i + len(sig)] += sig[:len(sfx) - i]
def whoosh():
    n = int(SR * .35); x = rng.standard_normal(n).astype(np.float32)
    env = np.sin(np.linspace(0, np.pi, n)) ** 2
    y = np.zeros(n, np.float32); k = 0.0
    a = np.linspace(.02, .35, n)  # one-pole low-pass sweeping open = rising whoosh
    for i in range(n): k += a[i] * (x[i] - k); y[i] = k
    return y * env * .5
def popsfx():
    n = int(SR * .09); tt = np.arange(n) / SR
    f = 900 * np.exp(-tt * 30) + 260
    return (np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * 45) * .35).astype(np.float32)
W_, P_ = whoosh(), popsfx()
prev = None
for s in P["segments"]:
    if s["kind"] != "footage" or (prev and prev["kind"] != "footage"): add(W_, max(0, s["t0"] - .12))
    if s.get("title"): add(P_, s["title"]["t"])
    g = s.get("graphic", {})
    for r in g.get("rows", []): add(P_, r["t"])
    if g.get("flow"): add(P_, g["flow"]["t_from"]); add(P_, g["flow"]["t_to"])
    for ch in s.get("chips", []): add(P_, ch["t"])
    for p in s.get("punch", []): add(W_ * .5, max(0, p[0] - .1))
    prev = s
sfx_path = P["out_mp4"].replace(".mp4", "_sfx.wav")
with wave.open(sfx_path, "wb") as wf:
    wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(SR)
    wf.writeframes((np.clip(sfx * P.get("sfx_gain", .5), -1, 1) * 32767).astype(np.int16).tobytes())

dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", P["video"], "-vf", VF, "-r", str(FPS), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                       stdout=subprocess.PIPE)
enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
    "-i", P["video"], "-i", sfx_path, "-filter_complex", "[1:a]loudnorm=I=-14:TP=-1.5:LRA=11,aformat=sample_rates=48000:channel_layouts=stereo[a];"
    "[2:a]aformat=sample_rates=48000:channel_layouts=stereo[s];[a][s]amix=inputs=2:normalize=0:duration=first[out]",
    "-map", "0:v", "-map", "[out]", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", P["out_mp4"]], stdin=subprocess.PIPE)
f = 0
while True:
    buf = dec.stdout.read(fsize)
    if len(buf) < fsize: break
    enc.stdin.write(compose(Image.frombytes("RGB", (W, H), buf), f / FPS).tobytes())
    if f % 150 == 0: print("frame", f, flush=True)
    f += 1
dec.wait(); enc.stdin.close(); enc.wait()
print("DONE", f, "frames ->", P["out_mp4"])
