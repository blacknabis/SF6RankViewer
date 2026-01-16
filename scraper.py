import json
import os
import time
from playwright.sync_api import sync_playwright

AUTH_FILE = "auth.json"
TARGET_URL = "https://www.streetfighter.com/6/buckler"

class Scraper:
    def __init__(self):
        self.browser = None
        self.context = None
        self.page = None

    def login_and_save_state(self):
        """
        사용자가 직접 로그인할 수 있도록 브라우저를 띄우고,
        로그인 완료 후 세션 상태를 저장합니다.
        """
        print("로그인을 위해 브라우저를 엽니다. 로그인 후 창을 닫지 마시고 엔터를 눌러주세요.")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            page.goto(TARGET_URL)
            
            # 사용자가 로그인할 때까지 대기 (브라우저가 닫힐 때까지 반복)
            print("브라우저가 열렸습니다. 로그인 후 브라우저를 닫아주세요.")
            
            try:
                while True:
                    if page.is_closed():
                        break
                    
                    # 현재 URL이 타겟 사이트일 때 주기적으로 저장 (로그인 상태 갱신)
                    try:
                        if "streetfighter.com" in page.url:
                            context.storage_state(path=AUTH_FILE)
                            # print(f"인증 정보 갱신됨: {page.url}") # 너무 자주 출력되면 시끄러우므로 주석 처리
                    except Exception:
                        pass 
                        
                    page.wait_for_timeout(2000) # 2초마다 상태 저장 시도
            except Exception as e:
                print(f"브라우저 감지 중 에러: {e}")
            
            print(f"인증 정보가 {AUTH_FILE}에 저장되었습니다.")

    def get_stats(self, user_code=None):
        """
        저장된 세션을 사용하여 백그라운드에서 전적 및 프로필 정보를 가져옵니다.
        """
        print("=== [Scraper] get_stats 시작 ===")
        if not os.path.exists(AUTH_FILE):
            print("❌ [Scraper] 인증 파일이 없습니다. 먼저 로그인을 진행해주세요.")
            return None

        data = {}
        with sync_playwright() as p:
            print("1. 브라우저 실행 중 (Headless: True)...")
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                storage_state=AUTH_FILE,
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1920, 'height': 1080},
                locale='ko-KR',
                timezone_id='Asia/Seoul'
            )
            page = context.new_page()
            
            print(f"2. 타겟 URL 접속 중: {TARGET_URL}")
            page.goto(TARGET_URL, wait_until='networkidle')
            page.wait_for_load_state("networkidle")
            
            if "error-system" in page.url:
                print("❌ [Scraper] 시스템 에러 페이지 감지됨. 인증 만료 또는 시스템 오류.")
                browser.close()
                raise Exception("AUTH_ERROR: System error page detected")
            
            print("3. 페이지 로드 완료. 사용자 정보 파싱 시작...")

            try:
                # 이름 및 User Code 가져오기
                name = "Unknown"
                extracted_user_code = "unknown_code"

                # 전략 1: 프로필 링크(a 태그)에서 텍스트와 href 추출
                print("   - 프로필 링크 탐색 중...")
                # 1. 헤더의 '내 프로필' 또는 닉네임 링크 찾기
                # 보통 href에 /profile/숫자 형태가 포함됨
                profile_links = page.locator("a[href*='/profile/']").all()
                print(f"   - 발견된 프로필 링크 후보 수: {len(profile_links)}")

                target_link = None
                for i, link in enumerate(profile_links):
                    try:
                        text = link.text_content().strip()
                        href = link.get_attribute("href")
                        print(f"     [{i}] 텍스트='{text}', href='{href}'")
                        
                        if href:
                            # href에서 숫자(User Code) 추출 시도
                            parts = href.split("/")
                            for part in reversed(parts):
                                if part.isdigit() and len(part) > 5: # User Code는 보통 깁니다 (최소 6자리 이상 가정)
                                    extracted_user_code = part
                                    target_link = link
                                    print(f"       -> 유효한 User Code 후보 발견: {extracted_user_code}")
                                    break
                        
                        if target_link:
                            break
                    except Exception as e:
                        print(f"     [{i}] 링크 분석 중 에러: {e}")
                        continue
                
                print(f"   - 최종 추출된 User Code: {extracted_user_code}")
                
                if not user_code or user_code == "unknown_code":
                    user_code = extracted_user_code

                # 상세 프로필 페이지로 이동
                if user_code and user_code != "unknown_code":
                    profile_url = f"{TARGET_URL}/ko-kr/profile/{user_code}"
                    print(f"4. 상세 프로필 페이지로 이동: {profile_url}")
                    page.goto(profile_url, wait_until='networkidle')
                    page.wait_for_load_state("networkidle")
                    
                    # 상세 페이지에서 정보 추출
                    print("5. 상세 페이지 정보 파싱...")
                    
                    # JSON 데이터 파싱 (Next.js Hydration Data 사용)
                    try:
                        next_data_el = page.locator("#__NEXT_DATA__")
                        if next_data_el.count() > 0:
                            json_text = next_data_el.text_content()
                            next_data = json.loads(json_text)
                            
                            # 데이터 경로: props -> pageProps -> fighter_banner_info
                            info = next_data.get("props", {}).get("pageProps", {}).get("fighter_banner_info", {})
                            
                            if info:
                                # 이름
                                name = info.get("personal_info", {}).get("fighter_id", "Unknown")
                                print(f"   - [JSON] 이름: {name}")

                                # 캐릭터 (영어 대문자, 예: RASHID)
                                character = info.get("favorite_character_alpha", "Unknown")
                                print(f"   - [JSON] 캐릭터: {character}")
                                
                                # 리그 정보
                                league_info = info.get("favorite_character_league_info", {})
                                if league_info:
                                    # LP
                                    lp = league_info.get("league_point", 0)
                                    print(f"   - [JSON] LP: {lp}")
                                    
                                    # MR & Rank
                                    mr_val = league_info.get("master_rating", 0)
                                    rank_name = league_info.get("league_rank_info", {}).get("league_rank_name", "Unknown")
                                    
                                    if mr_val and mr_val > 0:
                                        mr = mr_val
                                        rank = f"{rank_name} ({mr} MR)"
                                        print(f"   - [JSON] MR: {mr}")
                                    else:
                                        rank = rank_name
                                        print(f"   - [JSON] Rank: {rank}")
                            else:
                                print("   - [JSON] fighter_banner_info가 비어있음")
                        else:
                            print("   - [JSON] __NEXT_DATA__ 태그를 찾을 수 없음 (DOM 파싱으로 전환 필요)")
                            
                    except Exception as e:
                        print(f"   - JSON 파싱 중 에러: {e}")


                    data = {
                        "user_code": user_code,
                        "name": name,
                        "lp": lp,
                        "rank": rank,
                        "character": character
                    }
                    print(f"✅ [Scraper] 데이터 파싱 성공: {data}")

                else:
                    print("❌ [Scraper] 유효한 User Code를 찾지 못했습니다.")
                    data = {
                        "user_code": "unknown",
                        "name": "Unknown",
                        "lp": 0,
                        "rank": "Unknown",
                        "character": "Unknown"
                    }

            except Exception as e:
                print(f"❌ [Scraper] get_stats 실행 중 치명적 에러: {e}")
                import traceback
                traceback.print_exc()
                return None

            
            browser.close()
            print("=== [Scraper] get_stats 종료 ===")
            
        return data

    def get_match_history(self, user_code, my_name=None, limit=20):
        """
        Battle Log 페이지에서 최근 대전 기록을 가져옵니다.
        my_name: 내 이름 (Player 1/2 구분을 위해 필요)
        """
        print(f"=== [Scraper] get_match_history 시작 (User Code: {user_code}, My Name: {my_name}) ===")
        if not os.path.exists(AUTH_FILE):
            print("❌ [Scraper] 인증 파일이 없습니다. 먼저 로그인을 진행해주세요.")
            return []

        matches = []
        with sync_playwright() as p:
            print("1. 브라우저 실행 중 (Headless: False)...")
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                storage_state=AUTH_FILE,
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1920, 'height': 1080},
                locale='ko-KR',
                timezone_id='Asia/Seoul'
            )
            page = context.new_page()
            
            # Use the Ranked Match URL
            battlelog_url = f"{TARGET_URL}/ko-kr/profile/{user_code}/battlelog/rank"
            print(f"2. Battle Log (Ranked) 페이지 접속: {battlelog_url}")
            page.goto(battlelog_url, wait_until='networkidle')
            page.wait_for_load_state("networkidle")
            
            if "error-system" in page.url:
                print("❌ [Scraper] 시스템 에러 페이지 감지됨. 인증 만료 또는 시스템 오류.")
                browser.close()
                raise Exception("AUTH_ERROR: System error page detected")
            
            print("3. 대전 기록 파싱 시작...")
            try:
                match_items = page.locator(".battle_data_battlelog__list__JNDjG > li").all()
                print(f"   - 발견된 리스트 아이템 수: {len(match_items)}")
                
                if not match_items:
                    print("⚠️ [Scraper] 대전 기록을 찾을 수 없습니다. 스크린샷을 저장합니다.")
                    page.screenshot(path="debug_scraper_no_matches.png")
                
                for i, item in enumerate(match_items[:limit]):
                    try:
                        date_el = item.locator(".battle_data_date__f1sP6")
                        date_str = date_el.text_content().strip() if date_el.count() > 0 else ""
                        
                        # Player 1과 Player 2의 이름을 모두 가져오기
                        p1_name_el = item.locator(".battle_data_name_p1__Ookss .battle_data_name__IPyjF")
                        p1_name = p1_name_el.text_content().strip() if p1_name_el.count() > 0 else "Unknown"
                        
                        p2_name_el = item.locator(".battle_data_name_p2__ua7Oo .battle_data_name__IPyjF")
                        p2_name = p2_name_el.text_content().strip() if p2_name_el.count() > 0 else "Unknown"
                        
                        # Player 1과 Player 2의 승패 상태 확인
                        p1_div = item.locator(".battle_data_player1__MIpvf")
                        p1_class = p1_div.get_attribute("class") if p1_div.count() > 0 else ""
                        
                        p2_div = item.locator(".battle_data_player_2__STQb6")
                        p2_class = p2_div.get_attribute("class") if p2_div.count() > 0 else ""
                        
                        # 승패 판정
                        p1_won = "battle_data_win__8Y4Me" in p1_class
                        p2_won = "battle_data_win__8Y4Me" in p2_class
                        p1_lost = "battle_data_lose__ltUN0" in p1_class
                        p2_lost = "battle_data_lose__ltUN0" in p2_class
                        
                        # 내 이름과 비교하여 누가 나인지 판단
                        if my_name and p1_name == my_name:
                            # Player 1이 나
                            opponent_name = p2_name
                            my_char_el = item.locator(".battle_data_player1__MIpvf .battle_data_character__Mnj8l img")
                            opponent_char_el = item.locator(".battle_data_player2__tymNR .battle_data_character__Mnj8l img")
                            my_lp_el = item.locator(".battle_data_player1__MIpvf .battle_data_lp__6v5G9")
                            opponent_lp_el = item.locator(".battle_data_player2__tymNR .battle_data_lp__6v5G9")
                            
                            # Player 1의 승패 결과가 내 결과
                            if p1_won:
                                result = "WIN"
                            elif p1_lost:
                                result = "LOSE"
                            else:
                                result = "UNKNOWN"
                                
                        elif my_name and p2_name == my_name:
                            # Player 2가 나
                            opponent_name = p1_name
                            my_char_el = item.locator(".battle_data_player2__tymNR .battle_data_character__Mnj8l img")
                            opponent_char_el = item.locator(".battle_data_player1__MIpvf .battle_data_character__Mnj8l img")
                            my_lp_el = item.locator(".battle_data_player2__tymNR .battle_data_lp__6v5G9")
                            opponent_lp_el = item.locator(".battle_data_player1__MIpvf .battle_data_lp__6v5G9")
                            
                            # Player 2의 승패 결과가 내 결과
                            if p2_won:
                                result = "WIN"
                            elif p2_lost:
                                result = "LOSE"
                            else:
                                result = "UNKNOWN"
                                
                        else:
                            # 이름을 알 수 없는 경우 기본값 (Player 2가 나)
                            print(f"   - 경고: 이름 매칭 실패 (P1: {p1_name}, P2: {p2_name}, My: {my_name})")
                            opponent_name = p1_name
                            my_char_el = item.locator(".battle_data_player2__tymNR .battle_data_character__Mnj8l img")
                            opponent_char_el = item.locator(".battle_data_player1__MIpvf .battle_data_character__Mnj8l img")
                            my_lp_el = item.locator(".battle_data_player2__tymNR .battle_data_lp__6v5G9")
                            opponent_lp_el = item.locator(".battle_data_player1__MIpvf .battle_data_lp__6v5G9")
                            
                            # Player 2의 승패 결과가 내 결과 (기본값)
                            if p2_won:
                                result = "WIN"
                            elif p2_lost:
                                result = "LOSE"
                            else:
                                result = "UNKNOWN"
                        
                        # 캐릭터 정보 추출
                        my_character = my_char_el.get_attribute("alt") if my_char_el.count() > 0 else "Unknown"
                        opponent_character = opponent_char_el.get_attribute("alt") if opponent_char_el.count() > 0 else "Unknown"
                        
                        # 내 LP/MR
                        my_lp_text = my_lp_el.text_content().strip() if my_lp_el.count() > 0 else "0"
                        my_mr = None
                        my_lp = None
                        if "MR" in my_lp_text:
                            my_mr = int(my_lp_text.replace("MR", "").replace(",", "").strip())
                        elif "LP" in my_lp_text:
                            my_lp = int(my_lp_text.replace("LP", "").replace(",", "").strip())
                        
                        # 상대 LP/MR
                        opponent_lp_text = opponent_lp_el.text_content().strip() if opponent_lp_el.count() > 0 else "0"
                        opponent_mr = None
                        opponent_lp = None
                        if "MR" in opponent_lp_text:
                            opponent_mr = int(opponent_lp_text.replace("MR", "").replace(",", "").strip())
                        elif "LP" in opponent_lp_text:
                            opponent_lp = int(opponent_lp_text.replace("LP", "").replace(",", "").strip())
                        
                        match_data = {
                            "date": date_str,
                            "opponent_name": opponent_name,
                            "opponent_character": opponent_character,
                            "opponent_mr": opponent_mr,
                            "opponent_lp": opponent_lp,
                            "my_character": my_character,
                            "my_mr": my_mr,
                            "my_lp": my_lp,
                            "result": result
                        }
                        matches.append(match_data)
                        print(f"   - 매치 {i+1} 파싱 완료: {result} vs {opponent_name} ({opponent_character})")
                        
                    except Exception as e:
                        print(f"⚠️ [Scraper] 대전 기록 {i+1} 파싱 중 에러: {e}")
                        continue
                
                print(f"✅ [Scraper] 총 {len(matches)}개의 대전 기록을 가져왔습니다.")
                
            except Exception as e:
                print(f"❌ [Scraper] Battle Log 파싱 중 에러 발생: {e}")
                page.screenshot(path="debug_scraper_error.png")
            
            browser.close()
            print("=== [Scraper] get_match_history 종료 ===")
        
        return matches

if __name__ == "__main__":
    # 테스트 실행
    scraper = Scraper()
    # scraper.login_and_save_state() # 최초 1회 실행 필요
    pass
