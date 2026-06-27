"""
AI 학습데이터 소송 모니터링 시스템 - 메인 에이전트
매일 UTC 23:00, 11:00에 자동 실행 (KST 08:00, 20:00)
배포 시 환경변수 FIRST_RUN=true로 즉시 실행 가능
텔레그램 알림에 관련 기사 URL과 발행일 정보 포함
한 번 검색된 기사는 아카이빙하여 중복 검색 방지
"""

import os
import time
import json
import sqlite3
import hashlib
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

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
SERPER_API_KEY = os.getenv("SERPER_API_KEY")
NEWS_API_KEY = os.getenv("NEWS_API_KEY")
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_TO = os.getenv("EMAIL_TO")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DB_PATH = os.getenv("DB_PATH", "lawsuits.db")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger(__name__)

# ==================== 검색 쿼리 ====================

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
    "Getty Images AI lawsuit",
    "artists AI art lawsuit copyright",

    # 영어 (음악/미디어)
    "music labels AI training data lawsuit",
    "AI copyright infringement training lawsuit",
    "writers AI training data class action",
    "AI voice cloning lawsuit",
    "AI image generation lawsuit",

    # 미국 (주별)
    "California AI lawsuit training data",
    "New York AI regulation lawsuit",
    "Texas AI lawsuit",
    "AI chatbot copyright lawsuit",
    "machine learning dataset lawsuit",

    # 한국어
    "AI 학습데이터 저작권 소송",
    "생성형 AI 학습데이터 소송",
    "AI 학습 데이터 저작권 침해 소송",
    "AI 저작권 침해 집단소송",
    "인공지능 학습 저작물 소송",

    # 일본어
    "AI 学習データ 著作権 訴訟",
    "生成型AI 訴訟 学習データ",
    "AI 著作権 侵害 集団訴訟",
    "人工知能 学習データ 訴訟",

    # 중국어
    "人工智能 训练数据 版权 诉讼",
    "生成型AI 诉讼",

    # 유럽
    "GDPR AI lawsuit training data",
    "EU AI Act lawsuit",
    "Germany AI copyright lawsuit",
    "France AI training data lawsuit",
    "UK AI copyright lawsuit",

    # 기타 국가
    "Australia AI training data lawsuit",
    "Canada AI copyright lawsuit",
    "India AI lawsuit training",
    "Japan AI copyright lawsuit",
    "Korea AI training data lawsuit",
]

# ==================== 데이터베이스 ====================

def init_db():
    """데이터베이스 초기화"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 소송 테이블
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
        published_date TEXT,
        raw_snippets TEXT,
        discovered_at TIMESTAMP,
        last_updated TIMESTAMP
    )''')

    # 업데이트 테이블
    c.execute('''CREATE TABLE IF NOT EXISTS updates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lawsuit_id TEXT,
        update_type TEXT,
        description TEXT,
        source_url TEXT,
        updated_at TIMESTAMP,
        FOREIGN KEY(lawsuit_id) REFERENCES lawsuits(id)
    )''')

    # 검색 로그 테이블
    c.execute('''CREATE TABLE IF NOT EXISTS search_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        query TEXT,
        results_cnt INTEGER,
        searched_at TIMESTAMP
    )''')

    # ✅ 아카이브 테이블 (한 번 본 기사 저장)
    c.execute('''CREATE TABLE IF NOT EXISTS seen_articles (
        url_hash TEXT PRIMARY KEY,
        url TEXT,
        title TEXT,
        source TEXT,
        first_seen_at TIMESTAMP
    )''')

    conn.commit()
    conn.close()
    log.info("✅ Database initialized (seen_articles archive table ready)")

# ==================== 아카이브 함수 ====================

def make_url_hash(url: str) -> str:
    """URL의 MD5 해시 생성"""
    return hashlib.md5(url.strip().encode()).hexdigest()

def is_seen(url: str) -> bool:
    """이미 본 기사인지 확인"""
    if not url:
        return False
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM seen_articles WHERE url_hash = ?", (make_url_hash(url),))
    result = c.fetchone() is not None
    conn.close()
    return result

def archive_articles(articles: list[dict]):
    """기사 목록을 아카이브에 저장"""
    if not articles:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    saved = 0
    for article in articles:
        url = article.get("link", "")
        if not url:
            continue
        url_hash = make_url_hash(url)
        try:
            c.execute("""
                INSERT OR IGNORE INTO seen_articles
                (url_hash, url, title, source, first_seen_at)
                VALUES (?, ?, ?, ?, datetime('now'))
            """, (
                url_hash,
                url,
                article.get("title", ""),
                article.get("source", "")
            ))
            if c.rowcount > 0:
                saved += 1
        except Exception as e:
            log.warning(f"Archive insert error: {e}")
    conn.commit()
    conn.close()
    log.info(f"📦 Archived {saved} new articles (skipped duplicates)")

def filter_new_articles(articles: list[dict]) -> list[dict]:
    """이미 본 기사를 제외하고 새 기사만 반환"""
    if not articles:
        return []
    new_articles = []
    skipped = 0
    for article in articles:
        url = article.get("link", "")
        if url and is_seen(url):
            skipped += 1
        else:
            new_articles.append(article)
    log.info(f"🔍 Articles: {len(articles)} total → {len(new_articles)} new, {skipped} already seen (skipped)")
    return new_articles

def get_archive_stats() -> dict:
    """아카이브 통계 반환"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM seen_articles")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM seen_articles WHERE first_seen_at >= datetime('now', '-7 days')")
    last_week = c.fetchone()[0]
    conn.close()
    return {"total_archived": total, "archived_last_7_days": last_week}

# ==================== API 호출 ====================

def serper_search(query: str, max_results: int = 10, page: int = 1) -> list[dict]:
    """Serper.dev를 사용한 Google 검색"""
    try:
        url = "https://google.serper.dev/search"
        headers = {
            "X-API-KEY": SERPER_API_KEY,
            "Content-Type": "application/json"
        }
        payload = {"q": query, "num": max_results, "type": "news", "page": page}
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        results = []
        for item in response.json().get("news", [])[:max_results]:
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

def newsapi_search(query: str, max_results: int = 10, page: int = 1) -> list[dict]:
    """NewsAPI를 사용한 뉴스 검색"""
    try:
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": query,
            "pageSize": max_results,
            "page": page,
            "sortBy": "publishedAt",
            "apiKey": NEWS_API_KEY
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        results = []
        for article in response.json().get("articles", [])[:max_results]:
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

# ==================== Claude 분석 ====================

def claude_analyze_snippets(snippets: list[dict], full_texts: dict) -> list[dict]:
    """Claude로 검색결과에서 소송 식별 및 정보 추출"""
    try:
        client = Anthropic(api_key=ANTHROPIC_API_KEY)

        snippets_text = "\n".join([
            f"- {s['title']}\n  {s['snippet']}\n  출처: {s['source']}\n  URL: {s['link']}"
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
            "source_urls": "관련 기사 URL들 (쉼표로 구분)",
            "published_date": "기사 발행일 (YYYY-MM-DD HH:MM 형식)",
            "confidence": "신뢰도 (high/medium/low)"
        }}
    ]
}}

JSON만 응답하세요. source_urls와 published_date는 스니펫에서 찾을 수 있으면 포함하세요."""

        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )

        try:
            import re
            response_text = message.content[0].text
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return data.get("lawsuits", [])
        except Exception:
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
            model="claude-sonnet-4-6",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )

        try:
            import re
            response_text = message.content[0].text
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception:
            pass

        return None
    except Exception as e:
        log.error(f"Claude update analysis error: {e}")
        return None

# ==================== ID 생성 ====================

def make_lawsuit_id(plaintiff: str, defendant: str, country: str) -> str:
    """소송 고유 ID 생성"""
    key = f"{plaintiff}_{defendant}_{country}".lower()
    return hashlib.md5(key.encode()).hexdigest()

# ==================== 알림 ====================

def notify_new_lawsuit(lawsuit: dict):
    """신규 소송 텔레그램 알림"""
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        try:
            source_urls = lawsuit.get('source_urls', '')
            if isinstance(source_urls, str) and source_urls:
                source_list = source_urls.split(',')[:3]
                sources_text = "\n".join([f"🔗 {url.strip()}" for url in source_list])
            else:
                sources_text = "🔗 출처 정보 없음"

            published_date = lawsuit.get('published_date', '')
            date_info = f"📅 발행일: {published_date}" if published_date else "📅 발행일: 미정"

            text = f"""
⚖️ <b>신규 AI 학습데이터 소송 감지</b>

<b>사건명:</b> {lawsuit.get('case_name', 'N/A')}
<b>원고:</b> {lawsuit.get('plaintiff', 'N/A')}
<b>피고:</b> {lawsuit.get('defendant', 'N/A')}
<b>법원:</b> {lawsuit.get('jurisdiction', 'N/A')}
<b>제소일:</b> {lawsuit.get('filed_date', 'N/A')}

<b>📝 요약:</b>
{lawsuit.get('summary', 'N/A')}

<b>📚 대상 데이터:</b>
{lawsuit.get('subject_data', 'N/A')}

<b>⚠️ 청구 사항:</b>
{lawsuit.get('claims', 'N/A')}

<b>📰 관련 기사:</b>
{sources_text}

{date_info}

🕐 감지 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S KST')}
            """
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(
                url,
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": text,
                    "parse_mode": "HTML"
                }
            )
            log.info(f"📱 Telegram sent for: {lawsuit['case_name']}")
        except Exception as e:
            log.error(f"Telegram notification error: {e}")

# ==================== 주 작업 ====================

def run_all():
    """신규 소송 탐지 + 기존 소송 추적"""
    log.info("=" * 60)
    log.info("🔍 AI Lawsuit Monitor - Full Run Started")
    log.info("=" * 60)

    # 아카이브 통계 출력
    stats = get_archive_stats()
    log.info(f"📦 Archive stats: {stats['total_archived']} total articles seen, "
             f"{stats['archived_last_7_days']} in last 7 days")

    # 1. 신규 소송 탐지
    log.info("")
    log.info("=" * 60)
    log.info("🌐 DISCOVERY JOB START - Searching for new lawsuits")
    log.info("=" * 60)

    all_raw_snippets = []

    # 1차 검색 (쿼리 15개)
    log.info("🔎 Round 1: Primary search (15 queries)")
    for i, query in enumerate(DISCOVERY_QUERIES[:15]):
        log.info(f"   🔎 [{i+1}/15] {query}")
        serper_results = serper_search(query, max_results=5)
        newsapi_results = newsapi_search(query, max_results=5)
        all_raw_snippets.extend(serper_results)
        all_raw_snippets.extend(newsapi_results)

    log.info(f"📊 Round 1 collected: {len(all_raw_snippets)} snippets")

    # 새 기사만 필터링 (이미 본 기사 제외)
    new_snippets = filter_new_articles(all_raw_snippets)
    duplicates = len(all_raw_snippets) - len(new_snippets)

    # ✅ 중복 개수만큼 추가 검색 (A: 나머지 쿼리 + B: 페이지 넘기기)
    if duplicates > 0:
        log.info("")
        log.info(f"🔄 Round 2: Retry search for {duplicates} duplicate(s) skipped")

        extra_snippets = []
        collected_extra = 0

        # A: 나머지 쿼리(16번~) 로 추가 검색
        remaining_queries = DISCOVERY_QUERIES[15:]
        if remaining_queries:
            log.info(f"   📋 Strategy A: Searching {len(remaining_queries)} remaining queries")
            for j, query in enumerate(remaining_queries):
                if collected_extra >= duplicates:
                    break
                log.info(f"   🔎 [A-{j+1}] {query}")
                serper_results = serper_search(query, max_results=5)
                newsapi_results = newsapi_search(query, max_results=5)
                batch = serper_results + newsapi_results
                extra_snippets.extend(batch)
                collected_extra += len(batch)

        # B: 여전히 부족하면 기존 쿼리를 page=2로 재검색
        if collected_extra < duplicates:
            still_needed = duplicates - collected_extra
            log.info(f"   📋 Strategy B: Page 2 search for {still_needed} more (still needed)")
            for k, query in enumerate(DISCOVERY_QUERIES[:15]):
                if collected_extra >= duplicates:
                    break
                log.info(f"   🔎 [B-{k+1}] {query} (page 2)")
                serper_results = serper_search(query, max_results=5, page=2)
                newsapi_results = newsapi_search(query, max_results=5, page=2)
                batch = serper_results + newsapi_results
                extra_snippets.extend(batch)
                collected_extra += len(batch)

        new_extra = filter_new_articles(extra_snippets)
        log.info(f"📊 Round 2 collected: {len(extra_snippets)} snippets → {len(new_extra)} new")

        new_snippets.extend(new_extra)
        all_raw_snippets.extend(extra_snippets)
        log.info(f"📊 Total new snippets after retry: {len(new_snippets)}")
    else:
        log.info(f"✅ No retry needed (0 duplicates)")

    if not new_snippets:
        log.info("✅ No new articles found (all already archived). Skipping Claude analysis.")
    else:
        # ✅ 새 기사만 아카이브에 저장
        archive_articles(new_snippets)

        # Claude 분석 (새 기사만)
        log.info(f"🤖 Claude analyzing {len(new_snippets)} new snippets...")
        lawsuits = claude_analyze_snippets(new_snippets, {})
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

            c.execute("SELECT id FROM lawsuits WHERE id = ?", (lawsuit_id,))
            if not c.fetchone():
                c.execute("""
                    INSERT INTO lawsuits
                    (id, case_name, plaintiff, defendant, country, jurisdiction,
                     filed_date, subject_data, claims, summary, status, source_urls,
                     published_date, discovered_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
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
                    'active',
                    lawsuit.get('source_urls', ''),
                    lawsuit.get('published_date', '')
                ))
                new_count += 1
                notify_new_lawsuit(lawsuit)
                log.info(f"💾 New lawsuit saved: {lawsuit.get('case_name')}")

        conn.commit()
        conn.close()
        log.info(f"🎯 DISCOVERY DONE - {new_count} new lawsuits saved")

    # 2. 기존 소송 추적
    log.info("")
    log.info("=" * 60)
    log.info("📋 UPDATE TRACKING JOB START")
    log.info("=" * 60)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM lawsuits WHERE status = 'active'")
    active_lawsuits = c.fetchall()

    update_count = 0
    for lawsuit_row in active_lawsuits[:10]:
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

    init_db()
    log.info("")

    # 배포 시 즉시 첫 실행
    if os.getenv("RUN_NOW") == "true" or os.getenv("FIRST_RUN") == "true":
        log.info("🔄 FIRST RUN DETECTED - Running immediately for deployment check...")
        log.info("")
        run_all()
        log.info("✅ First run completed! System is ready.")
        log.info("")

    # 스케줄 설정 (UTC 기준)
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

    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main()
