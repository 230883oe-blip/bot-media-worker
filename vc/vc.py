import json, os, shutil, time
from pathlib import Path
from gradio_client import Client, handle_file
os.environ.pop("HF_TOKEN", None)
out = Path("artifacts"); out.mkdir(exist_ok=True); log = []
c = Client("Plachta/Seed-VC", verbose=False)
for i in range(4):
    for variant, kw in [("f0", dict(f0_condition=True, auto_f0_adjust=True, pitch_shift=0)), ("f0up", dict(f0_condition=True, auto_f0_adjust=False, pitch_shift=4))]:
        for attempt in range(3):
            try:
                r = c.predict(source_audio_path=handle_file(f"vc/src{i}.wav"), target_audio_path=handle_file("vc/child_ref.wav"),
                              diffusion_steps=25, length_adjust=1.0, inference_cfg_rate=0.7, api_name="/predict_1", **kw)
                p = r[1] if isinstance(r, (list, tuple)) else r
                shutil.copy(p, out / f"vc{i}_{variant}.wav"); log.append({"i": i, "v": variant, "ok": True}); break
            except Exception as e:
                log.append({"i": i, "v": variant, "err": f"{type(e).__name__}: {str(e)[:150]}"}); time.sleep(20)
(out / "log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8"); print(log)
