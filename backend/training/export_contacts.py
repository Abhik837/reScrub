"""MM-OR scene-graph relations -> labeled contact events (JSON lines).

Each relation like ("circulator", "touching", "instrument_table") becomes one
row with both sides' sterility. Rows where an unscrubbed person contacts a
sterile object (or a scrubbed person contacts a nonsterile one) are marked
`breach_candidate` — ground truth for training and checking the contamination
model against reScrub's proximity features.

    python -m training.export_contacts --mmor /data/MM-OR_data --out /data/rescrub_contacts.jsonl
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from .mmor import MMOR_SPLITS, MMOR_TAKE_TO_FOLDER, ClassMap, load_relation_frames, normalize_entity, resolve_root


def classify(sub_d: str, obj_d: str) -> bool:
    """Contact that breaks asepsis (same rules as rescrub/analysis/breaches.py and MM-OR's labels)."""
    if sub_d == "nonsterile":
        return obj_d in ("sterile", "patient")
    if sub_d == "sterile":
        return obj_d == "nonsterile"
    return False


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mmor", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    classes = ClassMap.load()
    entities = classes.relation_entities
    split_of = {t: s for s, takes in MMOR_SPLITS.items() for t in takes}
    stats: Counter = Counter()
    with open(args.out, "w") as out:
        for take, split in split_of.items():
            take_dir = resolve_root(args.mmor) / MMOR_TAKE_TO_FOLDER.get(take, take)
            for frame_idx, rels, ids in load_relation_frames(take_dir, take):
                for sub, pred, obj in rels:
                    sub, obj = normalize_entity(sub), normalize_entity(obj)
                    pred = pred[0].lower() + pred[1:]
                    if pred == "operating":
                        pred = "manipulating"
                    is_contact = pred in classes.contact_predicates
                    sub_d, obj_d = entities.get(sub, "unknown"), entities.get(obj, "unknown")
                    breach = is_contact and classify(sub_d, obj_d)
                    out.write(json.dumps({
                        "take": take, "split": split, "frame": frame_idx,
                        "azure_image_id": ids.get("azure"), "simstation_image_id": ids.get("simstation"),
                        "subject": sub, "predicate": pred, "object": obj,
                        "subject_designation": sub_d, "object_designation": obj_d,
                        "contact": is_contact, "breach_candidate": breach,
                    }) + "\n")
                    stats["relations"] += 1
                    stats["contacts"] += is_contact
                    stats["breach_candidates"] += breach
                    if breach:
                        stats[f"breach:{sub} {pred} {obj}"] += 1
    print(json.dumps(dict(stats.most_common()), indent=2))


if __name__ == "__main__":
    main()
