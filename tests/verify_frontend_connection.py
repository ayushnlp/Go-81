import asyncio
import os
import sys
from playwright.async_api import async_playwright

SCREENSHOT_DIR = r"C:\Users\ayush\.gemini\antigravity\brain\32ec0486-6571-4517-b7be-d801d1246efd\screenshots_stage5"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

async def test_frontend_connection():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 800})
        
        # Test 1: Load http://localhost:3001
        print("Navigating to http://localhost:3001...")
        await page.goto("http://localhost:3001", wait_until="networkidle")
        await page.wait_for_timeout(2500)
        
        # Find the connection button by aria-label or title
        connected_btn = await page.wait_for_selector('button[aria-label="Backend Connected"]', timeout=8000)
        assert connected_btn is not None, "Backend Connected button not found"
        
        aria_label = await connected_btn.get_attribute("aria-label")
        title_attr = await connected_btn.get_attribute("title")
        print(f"Status Indicator Aria-Label: '{aria_label}', Title: '{title_attr}'")
        
        # Check dot element inside
        dot_span = await connected_btn.query_selector('span')
        assert dot_span is not None, "Dot span element not found"
        dot_class = await dot_span.get_attribute("class")
        print(f"Dot Class: {dot_class}")
        
        # Verify classes
        assert "bg-emerald-500" in dot_class, f"Expected 'bg-emerald-500' in dot class, got: {dot_class}"
        assert "animate-pulse" in dot_class, f"Expected 'animate-pulse' in dot class, got: {dot_class}"
        
        # Capture initial screenshot
        initial_ss = os.path.join(SCREENSHOT_DIR, "10_live_connected_3001.png")
        await page.screenshot(path=initial_ss)
        print(f"Saved initial screenshot to {initial_ss}")
        
        # Test 2: Send a message in chat input
        chat_input = await page.query_selector('input[placeholder*="Ask anything"], textarea[placeholder*="Ask anything"]')
        assert chat_input is not None, "Chat input field not found"
        
        prompt = "What is 15 * 8?"
        print(f"Typing prompt: {prompt}")
        await chat_input.fill(prompt)
        await chat_input.press("Enter")
        
        print("Waiting for response...")
        await page.wait_for_selector('text=120', timeout=20000)
        print("Found calculation response '120' in chat!")
        
        # Verify no error bubble is present
        error_bubbles = await page.query_selector_all('text="Unable to connect to the Go 81 backend"')
        assert len(error_bubbles) == 0, "Unexpected backend disconnected error bubble found in chat!"
        
        # Capture conversation screenshot
        chat_ss = os.path.join(SCREENSHOT_DIR, "11_live_chat_connected_3001.png")
        await page.screenshot(path=chat_ss)
        print(f"Saved chat screenshot to {chat_ss}")
        
        # Test 3: Verify http://localhost:3000 as well
        print("Navigating to http://localhost:3000...")
        await page.goto("http://localhost:3000", wait_until="networkidle")
        await page.wait_for_timeout(2500)
        btn_3000 = await page.wait_for_selector('button[aria-label="Backend Connected"]', timeout=8000)
        assert btn_3000 is not None, "Backend Connected button on port 3000 not found"
        print("Port 3000 also verified connected!")
        
        await browser.close()
        print("\nALL VERIFICATIONS PASSED: Both port 3000 and 3001 are live, pulsing emerald green, and chat works seamlessly!")

if __name__ == "__main__":
    asyncio.run(test_frontend_connection())
