#!/usr/bin/env python3
"""
AI Training Data Lawsuit Monitor
하루 2회 실행: 전세계 AI 학습데이터 관련 소송 모니터링
"""

import os
import json
import sqlite3
import hashlib
import logging
import smtplib
import requests
import schedule
import time
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("monitor.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ─── Config ──────────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
SERPER_API_KEY    = os.getenv("SERPER_API_KEY")       # https://serper.dev  (Google Search API)
NEWS_API_KEY      = os.getenv("NEWS_API_KEY")          # https://newsapi.org
EMAIL_FROM        = os.getenv("EMAIL_FROM")
EMAIL_PASSWORD    = os.getenv("EMAIL_PASSWORD")
EMAIL_TO          = os.getenv("EMAIL_TO")              # 쉼표 구분 복수 가능
TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID  = os.getenv("TELEGRAM_CHAT_ID")
DB_PATH           = os.getenv("DB_PATH", "lawsuits.db")

client = Anthropic(api_key=ANTHROPIC_API_KEY)

# ─── Search Queries (다국어) ──────────────────────────────────────────────────

DISCOVERY_QUERIES = [
    # English – broad
    "AI training data lawsuit filed 2024 2025",
    "artificial intelligence copyright infringement lawsuit training dataset",
    "generative AI lawsuit training data complaint filed",
    "LLM training data scraping lawsuit",
    "text-to-image model training data lawsuit",
    # English – jurisdiction
    "AI training data lawsuit California New York",
    "OpenAI Anthropic Google Meta training data lawsuit",
    "Stability AI Midjourney training data copyright lawsuit",
    # Korean
    "AI 학습데이터 저작권 소송",
    "생성형 AI 학습데이터 소송 제기",
    "인공지능 훈련 데이터 법적 분쟁",
    # Japanese
    "AI 学習データ 著作権 訴訟",
    "生成AI 学習データ 訴訟 提訴",
    # Chinese
    "人工智能 训练数据 版权 诉讼",
    "AI 训练数据 侵权 起诉",
    # European
    "AI training data lawsuit Germany France UK EU",
    "künstliche Intelligenz Trainingsdaten Klage",
    "intelligence artificielle données entraînement procès",
]

UPDATE_QUERIES_TEMPLATE = [
    '"{plaintiff}" v "{defendant}" AI lawsuit update ruling',
    '"{case_name}" court ruling decision AI training data',
    '"{case_name}" settlement dismissed appeal',
]

TRACKER_SOURCES = [
    "https://littlesisgoogle.com",           # placeholder
    "https://www.courtlistener.com",
    "https://storage.courtlistener.com",
    "https://www.pacer.gov",
    "https://www.judiciary.uk",
]

# ─── Database ────────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS lawsuits (
            id              TEXT PRIMARY KEY,
            discovered_at   TEXT,
            last_updated    TEXT,
            status          TEXT DEFAULT 'active',
            jurisdiction    TEXT,
            country         TEXT,
            court           TEXT,
            case_number     TEXT,
            case_name       TEXT,
            plaintiff       TEXT,
            defendant       TEXT,
            filed_date      TEXT,
            subject_data    TEXT,
            claims          TEXT,
            summary         TEXT,
            source_urls     TEXT,
            raw_snippets    TEXT
        );
        CREATE TABLE IF NOT EXISTS updates (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            lawsuit_id  TEXT,
            updated_at  TEXT,
            update_type TEXT,
            description TEXT,
            source_url  TEXT,
            FOREIGN KEY (lawsuit_id) REFERENCES lawsuits(id)
        );
        CREATE TABLE IF NOT EXISTS search_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            searched_at TEXT,
            query       TEXT,
            results_cnt INTEGER
        );
    """)
    conn.commit()
    conn.close()
    log.info("DB initialised: %s", DB_PATH)

def lawsuit_exists(lawsuit_id: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT 1 FROM lawsuits WHERE id=?", (lawsuit_id,)).fetchone()
    conn.close()
    return row is not None

def save_lawsuit(data: dict):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT OR REPLACE INTO lawsuits
        (id, discovered_at, last_updated, status, jurisdiction, country, court,
         case_number, case_name, plaintiff, defendant, filed_date,
         subject_data, claims, summary, source_urls, raw_snippets)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        data["id"], data.get("discovered_at", datetime.now().isoformat()),
        datetime.now().isoformat(), data.get("status", "active"),
        data.get("jurisdiction"), data.get("country"), data.get("court"),
        data.get("case_number"), data.get("case_name"),
        data.get("plaintiff"), data.get("defendant"), data.get("filed_date"),
        data.get("subject_data"), data.get("claims"), data.get("summary"),
        json.dumps(data.get("source_urls", []), ensure_ascii=False),
        json.dumps(data.get("raw_snippets", []), ensure_ascii=False),
    ))
    conn.commit()
    conn.close()

def save_update(lawsuit_id: str, update_type: str, description: str, source_url: str = ""):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        INSERT INTO updates (lawsuit_id, updated_at, update_type, description, source_url)
        VALUES (?,?,?,?,?)
    """, (lawsuit_id, datetime.now().isoformat(), update_type, description, source_url))
    conn.execute("UPDATE lawsuits SET last_updated=? WHERE id=?",
                 (datetime.now().isoformat(), lawsuit_id))
    conn.commit()
    conn.close()

def get_active_lawsuits():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT id, case_name, plaintiff, defendant, country, court, status
        FROM lawsuits WHERE status != 'closed'
    """).fetchall()
    conn.close()
    return [dict(zip(["id","case_name","plaintiff","defendant","country","court","status"], r))
            for r in rows]

# ─── Search ──────────────────────────────────────────────────────────────────

def serper_search(query: str, num: int = 10, search_type: str = "search") -> list[dict]:
    """Google Search via Serper.dev"""
    if not SERPER_API_KEY:
        log.warning("SERPER_API_KEY not set – skipping Google search")
        return []
    url = f"https://google.serper.dev/{search_type}"
    payload = {"q": query, "num": num, "gl": "us", "hl": "en"}
    headers = {"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        results = []
        for item in data.get("organic", []) + data.get("news", []):
            results.append({
                "title": item.get("title", ""),
                "url":   item.get("link", ""),
                "snippet": item.get("snippet", ""),
                "date": item.get("date", ""),
            })
        return results
    except Exception as e:
        log.error("Serper error [%s]: %s", query, e)
        return []

def newsapi_search(query: str, days_back: int = 3) -> list[dict]:
    """NewsAPI.org"""
    if not NEWS_API_KEY:
        return []
    from_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query, "from": from_date, "sortBy": "publishedAt",
        "language": "en", "pageSize": 20, "apiKey": NEWS_API_KEY,
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        articles = r.json().get("articles", [])
        return [{"title": a["title"], "url": a["url"],
                 "snippet": a.get("description",""), "date": a.get("publishedAt","")}
                for a in articles]
    except Exception as e:
        log.error("NewsAPI error: %s", e)
        return []

def fetch_page_text(url: str, max_chars: int = 8000) -> str:
    """Fetch and truncate raw page text"""
    try:
        r = requests.get(url, timeout=15,
                         headers={"User-Agent": "Mozilla/5.0 (AI Lawsuit Monitor)"})
        r.raise_for_status()
        from html.parser import HTMLParser
        class _P(HTMLParser):
            def __init__(self):
                super().__init__()
                self.texts = []
            def handle_data(self, d):
                if d.strip():
                    self.texts.append(d.strip())
        p = _P()
        p.feed(r.text)
        return " ".join(p.texts)[:max_chars]
    except Exception as e:
        log.debug("fetch_page_text(%s): %s", url, e)
        return ""

# ─── Claude Analysis ─────────────────────────────────────────────────────────

DISCOVERY_SYSTEM = """당신은 AI 학습데이터 관련 소송을 전문으로 분석하는 법률 인텔리전스 에이전트입니다.
주어진 검색 결과에서 AI 학습데이터(training data)와 직접 관련된 소송 사건을 식별하고,
각 소송의 핵심 정보를 추출하세요. 반드시 JSON 형식만 출력하세요.
"""

def claude_analyze_snippets(snippets: list[dict], full_texts: dict) -> list[dict]:
    """Claude로 검색결과에서 소송 식별 및 정보 추출"""
    combined = ""
    for i, s in enumerate(snippets[:30]):
        full = full_texts.get(s["url"], "")
        combined += f"\n\n--- Result {i+1} ---\nTitle: {s['title']}\nURL: {s['url']}\nDate: {s.get('date','')}\nSnippet: {s['snippet']}\n"
        if full:
            combined += f"Page text: {full[:3000]}\n"

    prompt = f"""다음 검색 결과에서 AI 학습데이터(training data) 관련 소송을 식별하세요.

{combined}

각 소송에 대해 아래 JSON 배열을 반환하세요. 소송이 없으면 빈 배열 [] 반환.
반드시 순수 JSON만, Markdown 코드블록 없이 출력:

[
  {{
    "case_name": "사건명 (예: Authors Guild v. OpenAI)",
    "plaintiff": "원고 (개인/단체명)",
    "defendant": "피고 (기업/개인)",
    "country": "국가 (US/KR/JP/CN/DE/FR/GB/EU/etc.)",
    "jurisdiction": "관할 (예: N.D. Cal., Seoul Central District Court)",
    "court": "법원명",
    "case_number": "사건번호 (있는 경우)",
    "filed_date": "제소일 (YYYY-MM-DD, 불명확시 추정 표시)",
    "subject_data": "소송 대상 데이터 (예: Common Crawl, GitHub Code, 뉴스기사 등)",
    "claims": "소송 원인/청구 (예: 저작권 침해, 부정경쟁행위, GDPR 위반 등)",
    "summary": "사건 요약 2~3문장 (한국어)",
    "source_urls": ["관련 URL 1", "관련 URL 2"],
    "is_new": true,
    "confidence": "high/medium/low"
  }}
]
"""
    try:
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            system=DISCOVERY_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as e:
        log.error("Claude analyze error: %s", e)
        return []

UPDATE_SYSTEM = """당신은 AI 소송 진행 상황을 추적하는 전문 에이전트입니다.
기존 소송에 대한 새로운 업데이트(판결, 합의, 기각, 항소 등)를 식별하세요. 반드시 JSON만 출력.
"""

def claude_analyze_update(lawsuit: dict, snippets: list[dict]) -> dict | None:
    """기존 소송의 업데이트 식별"""
    if not snippets:
        return None
    combined = "\n".join(
        f"[{s.get('date','')}] {s['title']}\n{s['snippet']}\n{s['url']}"
        for s in snippets[:10]
    )
    prompt = f"""기존 소송 정보:
Case: {lawsuit.get('case_name')}
Plaintiff: {lawsuit.get('plaintiff')}
Defendant: {lawsuit.get('defendant')}
Status: {lawsuit.get('status')}

검색 결과:
{combined}

이 소송의 새로운 진행 상황이 있으면 JSON으로 반환, 없으면 null:
{{
  "update_type": "판결/합의/기각/항소/증거제출/공판기일/기타",
  "description": "업데이트 내용 (한국어, 2~3문장)",
  "new_status": "active/settled/dismissed/appealed/closed",
  "source_url": "출처 URL",
  "is_significant": true/false
}}
"""
    try:
        msg = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=UPDATE_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text.strip()
        if raw.lower() == "null" or not raw:
            return None
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as e:
        log.error("Claude update error: %s", e)
        return None

# ─── Deduplication ───────────────────────────────────────────────────────────

def make_lawsuit_id(lawsuit: dict) -> str:
    key = f"{lawsuit.get('plaintiff','').lower().strip()}-{lawsuit.get('defendant','').lower().strip()}-{lawsuit.get('country','').lower()}"
    return hashlib.md5(key.encode()).hexdigest()[:12]

# ─── Notifications ───────────────────────────────────────────────────────────

def send_email(subject: str, html_body: str):
    if not EMAIL_FROM or not EMAIL_TO:
        log.warning("Email config missing – skipping email")
        return
    recipients = [e.strip() for e in EMAIL_TO.split(",")]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
            srv.login(EMAIL_FROM, EMAIL_PASSWORD)
            srv.sendmail(EMAIL_FROM, recipients, msg.as_string())
        log.info("Email sent: %s", subject)
    except Exception as e:
        log.error("Email error: %s", e)

def send_telegram(text: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram config missing – skipping")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text,
               "parse_mode": "HTML", "disable_web_page_preview": False}
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        log.info("Telegram sent")
    except Exception as e:
        log.error("Telegram error: %s", e)

def notify_new_lawsuit(lawsuit: dict):
    flag = {"US":"🇺🇸","KR":"🇰🇷","JP":"🇯🇵","CN":"🇨🇳","DE":"🇩🇪",
            "FR":"🇫🇷","GB":"🇬🇧","EU":"🇪🇺"}.get(lawsuit.get("country",""), "🌐")
    urls = lawsuit.get("source_urls", [])
    links_html = "".join(f'<li><a href="{u}">{u}</a></li>' for u in urls)
    links_tg   = "\n".join(f'• <a href="{u}">{u[:80]}</a>' for u in urls[:3])

    html = f"""
<html><body style="font-family:sans-serif;max-width:700px;margin:auto">
<h2 style="color:#c0392b">⚖️ 신규 AI 학습데이터 소송 감지 {flag}</h2>
<table border="1" cellpadding="8" cellspacing="0" style="border-collapse:collapse;width:100%">
  <tr><td width="150"><b>사건명</b></td><td>{lawsuit.get('case_name','')}</td></tr>
  <tr><td><b>원고</b></td><td>{lawsuit.get('plaintiff','')}</td></tr>
  <tr><td><b>피고</b></td><td>{lawsuit.get('defendant','')}</td></tr>
  <tr><td><b>관할/법원</b></td><td>{lawsuit.get('court','')} ({lawsuit.get('jurisdiction','')})</td></tr>
  <tr><td><b>국가</b></td><td>{flag} {lawsuit.get('country','')}</td></tr>
  <tr><td><b>제소일</b></td><td>{lawsuit.get('filed_date','')}</td></tr>
  <tr><td><b>대상 데이터</b></td><td>{lawsuit.get('subject_data','')}</td></tr>
  <tr><td><b>소송 원인</b></td><td>{lawsuit.get('claims','')}</td></tr>
  <tr><td><b>요약</b></td><td>{lawsuit.get('summary','')}</td></tr>
  <tr><td><b>출처</b></td><td><ul>{links_html}</ul></td></tr>
</table>
<p style="color:#7f8c8d;font-size:12px">AI Lawsuit Monitor • {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
</body></html>"""

    tg = f"""⚖️ <b>신규 AI 학습데이터 소송</b> {flag}

<b>사건:</b> {lawsuit.get('case_name','')}
<b>원고:</b> {lawsuit.get('plaintiff','')}
<b>피고:</b> {lawsuit.get('defendant','')}
<b>법원:</b> {lawsuit.get('court','')}
<b>국가:</b> {lawsuit.get('country','')}
<b>제소일:</b> {lawsuit.get('filed_date','')}
<b>대상 데이터:</b> {lawsuit.get('subject_data','')}
<b>소송 원인:</b> {lawsuit.get('claims','')}

📝 {lawsuit.get('summary','')}

🔗 출처:
{links_tg}"""

    send_email(f"[AI소송] 신규 감지: {lawsuit.get('case_name','')}", html)
    send_telegram(tg)

def notify_update(lawsuit: dict, update: dict):
    flag = {"US":"🇺🇸","KR":"🇰🇷","JP":"🇯🇵","CN":"🇨🇳","DE":"🇩🇪",
            "FR":"🇫🇷","GB":"🇬🇧","EU":"🇪🇺"}.get(lawsuit.get("country",""), "🌐")
    html = f"""
<html><body style="font-family:sans-serif;max-width:700px;margin:auto">
<h2 style="color:#2980b9">🔄 소송 업데이트 {flag}</h2>
<table border="1" cellpadding="8" cellspacing="0" style="border-collapse:collapse;width:100%">
  <tr><td width="150"><b>사건명</b></td><td>{lawsuit.get('case_name','')}</td></tr>
  <tr><td><b>업데이트 유형</b></td><td>{update.get('update_type','')}</td></tr>
  <tr><td><b>내용</b></td><td>{update.get('description','')}</td></tr>
  <tr><td><b>새 상태</b></td><td>{update.get('new_status','')}</td></tr>
  <tr><td><b>출처</b></td><td><a href="{update.get('source_url','')}">링크</a></td></tr>
</table>
<p style="color:#7f8c8d;font-size:12px">AI Lawsuit Monitor • {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
</body></html>"""

    tg = f"""🔄 <b>소송 업데이트</b> {flag}

<b>사건:</b> {lawsuit.get('case_name','')}
<b>유형:</b> {update.get('update_type','')}
<b>내용:</b> {update.get('description','')}
<b>상태:</b> {update.get('new_status','')}
🔗 <a href="{update.get('source_url','')}">출처</a>"""

    send_email(f"[AI소송] 업데이트: {lawsuit.get('case_name','')}", html)
    send_telegram(tg)

# ─── Core Jobs ───────────────────────────────────────────────────────────────

def job_discover():
    """신규 소송 탐색 (하루 2회)"""
    log.info("=== DISCOVERY JOB START ===")
    all_snippets: list[dict] = []

    for query in DISCOVERY_QUERIES:
        results = serper_search(query, num=10, search_type="news")
        if not results:
            results = serper_search(query, num=10, search_type="search")
        results += newsapi_search(query, days_back=4)
        all_snippets.extend(results)
        log.info("Query '%s' → %d results", query[:50], len(results))

    # Deduplicate by URL
    seen_urls = set()
    unique = []
    for s in all_snippets:
        if s["url"] not in seen_urls:
            seen_urls.add(s["url"])
            unique.append(s)
    log.info("Total unique snippets: %d", len(unique))

    # Fetch full text for top candidates
    full_texts = {}
    for s in unique[:20]:
        if any(kw in (s["title"]+s["snippet"]).lower()
               for kw in ["lawsuit","suit","complaint","litigation","소송","訴訟","诉讼","klage","procès"]):
            full_texts[s["url"]] = fetch_page_text(s["url"])

    # Claude analysis
    lawsuits = claude_analyze_snippets(unique, full_texts)
    log.info("Claude identified %d lawsuits", len(lawsuits))

    new_count = 0
    for l in lawsuits:
        if l.get("confidence") == "low":
            continue
        l["id"] = make_lawsuit_id(l)
        l["discovered_at"] = datetime.now().isoformat()
        if not lawsuit_exists(l["id"]):
            save_lawsuit(l)
            notify_new_lawsuit(l)
            new_count += 1
            log.info("NEW lawsuit saved: %s", l.get("case_name"))
        else:
            log.debug("Already known: %s", l.get("case_name"))

    log.info("=== DISCOVERY DONE — %d new lawsuits ===", new_count)

def job_track_updates():
    """기존 소송 업데이트 추적 (하루 2회)"""
    log.info("=== UPDATE TRACKING JOB START ===")
    active = get_active_lawsuits()
    log.info("Tracking %d active lawsuits", len(active))

    for lawsuit in active:
        queries = [
            f'"{lawsuit["case_name"]}" ruling decision settlement',
            f'{lawsuit.get("plaintiff","")} v {lawsuit.get("defendant","")} lawsuit update',
        ]
        snippets = []
        for q in queries:
            snippets += serper_search(q, num=5, search_type="news")
            snippets += newsapi_search(q, days_back=4)

        update = claude_analyze_update(lawsuit, snippets)
        if update and update.get("is_significant"):
            save_update(lawsuit["id"], update["update_type"],
                        update["description"], update.get("source_url",""))
            # Update status if changed
            if update.get("new_status") and update["new_status"] != lawsuit["status"]:
                conn = sqlite3.connect(DB_PATH)
                conn.execute("UPDATE lawsuits SET status=? WHERE id=?",
                             (update["new_status"], lawsuit["id"]))
                conn.commit()
                conn.close()
            notify_update(lawsuit, update)
            log.info("Update saved for: %s", lawsuit["case_name"])

    log.info("=== UPDATE TRACKING DONE ===")

def run_all():
    job_discover()
    job_track_updates()

# ─── Scheduler ───────────────────────────────────────────────────────────────

def main():
    init_db()
    log.info("AI Lawsuit Monitor started")
    log.info("Schedule: 08:00 and 20:00 KST daily")

    # 즉시 1회 실행 (선택)
    if os.getenv("RUN_NOW", "false").lower() == "true":
        run_all()

    schedule.every().day.at("08:00").do(run_all)
    schedule.every().day.at("20:00").do(run_all)

    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    main()
