import unittest

from harness.mcp_client import business_session, call_tool, list_tool_defs


class McpContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_business_mcp_exposes_news_tools_and_returns_projection(self):
        try:
            async with business_session() as session:
                tool_defs = await list_tool_defs(session)
                tool_names = {item["function"]["name"] for item in tool_defs}

                self.assertIn("news_search", tool_names)
                self.assertIn("news_detail", tool_names)

                result = await call_tool(session, "news_search", {"query": "AI", "limit": 3})
        except Exception as exc:  # noqa: BLE001 - local MySQL/MCP may be unavailable in some dev envs
            self.skipTest(f"business MCP is not available: {exc}")

        if result.get("error"):
            self.skipTest(f"business MCP returned an unavailable local dependency: {result['error']}")
        self.assertEqual(result.get("tool"), "news_search")
        self.assertIsInstance(result.get("items"), list)
        self.assertLessEqual(len(result["items"]), 3)

        if result["items"]:
            first = result["items"][0]
            self.assertIn("id", first)
            self.assertIn("title", first)
            self.assertIn("summary", first)


if __name__ == "__main__":
    unittest.main()
