# Demo videos

| File | What it is | Used by |
| --- | --- | --- |
| `mmor-038-demo.mp4` | 3 minutes of MM-OR test surgery 038 (simulated robot-assisted knee replacement), angled ceiling camera `simstation0`, 1 frame per second, 1280×720 H.264 | **Analyze demo video**: uploaded to your backend and analyzed like any recording |
| `demo-procedure.webm` | A synthetic clip drawn with labeled shapes (`scripts/make_demo_video.py`) | **View demonstration**: a ready-made review that needs no backend |

Of the three cameras tried for the MM-OR clip, `simstation0` gave the most stable "Person N" labels, showed
sterile, non-sterile and patient areas, and was the only one with a scrubbed-hand finding. Surgery 038 was
never used for training or for choosing models.

## MM-OR terms of use

`mmor-038-demo.mp4` comes from [MM-OR](https://github.com/egeozsoy/MM-OR) (TU Munich), and MM-OR's terms
of use apply to it. **By using this clip you agree to follow MM-OR's terms:**
- read them via the access form linked in the [MM-OR README](https://github.com/egeozsoy/MM-OR#mm-or-dataset);
- use the clip only as those terms allow (for example, research and education);
- cite MM-OR:

> Özsoy et al., *MM-OR: A Large Multimodal Operating Room Dataset for Semantic Understanding of
> High-Intensity Surgical Environments*, CVPR 2025.

If you can't accept those terms, delete `mmor-038-demo.mp4`; the **Analyze demo video** button then
reports that the demo video could not be loaded, and everything else works.
