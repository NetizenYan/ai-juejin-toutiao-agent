import unittest

from harness.mcp_client import list_tool_defs
from harness import web_mcp_client
from harness.web_mcp_client import web_session


class WebMcpContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_web_mcp_exposes_guarded_web_tools(self):
        async with web_session() as session:
            defs = await list_tool_defs(session)

        names = {item["function"]["name"] for item in defs}
        self.assertIn("web_fetch", names)
        self.assertIn("web_capture_ocr", names)
        self.assertNotIn("sql_query", names)

    def test_web_mcp_python_runtime_can_be_configured(self):
        original = web_mcp_client.os.environ.get("WEB_MCP_PYTHON")
        web_mcp_client.os.environ["WEB_MCP_PYTHON"] = "D:/runtime/python.exe"
        try:
            params = web_mcp_client._server_params()
        finally:
            if original is None:
                web_mcp_client.os.environ.pop("WEB_MCP_PYTHON", None)
            else:
                web_mcp_client.os.environ["WEB_MCP_PYTHON"] = original

        self.assertEqual(params.command, "D:/runtime/python.exe")


if __name__ == "__main__":
    unittest.main()
