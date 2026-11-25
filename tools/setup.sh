#!/bin/bash
set -e
cd /home/user/Edit
export U2NET_HOME=/home/user/Edit/models/rembg HF_HOME=/home/user/Edit/models/hf HF_HUB_DISABLE_XET=1
echo "== step: python packages"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q faster-whisper "rembg[cpu]" pillow numpy
echo "== step: video tools (FFmpeg, yt-dlp, HyperFrames)"
command -v ffmpeg >/dev/null || { apt-get update -qq && apt-get install -y -qq ffmpeg; }
.venv/bin/pip install -q -U yt-dlp
command -v hyperframes >/dev/null || npm install -g hyperframes
ffmpeg -version | head -1
.venv/bin/yt-dlp --version
hyperframes --version
echo "== step: fonts"
curl -sSfL -o fonts/Anton-Regular.ttf "https://raw.githubusercontent.com/google/fonts/main/ofl/anton/Anton-Regular.ttf"
curl -sSfL -o "fonts/Inter.ttf" "https://raw.githubusercontent.com/google/fonts/main/ofl/inter/Inter%5Bopsz,wght%5D.ttf"
echo "== step: speech model (~0.5 GB)"
.venv/bin/python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8', download_root='/home/user/Edit/models/whisper'); print('speech model ready')"
echo "== step: cut-out model (~1 GB)"
.venv/bin/python -c "from rembg import new_session; new_session('birefnet-portrait'); print('cut-out model ready')"
echo "== ALL DONE"
