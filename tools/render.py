# Big word behind the head + captions in front.  Usage: render.py config.json
# Config keys: video, words, masks, out_mp4, out_png, word, word_index, plus optional style overrides.
import json, sys, os, re, subprocess, numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

C = json.load(open(sys.argv[1]))
ROOT = "/home/user/Edit"
ANTON, INTER = f"{ROOT}/fonts/Anton-Regular.ttf", f"{ROOT}/fonts/Inter.ttf"
only_frame = int(sys.argv[2]) if len(sys.argv) > 2 else None  # preview a single frame

# ---------- source info ----------
pr = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
    "stream=width,height,r_frame_rate,nb_frames,color_space,color_transfer,color_primaries,color_range",
    "-of", "json", C["video"]], capture_output=True, check=True).stdout)["streams"][0]
W, H = pr["width"], pr["height"]
fn, fd = map(int, pr["r_frame_rate"].split("/")); FPS = fn / fd
CS = pr.get("color_space", "bt709"); TRC = pr.get("color_transfer", "bt709")
PRI = pr.get("color_primaries", "bt709"); RNG = pr.get("color_range", "tv")
MATRIX = {"bt2020nc": "bt2020", "bt2020c": "bt2020", "bt709": "bt709", "smpte170m": "bt601",
          "bt470bg": "bt601"}.get(CS, "bt709")
HDR = TRC in ("arib-std-b67", "smpte2084")
# "white" in HDR video = reference white (HLG 75%), so text looks white, not glaring
WHITE = C.get("white_level", 0.75 if HDR else 1.0)
COLOR = np.array(C.get("word_color", [1, 1, 1]), np.float32) * WHITE
CAP_COLOR = np.array(C.get("caption_color", [1, 1, 1]), np.float32) * WHITE

words = json.load(open(C["words"]))["words"]
WI = C["word_index"]
T_WORD = words[WI]["s"]
F_WORD = int(np.ceil(T_WORD * FPS - 1e-6))

def mask_at(f):
    p = os.path.join(C["masks"], f"{f:05d}.png")
    if not os.path.exists(p): return None
    m = Image.open(p).convert("L").resize((W, H), Image.BICUBIC)
    return np.asarray(m, np.float32) / 255.0

# ---------- big word layer ----------
def text_layer(text, font, fill=255):
    l, t, r, b = font.getbbox(text)
    im = Image.new("L", (r - l, b - t), 0)
    ImageDraw.Draw(im).text((-l, -t), text, font=font, fill=fill)
    return im

word_text = C["word"].upper()
wfont_path = C.get("word_font", ANTON)
size = 400
for _ in range(30):  # size the word to the requested share of the frame width
    w_img = text_layer(word_text, ImageFont.truetype(wfont_path, size))
    ratio = C.get("word_width", 0.85) * W / w_img.width
    if abs(ratio - 1) < 0.002: break
    size = max(10, int(round(size * ratio)))
WORD = np.asarray(w_img, np.float32) / 255.0
WH, WW = WORD.shape
x0 = (W - WW) // 2

m0 = mask_at(F_WORD)
assert m0 is not None, "cut-out for the big-word frame is missing"
band = m0[:, int(0.3 * W):int(0.7 * W)] > 0.5
rows = np.where(band.sum(1) >= max(3, 0.01 * band.shape[1]))[0]
head_top = int(rows[0]) if len(rows) else H // 3

def coverage(y):
    ys, ye = max(0, y), min(H, y + WH)
    g = WORD[ys - y:ye - y]
    return float((g * m0[ys:ye, x0:x0 + WW]).sum() / WORD.sum())

notes = []
if "word_y" in C:                     # user asked for a position: honour it as given
    y0 = int(C["word_y"] * H)
else:
    y0 = int(round(head_top - 0.4 * WH))   # head covers the bottom ~60% of the letters
    y0 = max(y0, int(0.02 * H))
    if coverage(y0) < 0.15:
        y = y0
        while coverage(y) < 0.15 and y + WH < 0.9 * H and coverage(y) < 0.6:
            y += max(1, H // 400)
        notes.append(f"lowered word {y - y0}px to reach {coverage(y):.0%} cover")
        y0 = y
cov = coverage(y0)

# ---------- captions ----------
CAP_SIZE = int(C.get("caption_size", 0.07) * W)
cfont = ImageFont.truetype(C.get("caption_font", INTER), CAP_SIZE)
try: cfont.set_variation_by_name(C.get("caption_weight", "Bold"))
except Exception: pass
cap_words = [dict(w, i=i) for i, w in enumerate(words) if i != WI]   # big word isn't captioned twice
groups, cur = [], []
for k, w in enumerate(cap_words):
    cur.append(w)
    nxt = cap_words[k + 1] if k + 1 < len(cap_words) else None
    brk = (re.search(r"[.,!?;:]$", w["w"]) or len(cur) == 3 or nxt is None
           or nxt["i"] == WI + 1 and w["i"] == WI - 1          # break around the big word
           or (nxt and nxt["s"] - w["e"] > 0.35))              # natural pause
    if brk: groups.append(cur); cur = []
for g_i, g in enumerate(groups):
    g_end = groups[g_i + 1][0]["s"] if g_i + 1 < len(groups) else 1e9
    for w in g: w["g_end"] = g_end
line_h = int(CAP_SIZE * 1.25)
gap = int(0.02 * H)
if "caption_y" in C:
    cap_y = int(C["caption_y"] * H)
else:
    cap_y = y0 - gap - line_h                      # just above the big word
    cap_y = min(cap_y, int(0.65 * H) - line_h)
    if cap_y < 0.15 * H:                           # no room above inside the safe band
        below = y0 + WH + gap
        if below + line_h <= 0.65 * H:
            cap_y = below; notes.append("captions placed BELOW the word: no room above inside 15-65%")
        else:
            cap_y = int(0.15 * H); notes.append("captions overlap the word area: no free room in 15-65%")
SHADOW_BLUR = max(2, CAP_SIZE // 8)

def caption_rgba(t):
    g = next((g for g in groups if g[0]["s"] <= t < g[0]["g_end"]), None)
    if g is None: return None
    shown = [w["w"] for w in g if w["s"] <= t]
    full = " ".join(w["w"] for w in g)
    fl, _, fr, _ = cfont.getbbox(full)
    asc, desc = cfont.getmetrics()
    pad = SHADOW_BLUR * 3
    im = Image.new("L", (fr - fl + 2 * pad, asc + desc + 2 * pad), 0)
    # centre the whole group so words don't shift as they appear
    ImageDraw.Draw(im).text((pad - fl, pad), " ".join(shown), font=cfont, fill=255)
    a = np.asarray(im, np.float32) / 255.0
    sh = np.asarray(im.filter(ImageFilter.GaussianBlur(SHADOW_BLUR)), np.float32) / 255.0
    sh = np.roll(sh, (CAP_SIZE // 20, CAP_SIZE // 30), (0, 1)) * 0.75
    return a, sh, (W - a.shape[1]) // 2, cap_y - pad

POP = [0.80, 0.92, 1.01, 1.05, 1.03, 1.01]     # 6 frames, ~5% overshoot

def word_at(f):
    k = f - F_WORD
    s = POP[k] if k < len(POP) else 1.0
    s = min(s, (W - 2) / WW)                     # never wider than the frame
    if s == 1.0: return WORD, x0, y0
    nw, nh = max(1, int(WW * s)), max(1, int(WH * s))
    img = np.asarray(Image.fromarray((WORD * 255).astype(np.uint8)).resize((nw, nh), Image.BICUBIC), np.float32) / 255
    cx, cy = x0 + WW / 2, y0 + WH / 2
    return img, int(cx - nw / 2), int(cy - nh / 2)

def paste(canvas_a, img, x, y):
    h, w = img.shape
    xs, ys, xe, ye = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if xe <= xs or ye <= ys: return
    canvas_a[ys:ye, xs:xe] = np.maximum(canvas_a[ys:ye, xs:xe], img[ys - y:ye - y, xs - x:xe - x])

def over(frame, alpha, color):
    frame *= (1 - alpha)[..., None]; frame += alpha[..., None] * color

# ---------- frame loop ----------
dec = ["ffmpeg", "-v", "error", "-i", C["video"], "-vf",
       f"scale=in_color_matrix={MATRIX}:in_range={RNG}:out_range=pc,format=rgb48le",
       "-f", "rawvideo", "-pix_fmt", "rgb48le", "-"]
tags = ["-colorspace", CS, "-color_primaries", PRI, "-color_trc", TRC, "-color_range", RNG]
if only_frame is None:
    enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb48le",
        "-s", f"{W}x{H}", "-r", pr["r_frame_rate"], "-i", "-", "-i", C["video"],
        "-map", "0:v", "-map", "1:a?", "-vf",
        f"scale=in_range=pc:out_color_matrix={MATRIX}:out_range={RNG},format=yuv420p",
        "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-profile:v", "high",
        *tags, "-c:a", "copy", "-movflags", "+faststart", "-shortest", C["out_mp4"]],
        stdin=subprocess.PIPE)
else:
    dec[3:3] = ["-ss", f"{only_frame / FPS:.4f}"]; dec.insert(dec.index("-f"), "-frames:v"); dec.insert(dec.index("-f"), "1")

p = subprocess.Popen(dec, stdout=subprocess.PIPE)
fsize = W * H * 3 * 2
f = only_frame or 0
png_frame = C.get("png_frame", F_WORD + 15)
while True:
    buf = p.stdout.read(fsize)
    if len(buf) < fsize: break
    frame = np.frombuffer(buf, np.uint16).reshape(H, W, 3).astype(np.float32) / 65535
    if f >= F_WORD:
        a = np.zeros((H, W), np.float32)
        paste(a, *word_at(f))
        m = mask_at(f)
        if m is None: m = mask_at(f - 1) if mask_at(f - 1) is not None else np.zeros((H, W), np.float32)
        over(frame, a * (1 - m), COLOR)           # word behind: only where you're not
    cap = caption_rgba(f / FPS)
    if cap:
        ca, sh, cx, cy = cap
        sa = np.zeros((H, W), np.float32); paste(sa, sh, cx, cy); over(frame, sa, np.zeros(3, np.float32))
        aa = np.zeros((H, W), np.float32); paste(aa, ca, cx, cy); over(frame, aa, CAP_COLOR)
    out = (np.clip(frame, 0, 1) * 65535 + 0.5).astype(np.uint16).tobytes()
    if only_frame is not None:
        raw = C["out_png"] + ".raw"; open(raw, "wb").write(out); break
    enc.stdin.write(out)
    if f == png_frame:
        raw = C["out_png"] + ".raw"; open(raw, "wb").write(out)
    if f % 60 == 0: print(f"frame {f}", flush=True)
    f += 1
p.stdout.close(); p.wait()
if only_frame is None: enc.stdin.close(); enc.wait()

# PNG of a big-word frame, converted to normal (SDR) colours for viewing
raw = C["out_png"] + ".raw"
if os.path.exists(raw):
    zp = {"bt2020": "2020", "bt709": "709"}.get(PRI, "709")
    vf = (f"zscale=pin={zp}:p=709:tin={TRC}:t=709:rin=full:r=full:npl=203,format=rgb24") if HDR \
         else f"scale=in_color_matrix={MATRIX}:in_range=pc,format=rgb24"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb48le",
        "-s", f"{W}x{H}", "-i", raw, "-vf", vf, "-frames:v", "1", C["out_png"]], check=True)
    os.remove(raw)

print(json.dumps(dict(size=f"{W}x{H}", fps=round(FPS, 3), hdr=HDR, word_frame=F_WORD, head_top=head_top,
    word_box=[x0, y0, WW, WH], head_cover=round(cov, 3), caption_y=cap_y, caption_px=CAP_SIZE,
    groups=len(groups), notes=notes)))
