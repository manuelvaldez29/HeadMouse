"""Protocolo y análisis del estudio de cejas, con la cara sintética 3D."""
import random
import unittest
import brow_study as bs
import face_geometry as fg
from test_face_geometry import W, H, landmarks

POSES = {"NEUTRAL": {}, "LOOK_UP": {"pitch": 25}, "LOOK_DOWN": {"pitch": -12},
         "LOOK_LEFT": {"yaw": 20}, "LOOK_RIGHT": {"yaw": -20}, "BOTH_RAISE": {},
         "LEFT_RAISE": {}, "RIGHT_RAISE": {}, "UP_AND_RAISE": {"pitch": 15}}


def synthetic_records(seed=3):
    rng = random.Random(seed)
    records = []
    for start, end, round_index, label, _, phase in bs.schedule():
        for k in range(int((end - start) * 20)):
            pose = {key: value + rng.uniform(-2, 2) for key, value in POSES[label].items()}
            # Elevación cómoda variable entre frames, como en una persona real.
            raising = label in ("BOTH_RAISE", "LEFT_RAISE", "RIGHT_RAISE", "UP_AND_RAISE")
            lms = landmarks(raise_mm=rng.uniform(3, 6) if raising else rng.uniform(-.4, .4), **pose)
            left2d, right2d = fg.brow_lift_2d(lms)
            left3d, right3d = fg.brow_lift_3d(lms, W, H)
            records.append(dict(t=start + k / 20, round=round_index, label=label, phase=phase,
                                nose_x=.5, nose_y=.5, head_pitch=fg.head_pose(lms, W, H)[0],
                                head_yaw=0, head_roll=0, brow_left_lift=left2d, brow_right_lift=right2d,
                                brow_left_3d=left3d, brow_right_3d=right3d, blendshapes={}))
    return records


class BrowStudyTests(unittest.TestCase):
    def test_schedule_alternates_transition_and_hold(self):
        timeline = bs.schedule()
        self.assertEqual(len(timeline), 2 * len(bs.SEGMENTS) * bs.ROUNDS)
        self.assertEqual([row[5] for row in timeline[:2]], ["transition", "hold"])
        total = timeline[-1][1]
        self.assertLess(total, 150)
        self.assertEqual(bs.segment_at(timeline, 2.5)[3:6:2], ("NEUTRAL", "hold"))
        self.assertIsNone(bs.segment_at(timeline, total + 1))

    def test_analysis_prefers_pose_invariant_signal(self):
        results = bs.analyze(synthetic_records())
        rows = {(r["source"], r["side"]): r for r in results}
        geo, g3d = rows["GEOMETRIC", "left"], rows["GEOMETRIC_3D", "left"]
        self.assertGreater(g3d["auc_look_up"], .99)
        self.assertLess(g3d["false_up"], .05)
        self.assertLess(abs(g3d["look_up_shift"]), .1)
        self.assertGreater(geo["false_up"], .5)          # mirar arriba imita levantar cejas
        self.assertGreater(geo["look_up_shift"], .3)
        self.assertGreater(geo["pitch_per_10deg"], .2)
        self.assertTrue(rows["BLENDSHAPE", "left"]["missing"])
        self.assertEqual(bs.ranking(results)[0], "GEOMETRIC_3D")
        self.assertNotIn("BLENDSHAPE", bs.ranking(results))

    def test_posture_table_and_laterality_check(self):
        records = synthetic_records()
        rows = {row["label"]: row for row in bs.posture_table(records)}
        self.assertAlmostEqual(rows["LOOK_UP"]["pitch"], 25, delta=2)
        self.assertGreater(rows["LOOK_UP"]["GEOMETRIC", "left"], .5)
        self.assertLess(abs(rows["LOOK_UP"]["GEOMETRIC_3D", "left"]), .1)
        self.assertEqual(bs.laterality(records), [])
        # Cejas unilaterales sintéticas con los canales cruzados, como el bug de blendshapes espejados.
        for r in records:
            if r["label"] == "LEFT_RAISE":
                r["brow_left_3d"], r["brow_right_3d"] = 0, r["brow_left_3d"]
            if r["label"] == "RIGHT_RAISE":
                r["brow_left_3d"], r["brow_right_3d"] = r["brow_right_3d"], 0
        self.assertEqual(bs.laterality(records), ["GEOMETRIC_3D"])

    def test_report_and_round_trip_without_images(self):
        import tempfile, json
        from pathlib import Path
        records = synthetic_records()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "brow_study_test.jsonl"
            path.write_text("\n".join(json.dumps(r) for r in [{"experiment": "brow_study"}] + records),
                            encoding="utf-8")
            meta, loaded = bs.load(path)
            self.assertEqual(meta["experiment"], "brow_study")
            self.assertEqual(len(loaded), len(records))
            text = bs.report(bs.analyze(loaded), Path(directory) / "r.md", records=loaded)
            self.assertIn("Respuesta por postura", text)
            self.assertIn("GEOMETRIC_3D", text)
            self.assertTrue((Path(directory) / "r.md").exists())
        for name in ("frame", "image", "landmarks"):
            self.assertNotIn(name, records[0])


if __name__ == "__main__": unittest.main()
