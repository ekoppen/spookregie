import os
import random

# Alleen .wav: main.py speelt af met `aplay`, dat geen mp3 kan decoderen.
_AUDIO_EXTENSIONS = (".wav",)


def pick_audio_file(media_dir, rng=random, enabled=None):
    files = [f for f in os.listdir(media_dir) if f.lower().endswith(_AUDIO_EXTENSIONS)]
    if enabled is not None:
        files = [f for f in files if f in enabled]
    if not files:
        raise FileNotFoundError(f"Geen (ingeschakelde) audiobestanden gevonden in {media_dir}")
    return os.path.join(media_dir, rng.choice(files))
