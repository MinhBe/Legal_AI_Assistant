"""Ghi mức dùng CPU/RAM/GPU mỗi 30 s vào /kaggle/working/util.csv (theo yêu cầu của Minh).

Dùng trong notebook:
    import sys; sys.path.insert(0, "/kaggle/input/<dataset>")
    import util_monitor as um
    um.start()                 # luồng nền
    um.phase("unsloth_1gpu")   # nhãn giai đoạn cho các dòng tiếp theo
    ...
    um.stop(); um.summary()    # trung bình theo giai đoạn

CPU% là tổng qua các lõi (4 lõi = tối đa 400 %), như Minh thấy trên giao diện Kaggle.
"""

from __future__ import annotations

import csv
import subprocess
import threading
import time
from pathlib import Path

CSV = Path("/kaggle/working/util.csv")
_state = {"phase": "init", "stop": False, "thread": None}


def phase(name: str) -> None:
    _state["phase"] = name


def _gpus() -> list[tuple[int, float, float]]:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,utilization.gpu,memory.used",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10).stdout
    except Exception:  # noqa: BLE001 — không có GPU thì chỉ ghi CPU/RAM
        return []
    rows = []
    for line in out.strip().splitlines():
        idx, util, mem = (x.strip() for x in line.split(","))
        rows.append((int(idx), float(util), float(mem)))
    return rows


def _loop(every: float) -> None:
    import psutil

    psutil.cpu_percent(percpu=True)  # lần đầu luôn trả 0
    new = not CSV.exists()
    with CSV.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["ts", "phase", "cpu_pct_sum", "ram_gb", "gpu0_util", "gpu0_mem_mb",
                        "gpu1_util", "gpu1_mem_mb"])
        while not _state["stop"]:
            time.sleep(every)
            cpu = sum(psutil.cpu_percent(percpu=True))
            ram = psutil.virtual_memory().used / 1e9
            g = {i: (u, m) for i, u, m in _gpus()}
            w.writerow([round(time.time()), _state["phase"], round(cpu, 1), round(ram, 2),
                        *g.get(0, ("", "")), *g.get(1, ("", ""))])
            f.flush()


def start(every: float = 30.0) -> None:
    if _state["thread"] is None:
        t = threading.Thread(target=_loop, args=(every,), daemon=True)
        t.start()
        _state["thread"] = t


def stop() -> None:
    _state["stop"] = True


def summary() -> dict:
    """Trung bình theo giai đoạn: cpu_pct_sum, gpu0_util, gpu1_util, ram_gb."""
    if not CSV.exists():
        return {}
    rows = list(csv.DictReader(CSV.open()))
    out: dict[str, dict] = {}
    for r in rows:
        s = out.setdefault(r["phase"], {"n": 0, "cpu": 0.0, "g0": 0.0, "g1": 0.0, "ram": 0.0})
        s["n"] += 1
        s["cpu"] += float(r["cpu_pct_sum"] or 0)
        s["ram"] += float(r["ram_gb"] or 0)
        s["g0"] += float(r["gpu0_util"] or 0)
        s["g1"] += float(r["gpu1_util"] or 0)
    res = {p: {"samples": s["n"], "cpu_pct_sum": round(s["cpu"] / s["n"], 1),
               "gpu0_util": round(s["g0"] / s["n"], 1), "gpu1_util": round(s["g1"] / s["n"], 1),
               "ram_gb": round(s["ram"] / s["n"], 2)} for p, s in out.items() if s["n"]}
    for p, s in res.items():
        print(f"{p:16s} CPU {s['cpu_pct_sum']:6.1f}%  GPU0 {s['gpu0_util']:5.1f}%  "
              f"GPU1 {s['gpu1_util']:5.1f}%  RAM {s['ram_gb']:.1f} GB  ({s['samples']} mẫu)")
    return res
