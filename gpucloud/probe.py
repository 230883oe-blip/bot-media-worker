# -*- coding: utf-8 -*-
r"""
בדיקת כרטיס מסך על רנר ציבורי של GitHub Actions - רץ *על הרנר*, לא כאן.

מה הוא מוכיח (או מפריך):
  1. יש בכלל חומרת GPU על הרנר (Metal על אפל, CUDA על לינוקס).
  2. ה-GPU הזה מריץ **את הקוד שלנו**: כפל מטריצות דרך PyTorch, מול אותו
     חישוב בדיוק על המעבד. היחס הוא התשובה.
  3. הצוואר האמיתי שלנו - ראסטריזציה של WebGL בדפדפן נסתר - מואץ בחומרה.
     נמדד דרך Chrome headless מול דף שמצייר N פריימים עם gl.finish().

למה דווקא רנרים של אפל (07/10/2026): רנרי ubuntu/windows של GitHub הם
מכונות וירטואליות ב-Azure בלי GPU כלל (נמדד: nvidia-smi לא קיים). רנרי
macos-14/15 הם Apple Silicon פיזי עם GPU משולב של 8-10 ליבות, והוא חשוף
גם ל-Metal וגם ל-WebGL. למאגר ציבורי הדקות חינמיות.

פלט: JSON אחד ל-stdout וגם לקובץ probe_<label>.json.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LABEL = os.environ.get("PROBE_LABEL", "unknown")


def sh(cmd: list[str] | str, timeout: int = 180) -> str:
    """פקודת מערכת עם timeout מפורש. שגיאה אינה מפילה את הבדיקה."""
    try:
        r = subprocess.run(cmd, shell=isinstance(cmd, str), timeout=timeout,
                           capture_output=True, text=True, errors="replace")
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:                                   # noqa: BLE001
        return f"<<{type(e).__name__}: {e}>>"


# ---------------------------------------------------------------- 1. חומרה

def machine() -> dict:
    out = {
        "label": LABEL,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or platform.machine(),
        "python": platform.python_version(),
        "logical_cores": os.cpu_count(),
    }
    sysname = platform.system()
    if sysname == "Darwin":
        out["cpu_brand"] = sh(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
        out["ram_gb"] = round(int(sh(["sysctl", "-n", "hw.memsize"]).strip() or 0)
                              / 1024 ** 3, 1)
        disp = sh(["system_profiler", "SPDisplaysDataType"], timeout=120)
        out["gpu_raw"] = disp[:1200]
        for ln in disp.splitlines():
            s = ln.strip()
            if s.startswith("Chipset Model:"):
                out["gpu"] = s.split(":", 1)[1].strip()
            elif s.startswith("Total Number of Cores:"):
                out["gpu_cores"] = s.split(":", 1)[1].strip()
    else:
        try:
            out["ram_gb"] = round(os.sysconf("SC_PAGE_SIZE")
                                  * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3, 1)
        except Exception:                                    # noqa: BLE001
            pass
        out["nvidia_smi"] = bool(shutil.which("nvidia-smi"))
        if out["nvidia_smi"]:
            out["gpu"] = sh(["nvidia-smi", "--query-gpu=name",
                             "--format=csv,noheader"]).strip()
        else:
            out["gpu"] = None
    return out


# ------------------------------------------------- 2. חישוב: GPU מול מעבד

def torch_bench() -> dict:
    """אותו כפל מטריצות על ה-GPU ועל המעבד. זה 'הקוד שלנו' בגרסה מינימלית."""
    res: dict = {"available": False}
    try:
        import torch
    except Exception as e:                                   # noqa: BLE001
        res["error"] = f"אין torch: {e}"
        return res

    res["torch"] = torch.__version__
    if torch.cuda.is_available():
        dev, kind = torch.device("cuda"), "cuda"
    elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        dev, kind = torch.device("mps"), "mps"
    else:
        res["error"] = "אין התקן GPU שזמין ל-torch"
        res["mps_built"] = bool(getattr(torch.backends, "mps", None)
                                and torch.backends.mps.is_built())
        return res

    res.update(available=True, backend=kind)
    # מלכודת (07/10): על macos-14 (M1 וירטואלי, 7GB משותפים) מטריצה של
    # 2048 נפלה ב-"MPS backend out of memory" למרות שהתקרה 7.93GB. על
    # אפל הזיכרון משותף עם המערכת, ולכן ההקצאה בפועל קטנה בהרבה. 1024
    # עובר על שני הרנרים ועדיין רווי-חישוב (פי 2 מיליארד פעולות לסבב).
    n, iters = 1024, 60

    def run(device, sync) -> float:
        a = torch.randn(n, n, device=device)
        b = torch.randn(n, n, device=device)
        a @ b                                   # חימום: ההקצאה הראשונה יקרה
        sync()
        t0 = time.perf_counter()
        for _ in range(iters):
            c = a @ b
        sync()
        return time.perf_counter() - t0

    try:
        gsync = (torch.cuda.synchronize if kind == "cuda"
                 else torch.mps.synchronize)
        res["gpu_seconds"] = round(run(dev, gsync), 3)
        res["cpu_seconds"] = round(run(torch.device("cpu"), lambda: None), 3)
        flops = 2 * n ** 3 * iters
        res["gpu_gflops"] = round(flops / res["gpu_seconds"] / 1e9, 1)
        res["cpu_gflops"] = round(flops / res["cpu_seconds"] / 1e9, 1)
        res["speedup"] = round(res["cpu_seconds"] / res["gpu_seconds"], 2)
    except Exception as e:                                   # noqa: BLE001
        res["error"] = f"{type(e).__name__}: {e}"
        res["available"] = False
    return res


# ------------------------------- 3. הצוואר האמיתי: ראסטריזציה של WebGL

PAGE = r"""<!doctype html><html><body><div id="r">pending</div><script>
// מלכודת (07/10): --dump-dom של Chrome מדפיס אחרי load, ולכן כל המדידה
// חייבת להיות סינכרונית *לפני* ש-load נגמר. בלי זה הדף נדפס ריק.
(function () {
  var out = {};
  try {
    var c = document.createElement('canvas');
    c.width = 1280; c.height = 720;
    var gl = c.getContext('webgl2', {antialias: false, powerPreference: 'high-performance'})
          || c.getContext('webgl', {antialias: false});
    if (!gl) { out.error = 'no webgl context'; throw 0; }
    var di = gl.getExtension('WEBGL_debug_renderer_info');
    out.renderer = di ? gl.getParameter(di.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
    out.vendor   = di ? gl.getParameter(di.UNMASKED_VENDOR_WEBGL)   : gl.getParameter(gl.VENDOR);
    out.version  = gl.getParameter(gl.VERSION);

    var vs = 'attribute vec2 p;varying vec2 v;void main(){v=p;gl_Position=vec4(p,0.,1.);}';
    // שיידר כבד בכוונה: לופ שמכריח את ה-GPU לעבוד באמת, כמו מעבר של צל/תאורה.
    var fs = 'precision highp float;varying vec2 v;uniform float t;void main(){' +
             'vec3 s=vec3(0.);for(int i=0;i<220;i++){float f=float(i);' +
             's+=vec3(sin(v.x*f+t),cos(v.y*f-t),sin((v.x+v.y)*f));}' +
             'gl_FragColor=vec4(abs(s)/220.,1.);}';
    function mk(ty, src) { var s = gl.createShader(ty); gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw gl.getShaderInfoLog(s);
      return s; }
    var pr = gl.createProgram();
    gl.attachShader(pr, mk(gl.VERTEX_SHADER, vs));
    gl.attachShader(pr, mk(gl.FRAGMENT_SHADER, fs));
    gl.linkProgram(pr); gl.useProgram(pr);
    var buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 3,-1, -1,3]), gl.STATIC_DRAW);
    var loc = gl.getAttribLocation(pr, 'p');
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    var tl = gl.getUniformLocation(pr, 't');
    var px = new Uint8Array(4);

    gl.uniform1f(tl, 0.0); gl.drawArrays(gl.TRIANGLES, 0, 3);
    gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);   // חימום + סנכרון

    var FRAMES = 60, t0 = performance.now();
    for (var i = 0; i < FRAMES; i++) {
      gl.uniform1f(tl, i * 0.01);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    }
    // readPixels חוסם עד שה-GPU סיים. בלעדיו מודדים רק הגשת פקודות.
    gl.readPixels(0, 0, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px);
    var ms = performance.now() - t0;
    out.frames = FRAMES;
    out.seconds = +(ms / 1000).toFixed(3);
    out.fps = +(FRAMES / (ms / 1000)).toFixed(2);
  } catch (e) { if (!out.error) out.error = '' + e; }
  document.getElementById('r').textContent = 'WEBGLJSON' + JSON.stringify(out) + 'ENDJSON';
})();
</script></body></html>"""


def find_chrome() -> str | None:
    cands = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "google-chrome", "chromium-browser", "chromium", "microsoft-edge",
    ]
    for c in cands:
        if c.startswith("/"):
            if Path(c).exists():
                return c
        elif shutil.which(c):
            return shutil.which(c)
    return None


def webgl_bench(angle: str | None) -> dict:
    """angle=None -> חומרה (ברירת המחדל). angle='swiftshader' -> תוכנה, לבקרה."""
    chrome = find_chrome()
    if not chrome:
        return {"error": "לא נמצא Chrome/Chromium על הרנר"}
    page = HERE / "webgl.html"
    page.write_text(PAGE, encoding="utf-8")
    prof = HERE / f"prof_{angle or 'hw'}"
    # מלכודת (07/10): על macOS הריצה נתקעה ב-300 שניות ולא החזירה DOM.
    # הסיבה היא Keychain: Chrome מבקש גישה למחסן המפתחות של המשתמש, ועל
    # רנר בלי מושב גרפי הבקשה לא נענית לעולם. `--use-mock-keychain` פותר
    # את זה. הוא מזיק לאיש, ולכן הוא כאן בכל מערכת ולא רק באפל.
    args = [chrome, "--headless=new", "--dump-dom", "--no-sandbox",
            "--disable-dev-shm-usage", "--no-first-run",
            "--no-default-browser-check", "--use-mock-keychain",
            "--disable-sync", "--disable-background-networking",
            "--disable-extensions", "--mute-audio",
            f"--user-data-dir={prof}", "--enable-unsafe-swiftshader",
            page.as_uri()]
    if angle:
        args.insert(-1, f"--use-angle={angle}")
        args.insert(-1, "--use-gl=angle")
    t0 = time.perf_counter()
    dom = sh(args, timeout=300)
    took = round(time.perf_counter() - t0, 2)
    if "WEBGLJSON" not in dom:
        return {"error": "הדף לא החזיר תוצאה", "chrome": chrome,
                "wall": took, "tail": dom[-500:]}
    raw = dom.split("WEBGLJSON", 1)[1].split("ENDJSON", 1)[0]
    try:
        res = json.loads(raw)
    except Exception as e:                                   # noqa: BLE001
        return {"error": f"JSON פגום: {e}", "raw": raw[:300]}
    res["chrome"] = chrome
    res["mode"] = angle or "hardware-default"
    res["wall_seconds"] = took
    return res


# ------------------------------------------------------------------ main

def main() -> int:
    rep = {"machine": machine(), "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    rep["torch"] = torch_bench()
    rep["webgl_hw"] = webgl_bench(None)
    rep["webgl_sw"] = webgl_bench("swiftshader")
    hw, sw = rep["webgl_hw"], rep["webgl_sw"]
    if hw.get("fps") and sw.get("fps"):
        rep["webgl_hw_over_sw"] = round(hw["fps"] / sw["fps"], 2)
    dst = HERE / f"probe_{LABEL}.json"
    dst.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
