import unittest

from routers import ai as ai_router


class AiRouterMetadataTests(unittest.TestCase):
    def test_assistant_evidence_pack_preserves_b_v3_metadata(self):
        validation = {
            "metadata": {"route": "econ_finance_query"},
            "context": {"anchor_ledger": [{"anchor_id": "news:jjrb:anchor"}]},
            "anchor_resolution": {"state": "ANCHOR_CONFIRMED"},
            "confirmed_anchor": {
                "anchor_id": "news:jjrb:anchor",
                "source_credibility": "high",
            },
            "agent_orchestration": {
                "next_action": "generate_answer",
                "roles": [{"role": "AnswerPlanner", "action": "generate_answer"}],
            },
        }

        pack = ai_router._build_assistant_evidence_pack(["news:jjrb:anchor"], validation)

        self.assertEqual(pack["refs"], ["news:jjrb:anchor"])
        self.assertEqual(pack["validation"]["route"], "econ_finance_query")
        self.assertEqual(pack["context"]["anchor_ledger"][0]["anchor_id"], "news:jjrb:anchor")
        self.assertEqual(pack["anchor_resolution"]["state"], "ANCHOR_CONFIRMED")
        self.assertEqual(pack["confirmed_anchor"]["anchor_id"], "news:jjrb:anchor")
        self.assertEqual(pack["agent_orchestration"]["next_action"], "generate_answer")

    def test_done_payload_exposes_b_v3_metadata_for_eval(self):
        validation = {
            "summary": {"passed": True},
            "anchor_resolution": {"state": "WAITING_USER_CONFIRMATION"},
            "confirmed_anchor": {"anchor_id": "news:jjrb:anchor"},
            "agent_orchestration": {
                "next_action": "ask_user_to_confirm_anchor",
                "roles": [{"role": "AnswerPlanner", "action": "ask_user_to_confirm_anchor"}],
            },
        }

        payload = ai_router._build_done_payload(7, ["news:jjrb:anchor"], validation)

        self.assertEqual(payload["sessionId"], 7)
        self.assertEqual(payload["anchorResolution"]["state"], "WAITING_USER_CONFIRMATION")
        self.assertEqual(payload["confirmedAnchor"]["anchor_id"], "news:jjrb:anchor")
        self.assertEqual(payload["agentOrchestration"]["next_action"], "ask_user_to_confirm_anchor")


if __name__ == "__main__":
    unittest.main()
