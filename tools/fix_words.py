import json, sys, numpy as np
# usage: fix_words.py words.json audio.npy out.json fixes.json
d = json.load(open(sys.argv[1])); audio = np.load(sys.argv[2]); fixes = json.load(open(sys.argv[4]))
words = d["words"]
for i, txt in fixes.items():          # a fixed word keeps the time of the word it replaces
    words[int(i)]["w"] = txt
sr, hop = 16000, 160                    # 10 ms frames
n = len(audio) // hop
rms = np.sqrt(np.mean(audio[:n*hop].reshape(n, hop)**2, axis=1) + 1e-10)
db = 20*np.log10(rms); db = np.convolve(db, np.ones(3)/3, mode="same")
moved = []
for k, w in enumerate(words):
    s = w["s"]; nxt = words[k+1]["s"] if k+1 < len(words) else s+0.3
    a = max(0, int((s-0.03)*100)); b = min(n-1, int(min(s+0.22, nxt-0.02, w["e"])*100))
    if b - a < 3: continue
    jump = db[a+2:b+1] - db[a:b-1]       # rise over 20 ms
    j = int(np.argmax(jump))
    if jump[j] > 4.0:                    # a clear rise in loudness = the real start
        t = round((a + j + 1) / 100, 3)
        if abs(t - s) >= 0.02: moved.append((w["w"], s, t))
        w["s"] = t
json.dump(dict(words=words), open(sys.argv[3], "w"), indent=1)
print("moved", len(moved), "of", len(words)); print(moved[:12])
print("mean shift", round(np.mean([t-s for _, s, t in moved]), 3) if moved else 0)
