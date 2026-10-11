# -*- coding: utf-8 -*-
"""כרטיס מסך אמיתי שמריץ את הקוד שלנו: Apple MPS על רנר macOS ציבורי.

זה הפער שנרשם ב-BENCHMARK.md כ"אין כזה". רנרי ubuntu/windows אכן
בלי GPU, אבל רנר macos-15 הוא Apple Silicon עם Metal, ו-PyTorch
מריץ עליו דיפוזיה. מאגר ציבורי = דקות בלתי מוגבלות גם ב-macOS.
"""
import json, os, platform, subprocess, sys, time
from pathlib import Path
OUT = Path("artifacts"); OUT.mkdir(exist_ok=True)
rep = {"platform": platform.platform(), "machine": platform.machine()}

try:
    rep["sysctl_mem"] = subprocess.run(["sysctl", "-n", "hw.memsize"],
        capture_output=True, text=True).stdout.strip()
    rep["cpu"] = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
        capture_output=True, text=True).stdout.strip()
    rep["chip"] = subprocess.run(["sysctl", "-n", "hw.model"],
        capture_output=True, text=True).stdout.strip()
except Exception as e:
    rep["sysctl_err"] = str(e)

import torch
rep["torch"] = torch.__version__
rep["mps_available"] = bool(torch.backends.mps.is_available())
rep["mps_built"] = bool(torch.backends.mps.is_built())
print("MPS זמין:", rep["mps_available"], "| שבב:", rep.get("chip"),
      "| זיכרון:", rep.get("sysctl_mem"), flush=True)

if rep["mps_available"]:
    # מדידת כושר: כפל מטריצות על Metal מול מעבד
    import torch as T
    for dev in ("cpu", "mps"):
        try:
            a = T.randn(2048, 2048, device=dev)
            b = T.randn(2048, 2048, device=dev)
            if dev == "mps": T.mps.synchronize()
            t = time.time()
            for _ in range(20):
                c = a @ b
            if dev == "mps": T.mps.synchronize()
            rep[f"matmul_{dev}_s"] = round(time.time() - t, 3)
        except Exception as e:
            rep[f"matmul_{dev}_err"] = str(e)[:200]
    print("כפל מטריצות - מעבד:", rep.get("matmul_cpu_s"),
          "ש · Metal:", rep.get("matmul_mps_s"), "ש", flush=True)

(OUT / "mps_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
print(json.dumps(rep, ensure_ascii=False, indent=1), flush=True)
