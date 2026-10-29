"""Soundtrack for the social edit, synthesised from the cue list that viral.py writes (no third-party audio).

python sound.py <cues.json> <out.wav>

drone   low tension bed that grows towards the impact     tick   clock tick every second
rumble  the AVE at speed, rising                          wind   empty field after the impact
cut     short whoosh on a change of screen                hit    low hit on the hook card
boom    the impact: blast, low drop and metal
"""
import json
import sys
import wave

import numpy as np

SR = 48000
cues_path, out_path = sys.argv[1:3]
spec = json.load(open(cues_path))
n = int((spec["duration"] + 1.0) * SR)
t = np.arange(n) / SR
rng = np.random.default_rng(7)
mix = np.zeros(n)


def lowpass(x, fc):
    f = np.fft.rfftfreq(len(x), 1 / SR)
    return np.fft.irfft(np.fft.rfft(x) / (1 + (f / fc) ** 4), len(x))


def bandpass(x, lo, hi):
    return lowpass(x, hi) - lowpass(x, lo)


def window(t0, t1, fade=0.4):
    a, b = int(t0 * SR), min(n, int(t1 * SR))
    w = np.zeros(n)
    if b <= a:
        return w
    k = np.arange(b - a) / SR
    w[a:b] = np.minimum(1.0, np.minimum(k / fade, (t1 - t0 - k) / fade))
    return np.clip(w, 0, 1)


def place(sig, at, gain):
    a = int(at * SR)
    if a < 0:
        sig, a = sig[-a:], 0
    if a >= n:
        return
    m = min(len(sig), n - a)
    mix[a:a + m] += gain * sig[:m]


noise = rng.standard_normal(n)
low_noise = lowpass(noise, 180)
low_noise /= np.abs(low_noise).max()
wind = bandpass(rng.standard_normal(n), 200, 900)
wind /= np.abs(wind).max()
brown = lowpass(rng.standard_normal(n), 90)
brown /= np.abs(brown).max()
impact = min([c["t"] for c in spec["cues"] if c["type"] == "boom"] or [spec["duration"]])
# beds that run over back-to-back screens play as one, without a dip at every cut
cues = []
for c in sorted(spec["cues"], key=lambda c: (c["type"], c.get("t0", c.get("t", 0)))):
    p = cues[-1] if cues else None
    if "t0" in c and p and p["type"] == c["type"] and c["t0"] - p["t1"] < 0.05:
        p["t1"] = c["t1"]
    else:
        cues.append(dict(c))

for c in cues:
    kind = c["type"]
    if kind == "drone":
        w = window(c["t0"], c["t1"], 0.8)
        grow = 0.55 + 0.45 * np.clip(t / max(impact, 1.0), 0, 1)
        bed = (np.sin(2 * np.pi * 55 * t) + 0.6 * np.sin(2 * np.pi * 82.4 * t + 0.3 * np.sin(2 * np.pi * 0.07 * t))
               + 0.35 * np.sin(2 * np.pi * 110.6 * t))
        mix += w * grow * (0.10 * bed + 0.08 * low_noise)
    elif kind == "tick":
        click = np.sin(2 * np.pi * 1700 * np.arange(int(0.03 * SR)) / SR) * np.exp(-np.arange(int(0.03 * SR)) / (0.006 * SR))
        s = c["t0"] + 0.2
        while s < c["t1"] - 0.2:
            place(click, s, 0.22)
            s += 1.0
    elif kind == "rumble":
        w = window(c["t0"], c["t1"], 0.3)
        ramp = np.clip((t - c["t0"]) / max(c["t1"] - c["t0"], 0.1), 0, 1)
        mix += w * (0.2 + 0.7 * ramp ** 1.5) * (0.8 * brown + 0.25 * np.sin(2 * np.pi * 46 * t))
    elif kind == "wind":
        w = window(c["t0"], c["t1"], 1.5)
        mix += w * 0.14 * wind * (0.7 + 0.3 * np.sin(2 * np.pi * 0.11 * t))
    elif kind == "cut":
        k = np.arange(int(0.35 * SR)) / SR
        whoosh = bandpass(rng.standard_normal(len(k)), 400, 3000) * np.sin(np.pi * k / k[-1]) ** 2
        place(whoosh / (np.abs(whoosh).max() + 1e-9), c["t"] - 0.15, 0.10)
    elif kind == "hit":
        k = np.arange(int(1.6 * SR)) / SR
        hit = np.sin(2 * np.pi * (60 - 20 * k) * k) * np.exp(-k / 0.45)
        place(hit, c["t"], 0.7)
    elif kind == "boom":
        k = np.arange(int(3.5 * SR)) / SR
        blast = lowpass(rng.standard_normal(len(k)), 900) * np.exp(-k / 0.55)
        blast /= np.abs(blast).max()
        drop = np.sin(2 * np.pi * (48 - 18 * k / k[-1]) * k) * np.exp(-k / 1.1)
        metal = sum(np.sin(2 * np.pi * fq * k) for fq in (1240, 1873, 2651, 3307)) / 4 * np.exp(-k / 0.9)
        place(0.9 * blast + 0.8 * drop + 0.25 * metal, c["t"], 1.0)

mix = np.tanh(1.2 * mix)
mix *= 0.89 / max(np.abs(mix).max(), 1e-9)
pcm = (np.repeat(mix[:, None], 2, axis=1) * 32767).astype("<i2")
with wave.open(out_path, "wb") as wf:
    wf.setnchannels(2)
    wf.setsampwidth(2)
    wf.setframerate(SR)
    wf.writeframes(pcm.tobytes())
print("OK", out_path, f"{n / SR:.1f} s", flush=True)
