"""Đo các bản nén của PhoWhisper trên Kaggle (minhart, GPU T4). Minh 20/11/2026.

Chuyển vinai/PhoWhisper-{small,medium,large} sang CTranslate2 (float16, int8_float16, int8), chép
lời cùng một bộ đoạn ghi âm, đo: WER so với large float16 (bản gốc), hệ số thời gian thực trên T4
(và trên CPU cho bản nhỏ), dung lượng, VRAM cao nhất. Chỉ ghi SỐ ĐO ra bench.json: bản chép
lời (còn tên người thật) không rời Kaggle. Các model đã chuyển nằm ở /kaggle/working/models để
tải riêng bản được chọn.

Dùng: tools/kaggle_asr_bench.py dựng notebook từ tệp này.
"""

import ctypes
import glob
import json
import os
import site
import subprocess
import threading
import time

subprocess.run(["pip", "-q", "install", "faster-whisper>=1.1.1", "ctranslate2>=4.4", "transformers>=4.44",
                "sentencepiece", "jiwer", "nvidia-cublas-cu12", "nvidia-cudnn-cu12==9.*"], check=True)
for pat in ("nvidia/cublas/lib/libcublasLt.so.12", "nvidia/cublas/lib/libcublas.so.12",
            "nvidia/cudnn/lib/libcudnn*.so.9"):
    for sp in site.getsitepackages():
        for f in sorted(glob.glob(os.path.join(sp, pat))):
            ctypes.CDLL(f, mode=ctypes.RTLD_GLOBAL)

import jiwer  # noqa: E402
import numpy as np  # noqa: E402
from faster_whisper import WhisperModel  # noqa: E402

CLIP_S, N_CLIPS = 120, 6          # 6 đoạn x 2 phút lấy từ các ghi âm (không tải về máy)
SIZES = ["small", "medium", "large"]
QUANTS = ["float16", "int8_float16", "int8"]
OUT = "/kaggle/working"
MODELS = f"{OUT}/models"


def load_audio(path, start, dur):
    pcm = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", str(start), "-t", str(dur), "-i", path,
                          "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


files = sorted(p for p in glob.glob("/kaggle/input/**/*", recursive=True)
               if p.lower().endswith((".mp4", ".m4a", ".mp3", ".wav")))
clips = []
for i, f in enumerate(files):  # đoạn ở phút 5 và phút 15 của mỗi tệp
    for start in (300, 900):
        if len(clips) < N_CLIPS:
            a = load_audio(f, start, CLIP_S)
            if len(a) > 16000 * 30:
                clips.append(a)
audio_s = sum(len(c) for c in clips) / 16000
print(len(clips), "đoạn,", round(audio_s), "giây")


def convert(size, quant):
    out = f"{MODELS}/phowhisper-{size}-{quant}"
    if not os.path.exists(f"{out}/model.bin"):
        cmd = ["ct2-transformers-converter", "--model", f"vinai/PhoWhisper-{size}", "--output_dir", out,
               "--quantization", quant, "--copy_files", "tokenizer.json", "preprocessor_config.json"]
        if subprocess.run(cmd).returncode != 0:
            subprocess.run(cmd[:-3] + ["--force"], check=True)
    return out


def dir_mb(path):
    return round(sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(path) for f in fs) / 2**20)


def vram_peak(stop, box):
    while not stop.is_set():
        q = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True).stdout.split()
        if q:
            box[0] = max(box[0], max(int(x) for x in q))
        time.sleep(0.5)


def transcribe(path, device, compute, beam=5):
    m = WhisperModel(path, device=device, compute_type=compute, cpu_threads=4)
    stop, box = threading.Event(), [0]
    t = threading.Thread(target=vram_peak, args=(stop, box))
    t.start()
    t0 = time.time()
    texts = []
    for c in clips:
        segs, _ = m.transcribe(c, language="vi", beam_size=beam, vad_filter=True)
        texts.append(" ".join(s.text.strip() for s in segs))
    secs = time.time() - t0
    stop.set()
    t.join()
    del m
    return texts, secs, box[0]


norm = jiwer.Compose([jiwer.ToLowerCase(), jiwer.RemovePunctuation(), jiwer.RemoveMultipleSpaces(), jiwer.Strip()])
results = []
ref = None
for size in reversed(SIZES):  # large float16 trước: làm bản tham chiếu
    for quant in QUANTS:
        path = convert(size, quant)
        texts, secs, vram = transcribe(path, "cuda", quant)
        if ref is None:
            ref = texts
        wer = jiwer.wer([norm(x) for x in ref], [norm(x) for x in texts])
        row = {"model": f"PhoWhisper-{size}", "quant": quant, "device": "T4", "size_mb": dir_mb(path),
               "wer_vs_large_fp16": round(wer, 4), "rtf": round(secs / audio_s, 3),
               "x_realtime": round(audio_s / secs, 1), "vram_peak_mb": vram}
        results.append(row)
        print(row, flush=True)
        json.dump({"audio_s": round(audio_s), "clips": len(clips), "results": results},
                  open(f"{OUT}/bench.json", "w"), indent=1)

for size in ("small", "medium"):  # CPU 4 lõi: phương án chỉ CPU
    path = convert(size, "int8")
    texts, secs, _ = transcribe(path, "cpu", "int8", beam=1)
    wer = jiwer.wer([norm(x) for x in ref], [norm(x) for x in texts])
    row = {"model": f"PhoWhisper-{size}", "quant": "int8", "device": "CPU-4", "size_mb": dir_mb(path),
           "wer_vs_large_fp16": round(wer, 4), "rtf": round(secs / audio_s, 3),
           "x_realtime": round(audio_s / secs, 1), "vram_peak_mb": 0}
    results.append(row)
    print(row, flush=True)
    json.dump({"audio_s": round(audio_s), "clips": len(clips), "results": results},
              open(f"{OUT}/bench.json", "w"), indent=1)
print("xong")
