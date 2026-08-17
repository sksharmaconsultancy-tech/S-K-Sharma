"""Iter 602 — Anti-spoofing / presentation-attack heuristics (Phase 2).

If a dedicated ONNX PAD model exists at backend/models/antispoof.onnx it is
used; otherwise robust server-side heuristics run on every frame:
  * Moire / screen re-capture — abnormal high-frequency FFT energy.
  * Flatness — printed photos show low colour-saturation variance.
  * Cross-frame motion — challenge frames must genuinely differ.
Returns a score 0..1 (higher = more likely LIVE) + verdict.
"""
import os
from typing import Dict, List

import cv2
import numpy as np

_MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "models", "antispoof.onnx")
_session = None


def _model():
    global _session
    if _session is None and os.path.exists(_MODEL_PATH):
        import onnxruntime as ort
        _session = ort.InferenceSession(_MODEL_PATH, providers=["CPUExecutionProvider"])
    return _session


def _moire_score(gray: np.ndarray) -> float:
    """High-frequency ring energy ratio — screens/prints show peaks."""
    g = cv2.resize(gray, (256, 256)).astype(np.float32)
    f = np.fft.fftshift(np.abs(np.fft.fft2(g)))
    f = np.log1p(f)
    c = 128
    yy, xx = np.ogrid[:256, :256]
    r = np.sqrt((yy - c) ** 2 + (xx - c) ** 2)
    hi = f[(r > 70) & (r < 120)].mean()
    lo = f[(r < 30)].mean()
    return float(hi / (lo + 1e-6))  # typical live ≈ 0.25-0.45; screens higher


def _flatness(img: np.ndarray) -> float:
    hsv = cv2.cvtColor(cv2.resize(img, (256, 256)), cv2.COLOR_BGR2HSV)
    return float(hsv[:, :, 1].std())  # printed/greyish photos → low


def frame_spoof_check(img: np.ndarray, face_bbox) -> Dict[str, float]:
    x1, y1, x2, y2 = [int(v) for v in face_bbox]
    h, w = img.shape[:2]
    pad = int((x2 - x1) * 0.4)
    crop = img[max(0, y1 - pad):min(h, y2 + pad), max(0, x1 - pad):min(w, x2 + pad)]
    if crop.size == 0:
        crop = img
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    sess = _model()
    if sess is not None:
        inp = cv2.resize(crop, (80, 80)).astype(np.float32).transpose(2, 0, 1)[None]
        out = sess.run(None, {sess.get_inputs()[0].name: inp})[0][0]
        e = np.exp(out - out.max()); p = e / e.sum()
        live = float(p[1]) if len(p) >= 2 else float(p[0])
        return {"live_score": live, "method": 1.0}
    moire = _moire_score(gray)
    flat = _flatness(crop)
    score = 1.0
    if moire > 0.62:            # strong high-frequency pattern → screen
        score -= min(0.6, (moire - 0.62) * 2.0)
    if flat < 18.0:             # very flat colour → print / grey photo
        score -= min(0.4, (18.0 - flat) / 30.0)
    return {"live_score": max(0.0, score), "moire": moire, "flatness": flat,
            "method": 0.0}


def motion_check(grays: List[np.ndarray]) -> float:
    """Mean absolute difference between consecutive challenge frames —
    a statically replayed image shows ~0 motion."""
    if len(grays) < 2:
        return 0.0
    diffs = []
    for a, b in zip(grays, grays[1:]):
        aa = cv2.resize(a, (160, 160)).astype(np.float32)
        bb = cv2.resize(b, (160, 160)).astype(np.float32)
        diffs.append(float(np.abs(aa - bb).mean()))
    return float(np.mean(diffs))
