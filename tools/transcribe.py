import sys, json, subprocess, numpy as np
from faster_whisper import WhisperModel
video, out = sys.argv[1], sys.argv[2]
raw = subprocess.run(["ffmpeg","-v","error","-i",video,"-vn","-ac","1","-ar","16000","-f","f32le","-"],capture_output=True,check=True).stdout
audio = np.frombuffer(raw, np.float32).copy()
np.save(out.replace(".json",".npy"), audio)
m = WhisperModel("small", device="cpu", compute_type="int8", download_root="/home/user/Edit/models/whisper")
segs, info = m.transcribe(audio, word_timestamps=True, beam_size=5, vad_filter=False)
words = [dict(w=x.word.strip(), s=round(x.start,3), e=round(x.end,3), p=round(x.probability,2)) for s in segs for x in s.words]
json.dump(dict(lang=info.language, words=words), open(out,"w"), indent=1)
print(info.language, len(words))
print(" ".join(w["w"] for w in words))
print("LOW:", [(i,w["w"],w["p"]) for i,w in enumerate(words) if w["p"]<0.6])
