"""
Stage 8.1 Real Chromium Runtime Verification Script.
Executes an end-to-end smoke test against the actual installed Chromium binary:
1. Playwright version & Chromium executable path inspection.
2. Real headless browser process launch.
3. Navigation to an ephemeral local HTTP test server.
4. DOM text and element inspection.
5. Form interaction (filling inputs and clicking controls).
6. Viewport screenshot generation with verified disk persistence.
7. Clean browser context and process shutdown.
"""

import asyncio
import importlib.metadata
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import time

from backend.browser.runtime import PlaywrightBrowserRuntime
from backend.browser.security import SSRFValidator


class SmokeTestServerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        html = """<!DOCTYPE html>
<html>
<head><title>Go 81 Chromium Smoke Test Page</title></head>
<body>
    <header><h1>Go 81 Sovereign Autonomous Browser Verification</h1></header>
    <main>
        <p id="status-text">Chromium subsystem initialized successfully.</p>
        <nav>
            <a id="safe-nav-link" href="/docs">Safe Documentation Link</a>
        </nav>
        <form id="test-form" action="/submit" method="POST">
            <label for="username">Username:</label>
            <input type="text" id="username" name="username" value="" />
            <label for="secret-token">Secret Token:</label>
            <input type="password" id="secret-token" name="secret_token" value="" />
            <button type="submit" id="submit-btn">Submit Verification</button>
        </form>
    </main>
</body>
</html>"""
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format, *args):
        pass  # Suppress HTTP server logs in output


def run_smoke_test():
    print("=" * 70)
    print("GO 81 — STAGE 8.1 REAL CHROMIUM RUNTIME VERIFICATION")
    print("=" * 70)

    # 1. Playwright Version
    pw_version = importlib.metadata.version("playwright")
    print(f"[1/8] Playwright Installed Version: {pw_version}")

    # Spin up ephemeral local server on an available port
    server = HTTPServer(("127.0.0.1", 0), SmokeTestServerHandler)
    port = server.server_port
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    base_url = f"http://127.0.0.1:{port}"
    print(f"      Ephemeral local HTTP server running at: {base_url}")

    async def _async_smoke():
        tmp_dir = tempfile.mkdtemp(prefix="go81_smoke_")
        validator = SSRFValidator(
            allow_local_test_server=True,
            allowed_test_hosts={f"127.0.0.1:{port}", "127.0.0.1"},
        )
        runtime = PlaywrightBrowserRuntime(
            base_dir=tmp_dir,
            ssrf_validator=validator,
            headless=True,
        )

        try:
            # 2. Browser process launch & Chromium Executable Path
            await runtime.initialize()
            executable_path = runtime._playwright.chromium.executable_path
            print(f"[2/8] Chromium Executable Path: {executable_path}")
            print(f"[3/8] Browser Process Launched: Headless Chromium PID={runtime._browser.is_connected()}")
            assert runtime._browser.is_connected() is True

            # 4. Navigation to controlled test page
            print(f"[4/8] Navigating to: {base_url}")
            nav_evidence = await runtime.navigate(task_id="smoke-task", url=base_url)
            print(f"      Navigation Result: Status={nav_evidence.status_code}, Title='{nav_evidence.title}'")
            assert nav_evidence.title == "Go 81 Chromium Smoke Test Page"

            # 5. DOM Inspection
            print(f"[5/8] Inspecting DOM...")
            inspect_evidence = await runtime.inspect(task_id="smoke-task", selector="#status-text")
            print(f"      Extracted Text: '{inspect_evidence.dom_snapshot[:100]}...'")
            assert "Chromium subsystem initialized" in inspect_evidence.dom_snapshot

            # 6. Form Interaction
            print(f"[6/8] Interacting with form elements...")
            fill_evidence = await runtime.fill(task_id="smoke-task", selector="#username", value="sovereign_agent_01")
            print(f"      Fill Result: {fill_evidence.result_summary}")
            assert fill_evidence.side_effect_produced is True

            # Fill password (to verify redaction & masking)
            pw_fill = await runtime.fill(task_id="smoke-task", selector="#secret-token", value="super_secret_otp_9999")
            print(f"      Password Fill: {pw_fill.result_summary}")
            assert "[REDACTED_CREDENTIAL]" in pw_fill.result_summary

            # 7. Screenshot Generation
            print(f"[7/8] Capturing screenshot...")
            ss_evidence = await runtime.screenshot(task_id="smoke-task", full_page=True)
            ss_path = ss_evidence.screenshot_ref
            ss_bytes = os.path.getsize(ss_path)
            print(f"      Screenshot saved: {ss_path} ({ss_bytes} bytes)")
            assert os.path.exists(ss_path)
            assert ss_bytes > 5000

            # 8. Clean Browser Shutdown
            print(f"[8/8] Shutting down browser...")
            await runtime.shutdown()
            is_connected = runtime._browser is not None
            print(f"      Browser cleanly terminated: Process Closed = {not is_connected}")
            assert is_connected is False

        finally:
            server.shutdown()
            server.server_close()

    asyncio.run(_async_smoke())
    print("=" * 70)
    print("REAL CHROMIUM RUNTIME VERIFICATION: 100% SUCCESS")
    print("=" * 70)


if __name__ == "__main__":
    run_smoke_test()

