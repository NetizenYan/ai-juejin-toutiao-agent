import unittest

from scripts import ab_compare


class AbCompareTests(unittest.TestCase):
    def test_compare_metric_sets_marks_ready_when_v2_meets_thresholds_and_baseline(self):
        v1 = {
            "RouteAccuracy": 0.94,
            "Recall@5": 0.65,
            "EvidenceRecall@5": 0.55,
            "LatencyP95": 1100,
        }
        v2 = {
            "RouteAccuracy": 0.96,
            "Recall@5": 0.70,
            "EvidenceRecall@5": 0.58,
            "LatencyP95": 900,
        }

        result = ab_compare.compare_metric_sets(v1, v2)

        self.assertTrue(result["ready_for_gray"])
        self.assertEqual(result["failed_gates"], [])

    def test_compare_metric_sets_blocks_latency_regression(self):
        v1 = {
            "RouteAccuracy": 0.94,
            "Recall@5": 0.65,
            "EvidenceRecall@5": 0.55,
            "LatencyP95": 1000,
        }
        v2 = {
            "RouteAccuracy": 0.96,
            "Recall@5": 0.70,
            "EvidenceRecall@5": 0.58,
            "LatencyP95": 1400,
        }

        result = ab_compare.compare_metric_sets(v1, v2)

        self.assertFalse(result["ready_for_gray"])
        self.assertIn("LatencyP95", result["failed_gates"])


if __name__ == "__main__":
    unittest.main()
