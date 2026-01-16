from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from database import get_db, init_db, Player, Match, engine, Base
from scraper import Scraper, AUTH_FILE
import os
import threading
import webbrowser
from datetime import datetime

app = FastAPI()

# 정적 파일 마운트 (오버레이 HTML/CSS/JS)
app.mount("/static", StaticFiles(directory="static"), name="static")

# DB 초기화
init_db()

scraper = Scraper()

@app.get("/")
async def get_dashboard():
    """대시보드 페이지 반환"""
    return FileResponse("static/dashboard.html")

@app.get("/overlay")
async def get_overlay():
    """오버레이 HTML 페이지 반환"""
    return FileResponse("static/overlay.html")

@app.get("/api/status")
async def get_status(db: Session = Depends(get_db)):
    """시스템 상태 및 최신 플레이어 데이터 반환"""
    auth_exists = os.path.exists(AUTH_FILE)
    
    # DB 연결 확인 및 최신 데이터 조회
    try:
        player = db.query(Player).order_by(Player.last_updated.desc()).first()
        db_exists = True
        latest_player = None
        if player:
            latest_player = {
                "name": player.name,
                "lp": player.lp,
                "rank": player.rank,
                "character": player.character,
                "last_updated": player.last_updated.isoformat()
            }
    except Exception:
        db_exists = False
        latest_player = None

    return {
        "auth_exists": auth_exists,
        "db_exists": db_exists,
        "latest_player": latest_player
    }

@app.post("/api/login")
async def trigger_login(background_tasks: BackgroundTasks):
    """백그라운드에서 로그인 프로세스 시작"""
    def run_login():
        # 별도 스레드에서 실행하여 서버 블로킹 방지
        scraper.login_and_save_state()
    
    background_tasks.add_task(run_login)
    return {"message": "Login browser launching..."}

@app.get("/api/stats")
async def get_stats(db: Session = Depends(get_db)):
    """
    최신 통계 반환.
    DB에서 가장 최근 업데이트된 플레이어 정보를 가져옵니다.
    없으면 더미 데이터를 반환합니다.
    """
    player = db.query(Player).order_by(Player.last_updated.desc()).first()
    
    if player:
        return {
            "name": player.name,
            "lp": player.lp,
            "rank": player.rank,
            "character": player.character,
            # 매치 기록 등 추가 가능
        }
    else:
        # DB에 데이터가 없을 경우 (초기 상태)
        return {
            "name": "No Data",
            "lp": 0,
            "rank": "Unranked",
            "character": "None"
        }

import json

USER_CONFIG_FILE = "user_config.json"

def load_user_config():
    if os.path.exists(USER_CONFIG_FILE):
        try:
            with open(USER_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {}

def save_user_config(config):
    with open(USER_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)

@app.get("/api/config/user_code")
def get_user_code_config():
    config = load_user_config()
    return {"user_code": config.get("user_code", "")}

@app.post("/api/config/user_code")
def set_user_code_config(data: dict):
    user_code = data.get("user_code")
    config = load_user_config()
    config["user_code"] = user_code
    save_user_config(config)
    return {"status": "success", "user_code": user_code}

@app.post("/api/refresh")
def refresh_stats(db: Session = Depends(get_db)):
    """
    스크래핑을 트리거하여 DB를 업데이트합니다.
    """
    try:
        config = load_user_config()
        user_code_config = config.get("user_code")
        
        data = scraper.get_stats(user_code=user_code_config)
        if data:
            user_code = data.get("user_code", "unknown_code")
            
            # DB 업데이트 로직 (Upsert)
            player = db.query(Player).filter(Player.user_code == user_code).first()
            
            if player:
                # 기존 플레이어 업데이트
                player.name = data.get("name")
                player.lp = data.get("lp")
                player.rank = data.get("rank")
                player.character = data.get("character")
                player.last_updated = datetime.now()
            else:
                # 새 플레이어 생성
                player = Player(
                    user_code=user_code,
                    name=data.get("name"),
                    lp=data.get("lp"),
                    rank=data.get("rank"),
                    character=data.get("character")
                )
                db.add(player)
            
            db.commit()
            return {"status": "success", "data": data}
        else:
            raise HTTPException(status_code=500, detail="Scraping failed or not logged in")
    except Exception as e:
        error_msg = str(e)
        if "AUTH_ERROR" in error_msg:
            raise HTTPException(status_code=401, detail=error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

@app.post("/api/collect_matches")
def collect_matches(db: Session = Depends(get_db)):
    """
    대전 기록을 수집하여 DB에 저장합니다.
    """
    try:
        # 먼저 플레이어 정보 가져오기
        config = load_user_config()
        user_code_config = config.get("user_code")
        
        player_data = scraper.get_stats(user_code=user_code_config)
        if not player_data:
            raise HTTPException(status_code=500, detail="Failed to get player data")
        
        user_code = player_data.get("user_code")
        
        # 플레이어 찾기 또는 생성
        player = db.query(Player).filter(Player.user_code == user_code).first()
        if not player:
            player = Player(
                user_code=user_code,
                name=player_data.get("name"),
                lp=player_data.get("lp"),
                rank=player_data.get("rank"),
                character=player_data.get("character")
            )
            db.add(player)
        else:
            # 기존 플레이어 정보도 최신으로 업데이트
            player.name = player_data.get("name")
            player.lp = player_data.get("lp")
            player.rank = player_data.get("rank")
            player.character = player_data.get("character")
            player.last_updated = datetime.now()
            
        db.commit()
        db.refresh(player)
        
        # 대전 기록 수집 (내 이름 전달)
        my_name = player_data.get("name")
        matches = scraper.get_match_history(user_code, my_name=my_name, limit=20)
        
        if not matches:
            return {"status": "success", "message": "No new matches found", "count": 0}
        
        # DB에 저장 (중복 체크: 상대이름+캐릭터+결과+MR/LP로 판단)
        new_count = 0
        for match in matches:
            # 날짜 파싱 - 여러 형식 시도
            match_datetime = None
            date_formats = [
                "%Y/%m/%d %H:%M",      # 요청된 포맷: 2025/11/23 23:03
                "%m/%d/%Y %H:%M",      # 기존 포맷: 11/23/2025 14:38
                "%Y. %m. %d. %p %I:%M:%S", # 한국어 포맷: 2025. 11. 23. 오후 2:38:00
                "%Y. %m. %d. %H:%M:%S",    # 한국어 포맷: 2025. 11. 23. 14:38:00
                "%Y-%m-%d %H:%M:%S"        # ISO 포맷
            ]
            
            for fmt in date_formats:
                try:
                    match_datetime = datetime.strptime(match["date"], fmt)
                    # print(f"날짜 파싱 성공: {match['date']} -> {match_datetime}")
                    break
                except ValueError:
                    continue
            
            if not match_datetime:
                print(f"⚠️ 날짜 파싱 실패: {match['date']} -> 현재 시간으로 대체")
                match_datetime = datetime.now()
            
            # 중복 체크: 상대 이름, 캐릭터, 결과, MR/LP가 모두 같으면 중복으로 간주
            existing = db.query(Match).filter(
                Match.player_id == player.id,
                Match.opponent_name == match["opponent_name"],
                Match.opponent_character == match["opponent_character"],
                Match.result == match["result"],
                Match.my_mr == match["my_mr"],
                Match.my_lp == match["my_lp"]
            ).first()
            
            if not existing:
                new_match = Match(
                    player_id=player.id,
                    opponent_name=match["opponent_name"],
                    opponent_character=match["opponent_character"],
                    opponent_mr=match["opponent_mr"],
                    opponent_lp=match["opponent_lp"],
                    my_character=match["my_character"],
                    my_mr=match["my_mr"],
                    my_lp=match["my_lp"],
                    result=match["result"],
                    match_date=match_datetime
                )
                db.add(new_match)
                new_count += 1
        
        db.commit()
        
        return {
            "status": "success",
            "message": f"Collected {new_count} new matches out of {len(matches)} total",
            "new_count": new_count,
            "total_scraped": len(matches)
        }
        
    except Exception as e:
        error_msg = str(e)
        if "AUTH_ERROR" in error_msg:
            raise HTTPException(status_code=401, detail=error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

@app.get("/api/matches")
def get_matches(db: Session = Depends(get_db), limit: int = 50):
    """
    저장된 대전 기록을 조회합니다.
    """
    try:
        matches = db.query(Match).order_by(Match.match_date.desc()).limit(limit).all()
        return [{
            "id": m.id,
            "opponent_name": m.opponent_name,
            "opponent_character": m.opponent_character,
            "opponent_mr": m.opponent_mr,
            "opponent_lp": m.opponent_lp,
            "my_character": m.my_character,
            "my_mr": m.my_mr,
            "my_lp": m.my_lp,
            "result": m.result,
            "match_date": m.match_date.isoformat() if m.match_date else None
        } for m in matches]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/stats")
def stats_page():
    """통계 페이지 제공"""
    return FileResponse("static/stats.html")

@app.get("/api/stats/summary")
def get_stats_summary(db: Session = Depends(get_db), limit: int = 100):
    """
    전체 승률 및 최근 N개 승률 통계
    """
    try:
        # 전체 승/패 카운트
        total_matches = db.query(Match).count()
        total_wins = db.query(Match).filter(Match.result == "WIN").count()
        total_losses = db.query(Match).filter(Match.result == "LOSE").count()
        
        # 최근 N개 승/패 카운트 (limit 파라미터 사용)
        recent_matches = db.query(Match).order_by(Match.match_date.desc()).limit(limit).all()
        recent_wins = sum(1 for m in recent_matches if m.result == "WIN")
        recent_losses = sum(1 for m in recent_matches if m.result == "LOSE")
        
        # 마지막 대전 상대
        last_match = db.query(Match).order_by(Match.match_date.desc()).first()
        last_opponent_name_stats = None
        last_opponent_char_stats = None
        my_character = None
        
        if last_match:
            opponent_name = last_match.opponent_name
            opponent_char = last_match.opponent_character
            my_character = last_match.my_character  # 내가 마지막으로 사용한 캐릭터
            
            # 마지막 상대 유저와의 전체 전적
            opponent_name_matches = db.query(Match).filter(Match.opponent_name == opponent_name).all()
            opponent_name_wins = sum(1 for m in opponent_name_matches if m.result == "WIN")
            opponent_name_losses = sum(1 for m in opponent_name_matches if m.result == "LOSE")
            last_opponent_name_stats = {
                "name": opponent_name,
                "wins": opponent_name_wins,
                "losses": opponent_name_losses,
                "total": len(opponent_name_matches)
            }
            
            # 마지막 상대 캐릭터와의 전체 전적
            opponent_char_matches = db.query(Match).filter(Match.opponent_character == opponent_char).all()
            opponent_char_wins = sum(1 for m in opponent_char_matches if m.result == "WIN")
            opponent_char_losses = sum(1 for m in opponent_char_matches if m.result == "LOSE")
            last_opponent_char_stats = {
                "character": opponent_char,
                "wins": opponent_char_wins,
                "losses": opponent_char_losses,
                "total": len(opponent_char_matches)
            }
        
        return {
            "total": {
                "wins": total_wins,
                "losses": total_losses,
                "total": total_matches
            },
            "recent_100": {
                "wins": recent_wins,
                "losses": recent_losses,
                "total": len(recent_matches)
            },
            "my_character": my_character,  # 내가 사용한 캐릭터 추가
            "last_opponent_name": last_opponent_name_stats,
            "last_opponent_char": last_opponent_char_stats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stats/opponent/{opponent_name}")
def get_opponent_stats(opponent_name: str, db: Session = Depends(get_db)):
    """
    특정 상대와의 전적
    """
    try:
        matches = db.query(Match).filter(Match.opponent_name == opponent_name).all()
        wins = sum(1 for m in matches if m.result == "WIN")
        losses = sum(1 for m in matches if m.result == "LOSE")
        
        return {
            "opponent_name": opponent_name,
            "wins": wins,
            "losses": losses,
            "total": len(matches)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stats/mr_history")
def get_mr_history(db: Session = Depends(get_db), limit: int = 100):
    """
    MR 변화 히스토리 (그래프용)
    """
    try:
        # MR이 있는 매치만 가져오기 (시간순)
        matches = db.query(Match).filter(Match.my_mr.isnot(None)).order_by(Match.match_date.asc()).limit(limit).all()
        
        history = [{
            "date": m.match_date.isoformat() if m.match_date else None,
            "mr": m.my_mr,
            "result": m.result
        } for m in matches]
        
        return history
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stats/opponents")
def get_all_opponents(db: Session = Depends(get_db)):
    """
    모든 상대 목록 (드롭다운용)
    """
    try:
        # 고유한 상대 이름 목록
        opponents = db.query(Match.opponent_name).distinct().all()
        return [{"name": opp[0]} for opp in opponents if opp[0]]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/delete_database")
def delete_database(db: Session = Depends(get_db)):
    """
    데이터베이스의 모든 데이터를 삭제합니다.
    """
    try:
        # 모든 매치 기록 삭제
        db.query(Match).delete()
        # 모든 플레이어 정보 삭제
        db.query(Player).delete()
        db.commit()
        
        return {
            "status": "success",
            "message": "All database records have been deleted successfully"
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete database: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    
    # 서버 시작 후 브라우저 자동 실행
    # 서버 시작 후 브라우저 자동 실행 (Chrome 우선)
    def open_browser():
        import time
        import os
        import webbrowser
        
        time.sleep(1.5)  # 서버가 완전히 시작될 때까지 대기
        
        target_url = "http://localhost:8000"
        
        # Chrome 경로 후보 (Windows)
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe") 
        ]
        
        chrome_path = None
        for path in chrome_paths:
            if os.path.exists(path):
                chrome_path = path
                break
                
        if chrome_path:
            try:
                # Chrome 등록 및 실행
                webbrowser.register('chrome', None, webbrowser.BackgroundBrowser(chrome_path))
                webbrowser.get('chrome').open(target_url)
                print(f"Chrome 브라우저로 실행합니다: {chrome_path}")
                return
            except Exception as e:
                print(f"Chrome 실행 실패: {e}")
        
        # Chrome 실패 시 기본 브라우저 사용
        webbrowser.open(target_url)
    
    # 별도 스레드에서 브라우저 실행
    threading.Thread(target=open_browser, daemon=True).start()
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
