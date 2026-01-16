from scraper import Scraper, AUTH_FILE
from playwright.sync_api import sync_playwright
import os

def debug_profile():
    if not os.path.exists(AUTH_FILE):
        print("Auth file missing.")
        return

    config = {}
    import json
    if os.path.exists("user_config.json"):
        with open("user_config.json", "r", encoding="utf-8") as f:
            config = json.load(f)
            
    user_code = "4285684297" # Hardcoded for debug
    if not user_code:
        print("User code missing.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            storage_state=AUTH_FILE,
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080},
            locale='ko-KR'
        )
        page = context.new_page()
        
        target_url = f"https://www.streetfighter.com/6/buckler/ko-kr/profile/{user_code}"
        print(f"Accessing: {target_url}")
        
        page.goto(target_url, wait_until='networkidle')
        page.wait_for_timeout(3000)
        
        # Save HTML
        with open("debug_profile.html", "w", encoding="utf-8") as f:
            f.write(page.content())
            
        print("Saved debug_profile.html")
        browser.close()

if __name__ == "__main__":
    debug_profile()
