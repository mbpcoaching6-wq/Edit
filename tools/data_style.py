# "Science explainer" style edit for a talking head: condensed caps captions with colour-boxed keywords,
# a dark data panel (week counter, three labelled groups, rising result bars), punch-ins, SFX, loudness.
# Usage: data_style.py plan.json [t1,t2,...]   (times = preview stills only)
import json, sys, re, subprocess, math, wave, numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

P = json.load(open(sys.argv[1]))
ROOT = "/home/user/Edit"
ANTON, INTER = f"{ROOT}/fonts/Anton-Regular.ttf", f"{ROOT}/fonts/Inter.ttf"
W, H, FPS = 1080, 1920, 30
preview = [float(x) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 else None

COL = {"yellow": (255, 205, 60), "orange": (255, 112, 40), "cyan": (60, 205, 255), "white": (245, 245, 245)}
DIM = (130, 130, 130)

_f = {}
def font(path, size, var=None):
    k = (path, size, var)
    if k not in _f:
        f = ImageFont.truetype(path, size)
        if var: f.set_variation_by_name(var)
        _f[k] = f
    return _f[k]

def ease_back(a):
    a = min(max(a, 0), 1); c = 1.7
    return 1 + (c + 1) * (a - 1) ** 3 + c * (a - 1) ** 2
def ease_out(a):
    a = min(max(a, 0), 1); return 1 - (1 - a) ** 3

# ---------- words, keywords, groups ----------
words = json.load(open(P["words"]))["words"]
for i, txt in P.get("word_fixes", {}).items(): words[int(i)]["w"] = txt
words = [w for w in words if w["w"]]
for w in words: w["u"] = re.sub(r"[.,!?;:]+$", "", w["w"]).upper()

# keyword spans: list of [phrase, colour]; matched on consecutive uppercase words
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
    if not keep and (re.search(r"[.,!?;:]$", w["w"]) or len(cur) >= P.get("max_words", 4) or nxt is None
                     or words[nxt]["s"] - w["e"] > 0.4):
        groups.append(cur); cur = []
for gi, g in enumerate(groups):
    end = words[groups[gi + 1][0]]["s"] if gi + 1 < len(groups) else words[g[-1]]["e"] + 1.0
    for i in g: words[i]["g_end"] = min(end, words[g[-1]]["e"] + 1.2); words[i]["g"] = gi

CAP = P.get("caption_size", 92)
def layout(g, maxw):
    f = font(ANTON, CAP); sp = int(CAP * 0.26)
    lines, line, x = [], [], 0
    for i in g:
        wd = f.getbbox(words[i]["u"])[2]
        if line and x + sp + wd > maxw: lines.append(line); line, x = [], 0
        line.append((i, wd)); x += (sp if len(line) > 1 else 0) + wd
    lines.append(line)
    return lines, f, sp

def draw_caption(c, t, cy, maxw=940):
    g = next((g for g in groups if words[g[0]]["s"] - 0.03 <= t < words[g[0]]["g_end"]), None)
    if g is None: return
    lines, f, sp = layout(g, maxw)
    d = ImageDraw.Draw(c); lh = int(CAP * 1.18)
    y = cy - lh * len(lines) / 2
    asc = f.getbbox("H")[1]
    for line in lines:
        tw = sum(wd for _, wd in line) + sp * (len(line) - 1); x = (W - tw) / 2
        boxes = {}
        for i, wd in line:
            if words[i]["s"] > t + 0.02: x += wd + sp; continue
            a = ease_out((t - words[i]["s"]) / 0.12)
            colour = COL[col_of[i]] if col_of[i] else COL["white"]
            fill = tuple(int(DIM[k] + (colour[k] - DIM[k]) * a) for k in range(3))
            # shadow, then word
            d.text((x + 3, y + 5), words[i]["u"], font=f, fill=(0, 0, 0))
            d.text((x, y), words[i]["u"], font=f, fill=fill)
            if span_of[i] is not None:
                b = boxes.setdefault(span_of[i], [x, x + wd, col_of[i]]); b[1] = x + wd
            x += wd + sp
        for x0, x1, colour in boxes.values():
            pad = 12; top = y + asc - pad; bot = y + asc + (f.getbbox("H")[3] - asc) + pad
            d.rectangle((x0 - pad, top, x1 + pad, bot), outline=COL[colour], width=5)
        y += lh

# ---------- data panel ----------
PANEL_H = P.get("panel_h", 900)
_bg = None
def panel_bg():
    global _bg
    if _bg is None:
        yy = np.linspace(0, 1, PANEL_H)[:, None]; xx = np.linspace(-1, 1, W)[None, :]
        v = 1 - 0.55 * (xx ** 2) - 0.25 * yy
        img = np.stack([10 + 10 * v, 12 + 12 * v, 17 + 16 * v], -1).astype(np.uint8)
        im = Image.fromarray(img, "RGB"); d = ImageDraw.Draw(im)
        for gx in range(0, W, 60): d.line([(gx, 0), (gx, PANEL_H)], fill=(24, 28, 36))
        for gy in range(0, PANEL_H, 60): d.line([(0, gy), (W, gy)], fill=(24, 28, 36))
        _bg = im
    return _bg

def glow_rect(c, box, colour, width=4, glow=10, fill=None):
    lay = Image.new("RGBA", c.size, (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    d.rectangle(box, outline=colour + (255,), width=width, fill=(fill + (255,)) if fill else None)
    g = lay.filter(ImageFilter.GaussianBlur(glow))
    c.alpha_composite(g); c.alpha_composite(g); c.alpha_composite(lay)

def draw_panel(c, t, D):
    c.paste(panel_bg(), (0, 0))
    d = ImageDraw.Draw(c)
    cols = D["columns"]; xs = [W * (k + 1) / (len(cols) + 1) for k in range(len(cols))]
    lab_y, base, maxh, bw = D.get("label_y", 340), D.get("base_y", 820), D.get("max_h", 360), 120
    fl = font(INTER, 30, "ExtraBold")
    # week counter
    wk = D.get("weeks")
    if wk and wk["t0"] <= t:
        n = min(wk["n"], 1 + int((t - wk["t0"]) / max(0.01, (wk["t1"] - wk["t0"]) / wk["n"])))
        fw = font(INTER, 30, "Bold"); fn = font(ANTON, 58)
        box = (W / 2 - 120, 236, W / 2 + 120, 300)
        done = t >= wk["t1"]
        d.rectangle(box, outline=COL["yellow"] if done else (90, 90, 90), width=3, fill=(16, 18, 24))
        d.text((box[0] + 26, 252), "WEEK", font=fw, fill=(190, 190, 190))
        d.text((box[0] + 140, 236), str(n), font=fn, fill=COL["yellow"])
        for k in range(2): d.polygon([(box[0] + 188 + k * 16, 262), (box[0] + 198 + k * 16, 268), (box[0] + 188 + k * 16, 274)], fill=(150, 150, 150))
    for k, col in enumerate(cols):
        x = xs[k]; colour = COL[col["color"]]
        lit = any(a <= t < b for a, b in col.get("lit", []))
        tw = fl.getbbox(col["label"])[2]
        bx = (x - tw / 2 - 16, lab_y - 10, x + tw / 2 + 16, lab_y + 42)
        if lit: glow_rect(c, bx, colour, 4, 12, (16, 18, 24))
        else: d.rectangle(bx, outline=colour, width=3, fill=(16, 18, 24))
        ImageDraw.Draw(c).text((x - tw / 2, lab_y - 2), col["label"], font=fl, fill=colour)
        # empty tube
        d = ImageDraw.Draw(c)
        d.rectangle((x - bw / 2, base - maxh, x + bw / 2, base), outline=(60, 64, 72), width=3)
        for k2 in range(1, 6): d.line([(x - bw / 2, base - maxh * k2 / 6), (x - bw / 2 + 18, base - maxh * k2 / 6)], fill=(60, 64, 72), width=2)
        if lit and col.get("icon"):
            pass
        # bar fill
        if "value" in col and t >= col["t"]:
            a = ease_out((t - col["t"]) / 0.7)
            h = maxh * col["value"] / D["max_value"] * a
            if h > 4: glow_rect(c, (x - bw / 2 + 6, base - h, x + bw / 2 - 6, base - 3), colour, 1, 16, colour)
            fv = font(ANTON, 64); txt = f"+{round(col['value'] * a)}%"
            l, tp, r, b = fv.getbbox(txt)
            d = ImageDraw.Draw(c)
            d.text((x - (r - l) / 2 + 3, base - h - 96 + 4), txt, font=fv, fill=(0, 0, 0))
            d.text((x - (r - l) / 2, base - h - 96), txt, font=fv, fill=colour)
            if col.get("badge") and t >= col["badge"]["t"]:
                s = ease_back((t - col["badge"]["t"]) / 0.25)
                fb = font(ANTON, int(54 * max(s, 0.05)))
                bt = col["badge"]["text"]; l, tp, r, b = fb.getbbox(bt)
                cx, cy = x + bw / 2 + 70, base - h / 2
                d.rectangle((cx - (r - l) / 2 - 14, cy - (b - tp) / 2 - 12, cx + (r - l) / 2 + 14, cy + (b - tp) / 2 + 12), fill=COL["yellow"])
                d.text((cx - (r - l) / 2 - l, cy - (b - tp) / 2 - tp), bt, font=fb, fill=(20, 20, 20))
        d.text((x - 22, base + 14), "SIZE", font=font(INTER, 22, "Bold"), fill=(110, 110, 110))

def draw_tag(c):
    if not P.get("tag"): return
    f = font(INTER, 26, "ExtraBold"); txt = P["tag"]; tw = f.getbbox(txt)[2]
    d = ImageDraw.Draw(c); x1 = W - 40; x0 = x1 - tw - 36
    d.rounded_rectangle((x0, 40, x1, 86), radius=23, fill=COL["orange"])
    d.text((x0 + 18, 48), txt, font=f, fill=(255, 255, 255))

_grad = None
def top_grad(c):
    global _grad
    if _grad is None:
        g = np.zeros((int(H * .34), W, 4), np.uint8); g[..., 3] = (np.linspace(1, 0, g.shape[0]) ** 1.4 * 190)[:, None]
        _grad = Image.fromarray(g, "RGBA")
    c.alpha_composite(_grad)

# ---------- composition ----------
def seg_at(t):
    for s in P["segments"]:
        if s["t0"] <= t < s["t1"]: return s
    return P["segments"][-1]

def zoomed(src, t, seg):
    z = 1.0
    for a, b, zz in seg.get("punch", []):
        if a <= t < b: z = zz
    if z == 1.0: return src
    cx, cy = seg.get("zoom_center", [0.5, 0.35]); w, h = W / z, H / z
    x0 = min(max(cx * W - w / 2, 0), W - w); y0 = min(max(cy * H - h / 2, 0), H - h)
    return src.crop((int(x0), int(y0), int(x0 + w), int(y0 + h))).resize((W, H), Image.BICUBIC)

def compose(src, t):
    seg = seg_at(t)
    if seg["kind"] == "panel":
        c = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        fr = zoomed(src, t, seg); hh = H - PANEL_H
        cy = seg.get("face_y", 0.36) * H; y0 = int(min(max(cy - hh / 2, 0), H - hh))
        c.paste(fr.crop((0, y0, W, y0 + hh)), (0, PANEL_H))
        g = np.zeros((60, W, 4), np.uint8); g[..., 3] = np.linspace(255, 0, 60)[:, None].astype(np.uint8)
        g[..., :3] = (14, 16, 22); c.alpha_composite(Image.fromarray(g, "RGBA"), (0, PANEL_H))
        draw_panel(c, t, P["data"])
        draw_caption(c, t, 150)
    else:
        c = zoomed(src, t, seg).convert("RGBA"); top_grad(c)
        draw_caption(c, t, seg.get("cap_y", 0.17) * H)
        ti = seg.get("title")
        if ti and t >= ti["t"]:
            s = ease_back((t - ti["t"]) / 0.3); f = font(ANTON, int(ti.get("size", 230) * max(s, 0.05)))
            l, tp, r, b = f.getbbox(ti["text"]); d = ImageDraw.Draw(c); y = ti.get("y", 0.62) * H
            d.text(((W - (r - l)) / 2 + 5, y + 8), ti["text"], font=f, fill=(0, 0, 0))
            d.text(((W - (r - l)) / 2, y), ti["text"], font=f, fill=COL[ti.get("color", "yellow")])
    draw_tag(c)
    return c.convert("RGB")

VF = "scale=1080:1920:flags=lanczos:in_color_matrix=bt709:in_range=tv:out_range=pc,format=rgb24"
fsize = W * H * 3
if preview:
    for tp in preview:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{tp}", "-i", P["video"], "-vf", VF, "-frames:v", "1",
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        compose(Image.frombytes("RGB", (W, H), raw[:fsize]), tp).save(f"{P['preview_dir']}/d_{tp:05.2f}.jpg", quality=88)
    sys.exit()

# ---------- SFX ----------
SR = 48000
dur = float(json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", P["video"]],
                                      capture_output=True).stdout)["format"]["duration"])
sfx = np.zeros(int(SR * (dur + 1)), np.float32); rng = np.random.default_rng(2)
def add(sig, t):
    i = int(t * SR); sfx[i:i + len(sig)] += sig[:max(0, len(sfx) - i)]
def whoosh():
    n = int(SR * .35); x = rng.standard_normal(n).astype(np.float32); y = np.zeros(n, np.float32); k = 0.0
    a = np.linspace(.02, .35, n)
    for i in range(n): k += a[i] * (x[i] - k); y[i] = k
    return y * np.sin(np.linspace(0, np.pi, n)) ** 2 * .5
def tone(f0, f1, d, decay, amp):
    n = int(SR * d); tt = np.arange(n) / SR; f = f1 + (f0 - f1) * np.exp(-tt * 30)
    return (np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * decay) * amp).astype(np.float32)
WH_, POP, TICK, RISE = whoosh(), tone(900, 260, .09, 45, .35), tone(2400, 1800, .03, 160, .25), None
for s in P["segments"]:
    if s["t0"] > 0: add(WH_, max(0, s["t0"] - .12))
    for a, b, z in s.get("punch", []): add(WH_ * .4, max(0, a - .08))
D = P["data"]; wk = D.get("weeks")
if wk:
    for k in range(wk["n"]): add(TICK, wk["t0"] + k * (wk["t1"] - wk["t0"]) / wk["n"])
for col in D["columns"]:
    for a, b in col.get("lit", []): add(POP, a)
    if "t" in col:
        n = int(SR * .7); tt = np.arange(n) / SR
        add((np.sin(2 * np.pi * np.cumsum(300 + 500 * tt / .7) / SR) * (1 - tt / .7) * .12).astype(np.float32), col["t"])
    if col.get("badge"): add(POP, col["badge"]["t"])
for s in P["segments"]:
    if s.get("title"): add(POP, s["title"]["t"])
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
