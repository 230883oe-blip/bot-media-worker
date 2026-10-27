import json, os, shutil
from pathlib import Path
from gradio_client import Client, handle_file
os.environ.pop("HF_TOKEN", None)
S = int(os.environ["SHARD"]); i = S + 1; out = Path("artifacts"); out.mkdir(exist_ok=True)
c = Client("Plachta/Seed-VC", verbose=False)
r = c.predict(source_audio_path=handle_file(f"vc/src{i}.wav"), target_audio_path=handle_file("vc/child_ref.wav"), diffusion_steps=50, length_adjust=1.0,
              inference_cfg_rate=0.3, f0_condition=False, auto_f0_adjust=True, pitch_shift=0, api_name="/predict_1")
shutil.copy(r[1], out / f"line{i}.wav"); print("ok", i)
