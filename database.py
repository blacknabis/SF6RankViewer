from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

# 데이터베이스 URL 설정 (SQLite 사용)
SQLALCHEMY_DATABASE_URL = "sqlite:///./sf6viewer.db"

# 엔진 생성
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

# 세션 로컬 생성
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 베이스 클래스 생성
Base = declarative_base()

class Player(Base):
    """플레이어 정보를 저장하는 모델"""
    __tablename__ = "players"

    id = Column(Integer, primary_key=True, index=True)
    user_code = Column(String, unique=True, index=True) # CFN 유저 코드
    name = Column(String) # 닉네임
    lp = Column(Integer) # 리그 포인트
    rank = Column(String) # 랭크 (예: Master, Diamond)
    character = Column(String) # 주 캐릭터
    last_updated = Column(DateTime, default=datetime.now)

class Match(Base):
    """매치 기록을 저장하는 모델"""
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("players.id"))
    opponent_name = Column(String)
    opponent_character = Column(String)
    opponent_mr = Column(Integer, nullable=True)  # 상대 MR (Master Rating)
    opponent_lp = Column(Integer, nullable=True)  # 상대 LP
    my_character = Column(String)  # 내가 사용한 캐릭터
    my_mr = Column(Integer, nullable=True)  # 내 MR
    my_lp = Column(Integer, nullable=True)  # 내 LP
    result = Column(String)  # WIN, LOSE, DRAW
    match_date = Column(DateTime)  # 대전 날짜/시간
    
    player = relationship("Player", back_populates="matches")

Player.matches = relationship("Match", order_by=Match.id, back_populates="player")

def init_db():
    """데이터베이스 테이블 생성"""
    Base.metadata.create_all(bind=engine)

def get_db():
    """DB 세션 의존성 주입"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
