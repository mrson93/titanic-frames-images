#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from prune_history import SafetyError, build_plan


MANIFEST = [
    {"index": 0, "file": "frames/00002.jpg"},
    {"index": 1, "file": "frames/00003.jpg"},
    {"index": 2, "file": "frames/00004.jpg"},
]


class BuildPlanTests(unittest.TestCase):
    def test_removes_posted_and_unknown_frame_but_preserves_future(self):
        plan = build_plan(
            MANIFEST,
            {"next_index": 1},
            {"next_index": 2},
            frozenset(
                {
                    "frames/00001.jpg",
                    "frames/00002.jpg",
                    "frames/00003.jpg",
                    "frames/00004.jpg",
                }
            ),
        )
        self.assertEqual(
            plan.removable_frames,
            ("frames/00001.jpg", "frames/00002.jpg"),
        )
        self.assertEqual(
            plan.future_frames,
            frozenset({"frames/00003.jpg", "frames/00004.jpg"}),
        )

    def test_aborts_if_any_future_frame_is_missing(self):
        with self.assertRaisesRegex(SafetyError, "frames futuros estão ausentes"):
            build_plan(
                MANIFEST,
                {"next_index": 1},
                {"next_index": 2},
                frozenset({"frames/00002.jpg", "frames/00003.jpg"}),
            )

    def test_aborts_if_cutoff_is_ahead_of_current_state(self):
        with self.assertRaisesRegex(SafetyError, "índices fora de ordem"):
            build_plan(
                MANIFEST,
                {"next_index": 3},
                {"next_index": 2},
                frozenset(item["file"] for item in MANIFEST),
            )


if __name__ == "__main__":
    unittest.main()
