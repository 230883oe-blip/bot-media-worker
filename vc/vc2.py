import json, os, shutil, time
from pathlib import Path
from gradio_client import Client, handle_file
os.environ.pop("HF_TOKEN", None)
S = int(os.environ["SHARD"]); out = Path("artifacts"); out.mkdir(exist_ok=True); log = []
SV = {1: dict(inference_cfg_rate=0.3, f0_condition=False), 2: dict(inference_cfg_rate=0.0, f0_condition=False), 3: dict(inference_cfg_rate=0.7, f0_condition=True)}
for i in (0, 1):
    try:
        if S in SV:
            c = Client("Plachta/Seed-VC", verbose=False)
            r = c.predict(source_audio_path=handle_file(f"vc/src{i}.wav"), target_audio_path=handle_file("vc/child_ref.wav"), diffusion_steps=50,
                          length_adjust=1.0, auto_f0_adjust=True, pitch_shift=0, api_name="/predict_1", **SV[S]) if False else \
                c.predict(source_audio_path=handle_file(f"vc/src{i}.wav"), target_audio_path=handle_file("vc/child_ref.wav"), diffusion_steps=50,
                          length_adjust=1.0, auto_f0_adjust=True, pitch_shift=0, api_name="/predict_1", **SV[S])
            p = r[1]
        else:
            c = Client("hugging-apps/meanvc2-voice-conversion", verbose=False)
            p = c.predict(source_audio=handle_file(f"vc/src{i}.wav"), reference_audio=handle_file("vc/child_ref.wav"),
                          model_variant="120 ms chunk + 40 ms lookahead (best quality)", steps=3 if S == 4 else 8, seed=0, api_name="/convert")
        shutil.copy(p, out / f"s{S}_line{i}.wav"); log.append({"s": S, "i": i, "ok": True})
    except Exception as e:
        log.append({"s": S, "i": i, "err": f"{type(e).__name__}: {str(e)[:150]}"})
(out / f"log{S}.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8"); print(log)
