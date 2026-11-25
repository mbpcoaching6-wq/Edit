# Cut pauses out of a talking-head clip (jump cuts) and shift word timings to match.
# Usage: cut_silence.py video audio.npy words.json out.mp4 out_words.json [thresh_db_above_floor=5] [min_gap=0.18]
import sys, json, subprocess, numpy as np
video, npy, wj, out, out_w = sys.argv[1:6]
above = float(sys.argv[6]) if len(sys.argv) > 6 else 5.0
min_gap = float(sys.argv[7]) if len(sys.argv) > 7 else 0.25
PRE, POST, FPS = 0.07, 0.10, 30
# cut from a 1080p proxy: trimming 4K HEVC many times at once runs out of memory
proxy = out.replace(".mp4", "_proxy.mp4")
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", video, "-vf", "scale=1080:1920:flags=lanczos,fps=30", "-c:v", "libx264",
                "-preset", "fast", "-crf", "10", "-pix_fmt", "yuv420p", "-c:a", "copy", proxy], check=True)

a = np.load(npy); hop = 160; n = len(a) // hop
db = 20 * np.log10(np.sqrt((a[:n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-9)
db = np.convolve(db, np.ones(5) / 5, "same")
floor = np.percentile(db, 10); quiet = db < floor + above
dur = float(json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", video],
                                      capture_output=True).stdout)["format"]["duration"])
words = json.load(open(wj))["words"]

# silent runs -> cut regions (keep a little air either side of speech)
cuts, i = [], 0
while i < n:
    if quiet[i]:
        j = i
        while j < n and quiet[j]: j += 1
        s, e = i / 100, j / 100
        if e - s >= min_gap:
            cs, ce = (0 if i == 0 else s + POST), (dur if j >= n else e - PRE)
            # never cut through a word's core (whisper says someone is speaking there)
            # loudness only: whisper's word edges drift into pauses. Re-transcribe the result to check nothing was clipped.
            if ce - cs > 0.06:
                cuts.append([cs, ce])
        i = j
    else: i += 1
snap = lambda t: round(t * FPS) / FPS
cuts = [[snap(s), snap(e)] for s, e in cuts if snap(e) - snap(s) >= 1 / FPS]
keep, t = [], 0.0
for s, e in cuts:
    if s > t: keep.append([t, s])
    t = e
if t < dur - 1 / FPS: keep.append([t, snap(dur)])
keep = [k for k in keep if k[1] - k[0] >= 0.3 or quiet[int(k[0] * 100):int(k[1] * 100)].mean() < 0.5]

def remap(x):
    out_t = 0.0
    for s, e in keep:
        if x < s: return out_t
        if x <= e: return out_t + x - s
        out_t += e - s
    return out_t
for w in words: w["s"], w["e"] = round(remap(w["s"]), 3), round(remap(w["e"]), 3)
json.dump(dict(words=words, keep=keep), open(out_w, "w"), indent=1)

fc, cat = [], ""
for k, (s, e) in enumerate(keep):
    L = e - s; f = min(0.012, L / 4)
    fc.append(f"[0:v]trim={s:.4f}:{e:.4f},setpts=PTS-STARTPTS[v{k}]")
    fc.append(f"[0:a]atrim={s:.4f}:{e:.4f},asetpts=PTS-STARTPTS,afade=t=in:d={f:.4f},afade=t=out:st={L - f:.4f}:d={f:.4f}[a{k}]")
    cat += f"[v{k}][a{k}]"
fc.append(f"{cat}concat=n={len(keep)}:v=1:a=1[v][a]")
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", proxy, "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "fast", "-crf", "12", "-pix_fmt", "yuv420p", "-colorspace", "bt709",
                "-color_primaries", "bt709", "-color_trc", "bt709", "-c:a", "aac", "-b:a", "256k", out], check=True)
new = sum(e - s for s, e in keep)
print(f"floor {floor:.1f} dB, {len(cuts)} cuts, {dur:.2f}s -> {new:.2f}s (removed {dur - new:.2f}s)")
print("cuts:", [(round(s, 2), round(e, 2)) for s, e in cuts])
