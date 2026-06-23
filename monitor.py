"f""
AI 학습데이터 소송 모니터링 시스템 - 메인 에이전트
매일 UTC 23:00, 11:00에 자동 실행 (KST 08:00, 20:00)
배포 시 환경변수 FIRST_RUN=true로 즉시 실행 가능
"""

import os
import time
import json
import sqlite3
import logging
from datetime import datetime
from typing import Optional
import requests
import schedule
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from anthropic import Anthropic

# ==================== 설정 ====================

# API 키
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
SERPER_API_KEY = os.getenv("SERPER_API_KEY")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_TO = os.getenv("EMAIL_TO")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DB_PATH = os.getenv("DB_PATH", "lawsuits.db")

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger(__name__)

# ==================== 30개 다국어 검색 쿼리 ====================

DISCOVERY_QUERIES = [
    # 영어 (일반)
    "AI training data lawsuit filed 2024 2025",
    "generative AI lawsuit training dataset copyright",
    "OpenAI Anthropic Google Meta lawsuit",
    "Stability AI Midjourney lawsuit",
    "AI companies sued for training data",
    
    # 영어 (저작권/출판)
    "authors guild AI lawsuit",
    "publishing companies AI copyright lawsuit",
    "news organizations AI training data lawsuit",
    
    # 미국 (주별)
    "California AI lawsuit training data",
    "New York AI regulation lawsuit",
    "Texas AI lawsuit",
    
    # 한국어
    "AI 학습데이터 저작권 소송",
    "생성형 AI 학습데이터 소송",
    "AI 학습 데이터 저작권 침해 소송",
    
    # 일본어
    "AI 学習データ 著作権 訴訟",
    "生成型AI 訴訟 学習データ",
    
    # 중국어
    "人工智能 训练数据 版权 诉讼",
    "生成型AI 诉讼",
    
    # 유럽
    "GDPR AI lawsuit training data",
    "EU AI Act lawsuit",
    "Germany AI copyright lawsuit",
    
    # 기타
    "AI voice cloning lawsuit",
    "AI image generation lawsuit",
    "AI chatbot copyright lawsuit",
    "machine learning dataset lawsuit",
]

# ==================== 데이터베이스 ====================

def init_db():
    """데이터베이스 초기화"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS lawsuits (
        id TEXT PRIMARY KEY,
        case_name TEXT,
        plaintiff TEXT,
        defendant TEXT,
        country TEXT,
        court TEXT,
        jurisdiction TEXT,
        case_number TEXT,
        filed_date TEXT,
        subject_data TEXT,
        claims TEXT,
        summary TEXT,
        status TEXT,
        source_urls TEXT,
        raw_snippets TEXT,
        discovered_at TIMESTAMP,
        last_updated TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS updates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lawsuit_id TEXT,
        update_type TEXT,
        description TEXT,
        source_url TEXT,
        updated_at TIMESTAMP,
        FOREIGN KEY(lawsuit_id) REFERENCES lawsuits(id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS search_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        query TEXT,
        results_cnt INTEGER,
        searched_at TIMESTAMP
    )''')
    
    conn.commit()
    conn.close()

# ==================== API 호출 ====================

def serper_search(query: str, max_results: int = 10) -> list[dict]:
    """Serper.dev를 사용한 Google 검색"""
    try:
        url = "https://google.serper.dev/search"
        headers = {
            "X-API-KEY": SERPER_API_KEY,
            "Content-Type": "application/json"
        }
        payload = {
            "q": query,
            "num": max_results,
            "type": "news"
        }
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        
        results = []
        data = response.json()
        
        # 뉴스 결과
        for item in data.get("news", [])[:max_results]:
            results.append({
                "title": item.get("title"),
                "snippet": item.get("snippet"),
                "link": item.get("link"),
                "source": item.get("source")
            })
        
        return results
    except Exception as e:
        log.error(f"Serper search error: {e}")
        return []

def newsapi_search(query: str, max_results: int = 10) -> list[dict]:
    """NewsAPI를 사용한 뉴스 검색"""
    try:
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": query,
            "pageSize": max_results,
            "sortBy": "publishedAt",
            "apiKey": NEWS_API_KEY
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        results = []
        data = response.json()
        
        for article in data.get("articles", [])[:max_results]:
            results.append({
                "title": article.get("title"),
                "snippet": article.get("description"),
                "link": article.get("url"),
                "source": article.get("source", {}).get("name")
            })
        
        return results
    except Exception as e:
        log.error(f"NewsAPI search error: {e}")
        return []

def fetch_page_text(url: str, max_chars: int = 8000) -> str:
    """URL에서 텍스트 추출"""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.text[:max_chars]
    except Exception as e:
        log.warning(f"Failed to fetch {url}: {e}")
        return ""

# ==================== Claude 분석 ====================

def claude_analyze_snippets(snippets: list[dict], full_texts: dict) -> list[dict]:
    """Claude로 검색결과에서 소송 식별 및 정보 추출"""
    try:
        client = Anthropic(api_key=ANTHROPIC_API_KEY)
        
        # 스니펫 형식화
        snippets_text = "\n".join([
            f"- {s['title']}\n  {s['snippet']}\n  Source: {s['source']}\n  URL: {s['link']}"
            for s in snippets[:20]
        ])
        
        prompt = f"""당신은 AI 학습데이터와 관련된 소송을 식별하는 법률 분석가입니다.

다음 뉴스 스니펫들을 분석하여, AI 학습데이터/저작권과 관련된 소송을 식별하세요.

스니펫:
{snippets_text}

각 소송에 대해 JSON 형식으로 다음 정보를 추출하세요:
{{
    "lawsuits": [
        {{
            "case_name": "사건명",
            "plaintiff": "원고",
            "defendant": "피고",
            "country": "국가",
            "jurisdiction": "관할권",
            "filed_date": "제소일 (YYYY-MM-DD)",
            "subject_data": "대상 데이터 (예: 저작권 있는 책, 뉴스기사)",
            "claims": "주요 청구 (예: 저작권 침해, GDPR 위반)",
            "summary": "소송 요약 (한두 문장)",
            "confidence": "신뢰도 (high/medium/low)"
        }}
    ]
}}

JSON만 응답하세요."""
        
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )
        
        try:
            response_text = message.content[0].text
            # JSON 추출
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return data.get("lawsuits", [])
        except:
            log.warning("Failed to parse Claude response as JSON")
            return []
        
        return []
    except Exception as e:
        log.error(f"Claude analysis error: {e}")
        return []

def claude_analyze_update(lawsuit_case: dict) -> Optional[dict]:
    """기존 소송의 업데이트 확인"""
    try:
        client = Anthropic(api_key=ANTHROPIC_API_KEY)
        
        prompt = f"""다음 소송에 대한 최신 뉴스를 검색하고 업데이트를 식별하세요:

사건명: {lawsuit_case['case_name']}
원고: {lawsuit_case['plaintiff']}
피고: {lawsuit_case['defendant']}

최신 상태를 JSON으로 반환:
{{
    "has_update": true/false,
    "update_type": "판결/합의/기각/항소/기타",
    "description": "업데이트 설명",
    "new_status": "active/settled/dismissed/appealed/closed"
}}

JSON만 응답하세요."""
        
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        
        try:
            response_text = message.content[0].text
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except:
            pass
        
        return None
    except Exception as e:
        log.error(f"Claude update analysis error: {e}")
        return None

# ==================== ID 생성 ====================

def make_lawsuit_id(plaintiff: str, defendant: str, country: str) -> str:
    """소송 고유 ID 생성"""
    import hashlib
    key = f"{plaintiff}_{defendant}_{country}".lower()
    return hashlib.md5(key.encode()).hexdigest()

# ==================== 알림 ====================

def notify_new_lawsuit(lawsuit: dict):
    """신규 소송 알림"""
    # 이메일 알림
    if EMAIL_FROM and EMAIL_PASSWORD and EMAIL_TO:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"⚖️ 신규 AI 학습데이터 소송 감지: {lawsuit['case_name']}"
            msg["From"] = EMAIL_FROM
            msg["To"] = EMAIL_TO
            
            html = f"""
            <html>
                <body>
                    <h2>⚖️ 신규 AI 학습데이터 소송 감지</h2>
                    <table border="1" cellpadding="10">
                        <tr><td><b>사건명</b></td><td>{lawsuit.get('case_name', 'N/A')}</td></tr>
                        <tr><td><b>원고</b></td><td>{lawsuit.get('plaintiff', 'N/A')}</td></tr>
                        <tr><td><b>피고</b></td><td>{lawsuit.get('defendant', 'N/A')}</td></tr>
                        <tr><td><b>법원</b></td><td>{lawsuit.get('jurisdiction', 'N/A')}</td></tr>
                        <tr><td><b>제소일</b></td><td>{lawsuit.get('filed_date', 'N/A')}</td></tr>
                        <tr><td><b>대상 데이터</b></td><td>{lawsuit.get('subject_data', 'N/A')}</td></tr>
                        <tr><td><b>소송 원인</b></td><td>{lawsuit.get('claims', 'N/A')}</td></tr>
                        <tr><td><b>요약</b></td><td>{lawsuit.get('summary', 'N/A')}</td></tr>
                    </table>
                    <p>출처: {lawsuit.get('source_urls', 'N/A')}</p>
                </body>
            </html>
            """
            msg.attach(MIMEText(html, "html"))
            
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(EMAIL_FROM, EMAIL_PASSWORD)
                server.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
            log.info(f"✉️ Email sent for: {lawsuit['case_name']}")
        except Exception as e:
            log.error(f"Email notification error: {e}")
    
    # 텔레그램 알림
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        try:
            text = f"""
⚖️ 신규 AI 학습데이터 소송 감지

사건명: {lawsuit.get('case_name', 'N/A')}
원고: {lawsuit.get('plaintiff', 'N/A')}
피고: {lawsuit.get('defendant', 'N/A')}
법원: {lawsuit.get('jurisdiction', 'N/A')}
제소일: {lawsuit.get('filed_date', 'N/A')}

📝 요약: {lawsuit.get('summary', 'N/A')}
            """
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text})
            log.info(f"📱 Telegram sent for: {lawsuit['case_name']}")
        except Exception as e:
            log.error(f"Telegram notification error: {e}")

# ==================== 주 작업 ====================

def run_all():
    """신규 소송 탐지 + 기존 소송 추적"""
    log.info("=" * 60)
    log.info("🔍 AI Lawsuit Monitor - Full Run Started")
    log.info("=" * 60)
    
    # 1. 신규 소송 탐지
    log.info("")
    log.info("=" * 60)
    log.info("🌐 DISCOVERY JOB START - Searching for new lawsuits")
    log.info("=" * 60)
    
    all_snippets = []
    
    for query in DISCOVERY_QUERIES[:15]:  # 처음 15개 쿼리만 사용 (API 한도)
        log.info(f"🔎 Querying: {query}")
        
        serper_results = serper_search(query, max_results=5)
        newsapi_results = newsapi_search(query, max_results=5)
        
        all_snippets.extend(serper_results)
        all_snippets.extend(newsapi_results)
    
    log.info(f"📊 Total snippets collected: {len(all_snippets)}")
    
    # Claude 분석
    log.info("🤖 Claude analyzing snippets...")
    lawsuits = claude_analyze_snippets(all_snippets, {})
    log.info(f"✅ Claude identified {len(lawsuits)} potential lawsuits")
    
    # DB 저장
    new_count = 0
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    for lawsuit in lawsuits:
        lawsuit_id = make_lawsuit_id(
            lawsuit.get('plaintiff', ''),
            lawsuit.get('defendant', ''),
            lawsuit.get('country', '')
        )
        
        # 중복 확인
        c.execute("SELECT id FROM lawsuits WHERE id = ?", (lawsuit_id,))
        if not c.fetchone():
            c.execute("""
                INSERT INTO lawsuits 
                (id, case_name, plaintiff, defendant, country, jurisdiction, 
                 filed_date, subject_data, claims, summary, status, discovered_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                lawsuit_id,
                lawsuit.get('case_name', ''),
                lawsuit.get('plaintiff', ''),
                lawsuit.get('defendant', ''),
                lawsuit.get('country', ''),
                lawsuit.get('jurisdiction', ''),
                lawsuit.get('filed_date', ''),
                lawsuit.get('subject_data', ''),
                lawsuit.get('claims', ''),
                lawsuit.get('summary', ''),
                'active'
            ))
            new_count += 1
            
            # 알림
            notify_new_lawsuit(lawsuit)
            log.info(f"💾 New lawsuit saved: {lawsuit.get('case_name')}")
    
    conn.commit()
    log.info(f"🎯 DISCOVERY DONE - {new_count} new lawsuits saved")
    
    # 2. 기존 소송 추적
    log.info("")
    log.info("=" * 60)
    log.info("📋 UPDATE TRACKING JOB START")
    log.info("=" * 60)
    
    c.execute("SELECT * FROM lawsuits WHERE status = 'active'")
    active_lawsuits = c.fetchall()
    
    update_count = 0
    for lawsuit_row in active_lawsuits[:10]:  # 최대 10개만 추적
        lawsuit = {
            'case_name': lawsuit_row[1],
            'plaintiff': lawsuit_row[2],
            'defendant': lawsuit_row[3],
            'country': lawsuit_row[4]
        }
        
        update = claude_analyze_update(lawsuit)
        if update and update.get('has_update'):
            c.execute("""
                INSERT INTO updates 
                (lawsuit_id, update_type, description, updated_at)
                VALUES (?, ?, ?, datetime('now'))
            """, (
                lawsuit_row[0],
                update.get('update_type', ''),
                update.get('description', '')
            ))
            
            c.execute("""
                UPDATE lawsuits 
                SET status = ?, last_updated = datetime('now')
                WHERE id = ?
            """, (update.get('new_status', 'active'), lawsuit_row[0]))
            
            update_count += 1
            log.info(f"📌 Update recorded: {lawsuit['case_name']} - {update.get('update_type')}")
    
    conn.commit()
    conn.close()
    
    log.info(f"✅ UPDATE TRACKING DONE - {update_count} updates recorded")
    log.info("=" * 60)
    log.info("🎉 AI Lawsuit Monitor - Full Run Completed Successfully!")
    log.info("=" * 60)
    log.info("")

# ==================== 스케줄러 ====================

def main():
    """메인 함수 - 스케줄러 시작"""
    log.info("")
    log.info("╔" + "=" * 58 + "╗")
    log.info("║" + " " * 58 + "║")
    log.info("║" + "  🚀 AI Lawsuit Monitor Starting Up...".ljust(58) + "║")
    log.info("║" + " " * 58 + "║")
    log.info("╚" + "=" * 58 + "╝")
    log.info("")
    
    # 데이터베이스 초기화
    init_db()
    log.info("✅ Database initialized")
    log.info("")
    
    # 배포 시 즉시 첫 실행 (진행상황 확인용)
    if os.getenv("RUN_NOW") == "true" or os.getenv("FIRST_RUN") == "true":
        log.info("🔄 FIRST RUN DETECTED - Running immediately for deployment check...")
        log.info("")
        run_all()
        log.info("✅ First run completed! System is ready.")
        log.info("")
    
    # 스케줄 설정 (UTC 기준)
    # ⚠️ Render 서버는 UTC 시간대를 사용합니다
    # KST 08:00 = UTC 23:00 (전날 밤 11시)
    # KST 20:00 = UTC 11:00 (정오)
    log.info("🌍 Timezone Configuration:")
    log.info("   Render server uses UTC timezone")
    log.info("   KST 08:00 = UTC 23:00 (previous day, 11 PM)")
    log.info("   KST 20:00 = UTC 11:00 (11 AM)")
    log.info("")
    
    schedule.every().day.at("23:00").do(run_all)  # KST 08:00
    schedule.every().day.at("11:00").do(run_all)  # KST 20:00
    
    log.info("📅 Scheduled Runs:")
    log.info("   ⏰ Every day at 23:00 UTC → KST 08:00 (morning)")
    log.info("   ⏰ Every day at 11:00 UTC → KST 20:00 (evening)")
    log.info("")
    log.info("⏳ Scheduler ready. Waiting for scheduled times...")
    log.info("")
    
    # 스케줄러 실행
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main()
