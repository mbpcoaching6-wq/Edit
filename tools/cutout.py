# Cut-out masks with rembg birefnet-portrait. Resumable: skips masks that already exist.
# Order: the big-word frame first, then every 2nd frame, then the frames in between.
import os, sys, time, onnxruntime as ort
from rembg import new_session, remove
from PIL import Image
src, dst = sys.argv[1], sys.argv[2]
names = sorted(os.listdir(src))
order = names[::2] + names[1::2]
o = ort.SessionOptions(); o.enable_cpu_mem_arena = False; o.enable_mem_pattern = False
s = new_session("birefnet-portrait", sess_opts=o)
done = sum(os.path.exists(os.path.join(dst, n.replace(".jpg", ".png"))) for n in names)
t0 = time.time(); k = 0
for n in order:
    out = os.path.join(dst, n.replace(".jpg", ".png"))
    if os.path.exists(out): continue
    m = remove(Image.open(os.path.join(src, n)), session=s, only_mask=True, post_process_mask=False)
    m.save(out + ".tmp.png"); os.replace(out + ".tmp.png", out)
    k += 1; done += 1
    print(f"{done}/{len(names)} done, {(time.time()-t0)/k:.1f}s/frame", flush=True)
print("CUTOUT DONE", flush=True)
