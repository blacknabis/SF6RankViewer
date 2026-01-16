from scraper import Scraper

if __name__ == "__main__":
    print("=== SF6 Viewer 로그인 도우미 ===")
    print("브라우저가 열리면 Capcom ID로 로그인해주세요.")
    print("로그인이 완료되면 이 창으로 돌아와서 엔터 키를 눌러주세요.")
    
    s = Scraper()
    s.login_and_save_state()
    
    print("=== 설정 완료 ===")
    print("이제 auth.json 파일이 생성되었습니다.")
