import asyncio
import os
import sys
import time
import unittest
from dataclasses import replace
from unittest import mock

from mcp import StdioServerParameters

from agent.harness import mcp_pool
from agent.harness.mcp_client import call_tool

SERVER = os.path.join(os.path.dirname(__file__), "fixtures", "echo_mcp_server.py")


def _params() -> StdioServerParameters:
    return StdioServerParameters(command=sys.executable, args=[SERVER], env=os.environ.copy())


async def _pid(name: str = "echo") -> int:
    async with mcp_pool.mcp_session(name, _params) as session:
        return (await call_tool(session, "whoami", {}))["pid"]


class ResidentSessionTests(unittest.TestCase):
    def test_requests_share_one_server_process(self):
        async def run():
            try:
                first = await _pid()
                second = await _pid()
                start = time.perf_counter()
                # Concurrent calls multiplex over the one session instead of queueing behind each other.
                async with mcp_pool.mcp_session("echo", _params) as session:
                    results = await asyncio.gather(*(call_tool(session, "sleep", {"seconds": 0.5}) for _ in range(3)))
                return first, second, {r["pid"] for r in results}, time.perf_counter() - start
            finally:
                await mcp_pool.close_all()

        first, second, pids, elapsed = asyncio.run(run())
        self.assertEqual(first, second)
        self.assertEqual(pids, {first})
        self.assertLess(elapsed, 1.4)

    def test_a_dead_server_is_restarted_on_the_next_request(self):
        async def run():
            try:
                first = await _pid()
                async with mcp_pool.mcp_session("echo", _params) as session:
                    with self.assertRaises(mcp_pool.TRANSPORT_ERRORS):
                        await asyncio.wait_for(call_tool(session, "die", {}), timeout=10)
                return first, await _pid(), mcp_pool.resident("echo", _params).starts
            finally:
                await mcp_pool.close_all()

        first, second, starts = asyncio.run(run())
        self.assertNotEqual(first, second)
        self.assertEqual(starts, 2)

    def test_a_timed_out_call_does_not_tear_down_the_session(self):
        async def run():
            try:
                async with mcp_pool.mcp_session("echo", _params) as session:
                    with self.assertRaises(asyncio.TimeoutError):
                        await asyncio.wait_for(call_tool(session, "sleep", {"seconds": 5}), timeout=0.3)
                    after = await call_tool(session, "whoami", {})
                return after["pid"], mcp_pool.resident("echo", _params).starts
            finally:
                await mcp_pool.close_all()

        pid, starts = asyncio.run(run())
        self.assertTrue(pid)
        self.assertEqual(starts, 1)

    def test_resident_mode_off_starts_a_process_per_request(self):
        async def run():
            return await _pid(), await _pid()

        with mock.patch.object(mcp_pool, "settings", replace(mcp_pool.settings, mcp_resident_sessions=False)):
            first, second = asyncio.run(run())
        self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
