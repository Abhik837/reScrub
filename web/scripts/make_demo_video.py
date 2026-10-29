"""Generate the synthetic demonstration clip used by reScrub's demo mode.

This draws simple labelled shapes (no real footage) so the demo findings in
lib/demo.ts line up with moments that actually happen on screen.

Run from the web/ folder:
    pip install opencv-python numpy
    python scripts/make_demo_video.py

Output: public/demo/demo-procedure.webm (VP8, plays in all modern browsers).
If you change the timings here, update lib/demo.ts to match.
"""

from pathlib import Path

import cv2
import numpy as np

W, H, FPS, SECONDS = 960, 540, 15, 60
OUT = Path(__file__).resolve().parent.parent / "public" / "demo" / "demo-procedure.webm"

# Colors are BGR.
BG = (34, 36, 33)
FIELD = (88, 120, 70)        # sterile drape (green)
TRAY = (120, 130, 110)
NONSTERILE = (60, 90, 150)   # designated nonsterile side table (brown/orange)
MASK_ZONE = (95, 95, 95)
TEXT = (230, 232, 228)
DIM = (150, 155, 150)
GLOVE_R = (230, 200, 120)    # right glove (light blue)
GLOVE_L = (200, 220, 235)    # left glove
INSTRUMENT = (210, 210, 210)
OCCLUDER = (70, 70, 72)

FONT = cv2.FONT_HERSHEY_SIMPLEX

# Fixed scene regions: (x1, y1, x2, y2)
DRAPE = (300, 150, 700, 420)
TRAY_BOX = (720, 170, 900, 300)
SIDE_TABLE = (40, 330, 230, 470)
MASK = (380, 40, 600, 110)
WAIST_Y = 445  # line representing the table edge / waist level


def lerp(a, b, t):
    return a + (b - a) * t


def path(keyframes, t):
    """Piecewise-linear position from [(time, (x, y)), ...]."""
    if t <= keyframes[0][0]:
        return keyframes[0][1]
    for (t0, p0), (t1, p1) in zip(keyframes, keyframes[1:]):
        if t0 <= t <= t1:
            k = 0 if t1 == t0 else (t - t0) / (t1 - t0)
            # ease in/out so motion looks less mechanical
            k = k * k * (3 - 2 * k)
            return (int(lerp(p0[0], p1[0], k)), int(lerp(p0[1], p1[1], k)))
    return keyframes[-1][1]


# Right glove: rests on drape, touches side table at ~11s, then the instrument at ~15.5s,
# then drifts up near (but possibly not touching) the mask zone around 24s.
RIGHT = [
    (0, (520, 300)), (8, (520, 300)), (11, (150, 380)), (12, (150, 380)),
    (15.5, (790, 235)), (17, (790, 235)), (19, (560, 280)),
    (22, (520, 140)), (24, (505, 122)), (26, (520, 150)), (28, (540, 290)),
    (42, (540, 290)), (43, (800, 240)), (44, (820, 250)),
    (46.5, (960, 260)), (48, (800, 240)), (50, (560, 290)), (60, (560, 290)),
]

# Left glove: drops below the waist line at ~33s, then touches the drape at ~36s.
LEFT = [
    (0, (400, 320)), (30, (400, 320)), (33, (330, 480)), (34, (330, 480)),
    (36, (420, 330)), (60, (420, 330)),
]

# Instrument: sits on the tray, is carried out of view behind an occluder 43-48s.
INSTR = [
    (0, (800, 240)), (43, (800, 240)), (44, (820, 250)),
    (46.5, (960, 260)), (48, (800, 240)), (60, (800, 240)),
]


def label(img, text, org, color=TEXT, scale=0.5, thick=1):
    cv2.putText(img, text, org, FONT, scale, color, thick, cv2.LINE_AA)


def draw_frame(t):
    img = np.full((H, W, 3), BG, np.uint8)

    cv2.rectangle(img, DRAPE[:2], DRAPE[2:], FIELD, -1)
    label(img, "STERILE DRAPE", (DRAPE[0] + 10, DRAPE[1] + 24))

    cv2.rectangle(img, TRAY_BOX[:2], TRAY_BOX[2:], TRAY, -1)
    label(img, "INSTRUMENT TRAY", (TRAY_BOX[0] + 8, TRAY_BOX[1] + 22), scale=0.45)

    cv2.rectangle(img, SIDE_TABLE[:2], SIDE_TABLE[2:], NONSTERILE, -1)
    label(img, "NONSTERILE", (SIDE_TABLE[0] + 10, SIDE_TABLE[1] + 24), scale=0.45)
    label(img, "SIDE TABLE", (SIDE_TABLE[0] + 10, SIDE_TABLE[1] + 44), scale=0.45)

    cv2.rectangle(img, MASK[:2], MASK[2:], MASK_ZONE, -1)
    label(img, "FACE / MASK ZONE", (MASK[0] + 10, MASK[1] + 42), scale=0.5)

    cv2.line(img, (0, WAIST_Y), (W, WAIST_Y), DIM, 1, cv2.LINE_AA)
    label(img, "TABLE EDGE / WAIST LEVEL", (720, WAIST_Y - 8), DIM, 0.4)

    ix, iy = path(INSTR, t)
    cv2.rectangle(img, (ix - 28, iy - 5), (ix + 28, iy + 5), INSTRUMENT, -1)
    label(img, "FORCEPS", (ix - 28, iy + 22), DIM, 0.4)

    for pos, color, name in ((path(LEFT, t), GLOVE_L, "L"), (path(RIGHT, t), GLOVE_R, "R")):
        cv2.circle(img, pos, 22, color, -1, cv2.LINE_AA)
        label(img, name, (pos[0] - 6, pos[1] + 6), (30, 30, 30), 0.6, 2)

    # A teammate's arm passes in front of the camera from 43s to 48s.
    if 43 <= t <= 48:
        cv2.rectangle(img, (690, 150), (960, 340), OCCLUDER, -1)
        label(img, "VIEW BLOCKED", (760, 250), DIM, 0.5)

    cv2.rectangle(img, (0, H - 34), (W, H), (20, 20, 20), -1)
    label(img, "SYNTHETIC DEMONSTRATION CLIP - not real footage", (14, H - 12), DIM, 0.5)
    mm, ss = divmod(t, 60)
    label(img, f"{int(mm):02d}:{ss:05.2f}", (W - 110, H - 12), TEXT, 0.5)
    return img


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(OUT), cv2.VideoWriter_fourcc(*"VP80"), FPS, (W, H))
    if not writer.isOpened():
        raise SystemExit("OpenCV could not open a VP8 writer on this machine.")
    for i in range(FPS * SECONDS):
        writer.write(draw_frame(i / FPS))
    writer.release()
    print(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
