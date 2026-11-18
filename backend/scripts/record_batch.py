"""Lô ghi âm tư vấn của Minh: chép lời trong máy (CPU) -> che PII -> phân tích thử.

Bản gốc ở record/ không bị đụng tới: script đọc bản sao trong data/raw/record/ (gitignore).
Mọi đầu ra nằm ở data/raw/record/out/:
  <stem>.raw.json     đoạn + timestamp từng từ, CÒN dữ liệu cá nhân, chỉ trên máy
  <stem>.map.json     ánh xạ che PII (giá trị gốc), chỉ trên máy
  <stem>.masked.json  đoạn đã che; chỉ bản này được gửi Dahl
  progress.json       tiến độ lô

  python -m scripts.record_batch bench --model large-v3 --clips 0:900,2:1800,4:3600
  python -m scripts.record_batch transcribe --model large-v3
  python -m scripts.record_batch analyze --file <stem> --start 600 --end 1500

Chép lời chạy lại được giữa chừng: tệp đã có .masked.json thì bỏ qua.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path

from app.audio import convert, transcribe
from app.audio.spoken_pii import add_ner, mask_lines

SRC = Path("data/raw/record")
OUT = SRC / "out"
THREADS = 8  # chừa lõi cho API và lượt sinh dữ liệu đang chạy


def _model(name: str, threads: int = THREADS):
    from faster_whisper import WhisperModel

    return WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=threads)


def _write(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def _run(model, wav: Path, total: float, label: str) -> list[dict]:
    segments, _ = model.transcribe(
        transcribe._read_wav(wav), language="vi", vad_filter=True, word_timestamps=True,
        beam_size=5,
    )
    out, t0, last = [], time.monotonic(), 0.0
    for seg in segments:
        out.append({
            "start": round(seg.start, 2), "end": round(seg.end, 2),
            "text": (seg.text or "").strip(),
            "words": [[round(w.start, 2), round(w.end, 2), w.word] for w in seg.words or []],
        })
        now = time.monotonic()
        if now - last > 60:
            last = now
            speed = seg.end / max(1.0, now - t0)
            print(f"{label}: {seg.end / max(total, 1):.0%} ({speed:.2f}x thời gian thực)",
                  flush=True)
    return out


def mask_segments(segs: list[dict], window_s: float = 300) -> list:
    """Che PII từng đoạn; NER trong máy chạy theo cửa sổ 5 phút (đủ ngữ cảnh, ít lời gọi).

    Trả danh sách đoạn đã che, phần tử cuối là ánh xạ (chỉ lưu trên máy)."""
    from app.llm.router import get_router

    router = get_router()
    mapping: dict[str, str] = {}
    windows: dict[int, list[str]] = {}
    for s in segs:
        windows.setdefault(int(s["start"] // window_s), []).append(s["text"])
    for texts in windows.values():
        add_ner(router, "\n".join(texts), mapping)
    # che cả bản một lượt (ngữ cảnh vắt qua ranh giới đoạn), rồi tách lại từng đoạn
    masked = mask_lines([s["text"] for s in segs], mapping=mapping)
    out: list = [{"start": s["start"], "end": s["end"], "text": t}
                 for s, t in zip(segs, masked, strict=True)]
    out.append(mapping)
    return out


def _clip(src: Path, offset: float, seconds: float, out: Path) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", str(offset), "-t", str(seconds), "-i", str(src),
         "-vn", "-ac", "1", "-ar", "16000", str(out)],
        check=True, timeout=600,
    )
    return out


def bench(args) -> None:
    """Bake-off: một model trên vài đoạn ngắn ở các bản ghi khác nhau.

    Mỗi lần chạy một model (chạy lại cho model khác) để đo RAM đỉnh của riêng nó.
    Bản chép thô chỉ nằm trên máy; bản đã che để gửi đi so sánh.
    """
    import resource

    out = OUT / "bench"
    out.mkdir(parents=True, exist_ok=True)
    files = sorted(SRC.glob("*.mp4"))
    name = args.model
    tag = Path(name).name
    t0 = time.monotonic()
    model = _model(name)
    report = {"model": name, "load_s": round(time.monotonic() - t0), "clips": {}}
    for spec in args.clips.split(","):
        idx, offset = spec.split(":")
        clip_id = f"f{idx}_{offset}"
        wav = out / f"{clip_id}.wav"
        if not wav.exists():
            _clip(files[int(idx)], float(offset), args.clip, wav)
        t1 = time.monotonic()
        segs = _run(model, wav, args.clip, f"{tag} {clip_id}")
        took = time.monotonic() - t1
        raw = "\n".join(f"[{s['start']:.0f}] {s['text']}" for s in segs)
        (out / f"{tag}.{clip_id}.raw.txt").write_text(raw, encoding="utf-8")
        _write(out / f"{tag}.{clip_id}.raw.json", segs)
        report["clips"][clip_id] = {"transcribe_s": round(took),
                                    "x_realtime": round(args.clip / took, 2)}
        print(tag, clip_id, report["clips"][clip_id], flush=True)
    report["max_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    _write(out / f"{tag}.json", report)
    print(report, flush=True)


def mask_bench(_args) -> None:
    """Che bản chép bench; mỗi đoạn dùng chung một ánh xạ cho mọi model để so cạnh nhau."""
    from app.llm.router import get_router

    out = OUT / "bench"
    router = get_router()
    by_clip: dict[str, list[Path]] = {}
    for r in sorted(out.glob("*.raw.txt")):
        by_clip.setdefault(r.name.split(".")[-3], []).append(r)
    for files in by_clip.values():
        mapping: dict[str, str] = {}
        segs_by = {}
        for f in files:  # dòng "[giây] lời"
            rows = [line.split("] ", 1) for line in f.read_text(encoding="utf-8").splitlines()]
            segs_by[f] = [{"start": float(a.lstrip("[")), "text": b}
                          for a, b in (r for r in rows if len(r) == 2)]
        for segs in segs_by.values():
            add_ner(router, "\n".join(x["text"] for x in segs), mapping)
        for f, segs in segs_by.items():
            masked = mask_lines([x["text"] for x in segs], mapping=mapping)
            f.with_name(f.name.replace(".raw.txt", ".masked.txt")).write_text(
                "\n".join(f"[{x['start']:.0f}] {t}" for x, t in zip(segs, masked, strict=True)),
                encoding="utf-8")


def transcribe_all(args) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    files = sorted(SRC.glob("*.mp4"))
    model = None
    for i, src in enumerate(files, 1):
        stem = src.stem.replace(" ", "_")
        if (OUT / f"{stem}.masked.json").exists():
            continue
        total = convert.duration(src) or 0.0
        _write(OUT / "progress.json", {"model": args.model, "file": stem, "index": i,
                                       "files": len(files), "started": time.time()})
        model = model or _model(args.model, args.threads)
        wav = _clip(src, 0, total + 1, OUT / f"{stem}-16k.wav")
        t0 = time.monotonic()
        try:
            segs = _run(model, wav, total, stem)
        finally:
            wav.unlink(missing_ok=True)
        _write(OUT / f"{stem}.raw.json", {"file": src.name, "duration_s": total,
                                          "model": args.model, "segments": segs})
        # che PII ngay sau chép lời; ánh xạ dùng chung trong một tệp để placeholder nhất quán
        masked = mask_segments(segs)
        mapping = masked.pop()
        _write(OUT / f"{stem}.map.json", mapping)
        _write(OUT / f"{stem}.masked.json", {"file": src.name, "duration_s": total,
                                             "model": args.model, "segments": masked,
                                             "transcribe_s": round(time.monotonic() - t0)})
        print(f"xong {stem}: {len(segs)} đoạn, {time.monotonic() - t0:.0f}s", flush=True)
    _write(OUT / "progress.json", {"model": args.model, "done": True, "files": len(files)})


def remask(stem: str, reuse_map: bool = False) -> dict[str, str]:
    """Che lại <stem>.raw.json bằng mã hiện tại (bản đang chạy có thể nạp mã che cũ).

    reuse_map: giữ giá trị NER đã tìm ở lần trước (lọc lại bằng luật hiện tại) thay vì gọi
    mô hình lại cả tệp (~1 giờ khi máy bận); chỉ chạy lại các lớp luật."""
    from app.audio.spoken_pii import _plausible

    raw = json.loads((OUT / f"{stem}.raw.json").read_text(encoding="utf-8"))
    if reuse_map and (OUT / f"{stem}.map.json").exists():
        old = json.loads((OUT / f"{stem}.map.json").read_text(encoding="utf-8"))
        mapping = {}
        for ph, value in old.items():
            etype = ph.strip("[]").rsplit("_", 1)[0]
            if etype in {"TÊN", "TỔ_CHỨC", "ĐỊA_CHỈ", "SĐT", "STK"} and _plausible(etype, value):
                mapping[ph] = value
        texts = mask_lines([s["text"] for s in raw["segments"]], mapping=mapping)
        masked = [{"start": s["start"], "end": s["end"], "text": t}
                  for s, t in zip(raw["segments"], texts, strict=True)]
    else:
        masked = mask_segments(raw["segments"])
        mapping = masked.pop()
    _write(OUT / f"{stem}.map.json", mapping)
    _write(OUT / f"{stem}.masked.json", {**{k: v for k, v in raw.items() if k != "segments"},
                                         "segments": masked, "masker": "mask_lines"})
    return mapping


# Cửa sổ cần lượt hai: số đọc thành chữ ghép (trăm/mươi/nghìn…) hoặc từ khoá trích dẫn
_PASS2 = re.compile(
    r"(?<!\w)(?:điều|khoản|điểm|nghị định|thông tư|luật số|số hiệu|bộ luật|triệu|nghìn|ngàn|tỷ|tỉ"
    r"|trăm|mươi|phần trăm|năm hai nghìn)(?!\w)",
    re.IGNORECASE,
)


def pass2(stem: str, model_name: str = "medium", threads: int = 4) -> None:
    """Lượt hai bằng Whisper medium chỉ trên các đoạn có số / trích dẫn (Tech Lead duyệt)."""
    from faster_whisper import WhisperModel

    raw = json.loads((OUT / f"{stem}.raw.json").read_text(encoding="utf-8"))
    hits = [s for s in raw["segments"] if _PASS2.search(s["text"])]
    windows: list[list[float]] = []
    for s in hits:  # gộp đoạn sát nhau để Whisper có ngữ cảnh
        a, b = max(0.0, s["start"] - 1.0), s["end"] + 1.0
        if windows and a - windows[-1][1] < 3.0:
            windows[-1][1] = b
        else:
            windows.append([a, b])
    src = SRC / raw["file"]
    wav = _clip(src, 0, raw["duration_s"] + 1, OUT / f"{stem}-pass2.wav")
    try:
        audio = transcribe._read_wav(wav)
        model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=threads)
        out = []
        for a, b in windows:
            segs, _ = model.transcribe(audio[int(a * 16000):int(b * 16000)], language="vi",
                                       vad_filter=False, beam_size=5)
            text = " ".join((x.text or "").strip() for x in segs).strip()
            out.append({"start": round(a, 2), "end": round(b, 2), "text": text})
    finally:
        wav.unlink(missing_ok=True)
    _write(OUT / f"{stem}.pass2.raw.json", {"model": model_name, "windows": out})
    mask_pass2(stem)
    print(f"pass2 {stem}: {len(windows)} cửa sổ, {sum(b - a for a, b in windows):.0f}s âm thanh",
          flush=True)


def mask_pass2(stem: str) -> None:
    """Che <stem>.pass2.raw.json bằng ánh xạ của tệp (lượt hai có thể thêm tên mới)."""
    raw = json.loads((OUT / f"{stem}.pass2.raw.json").read_text(encoding="utf-8"))
    mapping = json.loads((OUT / f"{stem}.map.json").read_text(encoding="utf-8"))
    masked = mask_lines([w["text"] for w in raw["windows"]], mapping=mapping)
    _write(OUT / f"{stem}.map.json", mapping)
    _write(OUT / f"{stem}.pass2.masked.json", {"model": raw["model"], "windows": [
        {**w, "text": t} for w, t in zip(raw["windows"], masked, strict=True)]})


def import_kaggle(args) -> None:
    """Bản chép thô từ notebook Kaggle (asr/kaggle_asr.ipynb) -> che PII TRÊN MÁY NÀY."""
    src_dir = Path(args.dir)
    for raw_path in sorted(src_dir.glob("*.raw.json")):
        if raw_path.name.endswith(".pass2.raw.json"):
            continue
        stem = raw_path.name[: -len(".raw.json")]
        if src_dir.resolve() != OUT.resolve():
            (OUT / raw_path.name).write_bytes(raw_path.read_bytes())
            p2 = src_dir / f"{stem}.pass2.raw.json"
            if p2.exists():
                (OUT / p2.name).write_bytes(p2.read_bytes())
        remask(stem)
        if (OUT / f"{stem}.pass2.raw.json").exists():
            mask_pass2(stem)
        print("đã che", stem, flush=True)


def follow(_args) -> None:
    """Theo lô chép lời: tệp nào xong PhoWhisper thì che lại bằng mã mới rồi chạy lượt hai."""
    files = sorted(SRC.glob("*.mp4"))
    for src in files:
        stem = src.stem.replace(" ", "_")
        while not (OUT / f"{stem}.masked.json").exists():
            time.sleep(60)
        if not (OUT / f"{stem}.pass2.masked.json").exists():
            remask(stem)
            pass2(stem)
    print("FOLLOW_DONE", flush=True)


def _ts(s: float) -> str:
    s = int(s)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def window(stem: str, start: float, end: float) -> str:
    data = json.loads((OUT / f"{stem}.masked.json").read_text(encoding="utf-8"))
    return "\n".join(f"[{_ts(s['start'])}] {s['text']}" for s in data["segments"]
                     if start <= s["start"] < end)


def analyze(args) -> None:
    """Rút bài toán cho một cửa sổ bằng CẢ mô hình trong máy và Dahl (bản đã che)."""
    from app.llm.router import get_router
    from app.problems.extract import extract

    text = window(args.file, args.start, args.end)
    mapping = json.loads((OUT / f"{args.file}.map.json").read_text(encoding="utf-8"))
    router = get_router()
    result = {"file": args.file, "start": args.start, "end": args.end}
    for who, dahl in (("local", False), ("dahl", True)):
        t0 = time.monotonic()
        result[who] = extract(router, text, start_ts=args.start, end_ts=args.end,
                              allow_dahl=dahl, mapping=mapping)
        result[f"{who}_s"] = round(time.monotonic() - t0)
    path = OUT / "analysis" / f"{args.file}_{int(args.start)}_{int(args.end)}.json"
    path.parent.mkdir(exist_ok=True)
    _write(path, result)
    print(path)


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bench")
    b.add_argument("--model", required=True, help="tên faster-whisper hoặc thư mục CT2")
    b.add_argument("--clip", type=float, default=180)
    b.add_argument("--clips", default="0:900,2:1800,4:3600", help="chỉ_số_tệp:giây_bắt_đầu")
    t = sub.add_parser("transcribe")
    t.add_argument("--model", default="large-v3")
    t.add_argument("--threads", type=int, default=THREADS, help="ít luồng = máy mát hơn")
    sub.add_parser("mask-bench")
    sub.add_parser("follow")
    k = sub.add_parser("import-kaggle")
    k.add_argument("--dir", required=True, help="thư mục asr_out tải từ Kaggle")
    a = sub.add_parser("analyze")
    a.add_argument("--file", required=True)
    a.add_argument("--start", type=float, required=True)
    a.add_argument("--end", type=float, required=True)
    args = p.parse_args()
    {"bench": bench, "transcribe": transcribe_all, "analyze": analyze,
     "mask-bench": mask_bench, "follow": follow,
     "import-kaggle": import_kaggle}[args.cmd](args)


if __name__ == "__main__":
    main()
