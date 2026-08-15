import os
import random

_AUDIO_EXTENSIONS = (".wav", ".mp3")


def pick_audio_file(media_dir, rng=random):
    files = [f for f in os.listdir(media_dir) if f.lower().endswith(_AUDIO_EXTENSIONS)]
    if not files:
        raise FileNotFoundError(f"Geen audiobestanden gevonden in {media_dir}")
    return os.path.join(media_dir, rng.choice(files))
