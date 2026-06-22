# ⚖️ AI 학습데이터 소송 모니터

전세계 AI 학습데이터 관련 소송을 자동으로 탐지·추적하고,  
이메일/텔레그램으로 알림을 보내며, 웹 대시보드로 관리하는 시스템입니다.

---

## 📁 파일 구조

```
ai_lawsuit_monitor/
├── monitor.py        # 메인 모니터링 에이전트 (스케줄러 + 탐지 + 분석)
├── dashboard.py      # 웹 대시보드 (Flask)
├── requirements.txt  # Python 패키지 목록
├── .env.example      # 환경변수 템플릿
└── README.md
```

---

## ⚙️ 설치 방법

### 1. Python 환경 준비

```bash
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 환경변수 설정

```bash
cp .env.example .env
# .env 파일 열어서 API 키 등 입력
```

**필요한 API 키:**

| 서비스 | 용도 | 무료 한도 | 가입 링크 |
|--------|------|-----------|-----------|
| Anthropic | 소송 분석 (Claude) | 유료 | https://console.anthropic.com |
| Serper.dev | Google 검색 | 2,500회/월 무료 | https://serper.dev |
| NewsAPI.org | 뉴스 검색 | 100회/일 무료 | https://newsapi.org |
| Gmail 앱 비밀번호 | 이메일 알림 | 무료 | https://myaccount.google.com/apppasswords |
| Telegram Bot | 텔레그램 알림 | 무료 | @BotFather |

### 3. 텔레그램 봇 설정 방법

1. Telegram에서 `@BotFather` 검색 → `/newbot` 명령 → 봇 이름/username 설정
2. 발급된 **Token** 을 `.env` 의 `TELEGRAM_TOKEN` 에 입력
3. 봇에게 아무 메시지나 보낸 후 아래 URL 접속:
   ```
   https://api.telegram.org/bot{YOUR_TOKEN}/getUpdates
   ```
4. 응답에서 `"chat": {"id": 123456789}` 값을 `TELEGRAM_CHAT_ID` 에 입력

---

## 🚀 실행 방법

### 모니터 에이전트 (백그라운드 스케줄러)

```bash
# 일반 실행 (매일 08:00, 20:00 KST 자동 실행)
python monitor.py

# 시작 즉시 1회 실행 후 스케줄 유지
RUN_NOW=true python monitor.py

# 백그라운드 실행 (nohup)
nohup python monitor.py > monitor.log 2>&1 &

# systemd 서비스로 등록 (권장, 아래 섹션 참조)
```

### 웹 대시보드

```bash
python dashboard.py
# → http://localhost:5000 접속
```

---

## 🖥️ 서버 배포 (systemd, Linux)

`/etc/systemd/system/ai-lawsuit-monitor.service` 생성:

```ini
[Unit]
Description=AI Lawsuit Monitor
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/ai_lawsuit_monitor
ExecStart=/home/ubuntu/ai_lawsuit_monitor/venv/bin/python monitor.py
Restart=always
RestartSec=60

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable ai-lawsuit-monitor
sudo systemctl start ai-lawsuit-monitor
sudo systemctl status ai-lawsuit-monitor
```

---

## ☁️ 클라우드 배포 옵션 비교

| 옵션 | 비용 | 난이도 | 권장 |
|------|------|--------|------|
| **개인 PC / NAS** | 무료 | ⭐ | 테스트용 |
| **AWS EC2 t3.micro** | ~$8/월 | ⭐⭐ | 소규모 운영 |
| **Google Cloud Run** | 종량제 | ⭐⭐⭐ | 스케일업 |
| **Railway.app** | $5/월 | ⭐ | 가장 간단 |
| **Render.com** | 무료~$7/월 | ⭐ | 간단 |

**Railway 배포 (가장 빠름):**
```bash
npm install -g @railway/cli
railway login
railway init
railway up
```

---

## 📊 모니터링 대상 국가 및 소스

### 검색 소스
- **Google 뉴스/웹** (Serper.dev)
- **NewsAPI** (전세계 뉴스)
- **CourtListener** (미국 연방법원 PACER 공개 자료)
- **법원 판결 텍스트** (직접 크롤링)

### 모니터링 국가
| 지역 | 국가 | 검색 언어 |
|------|------|-----------|
| 북미 | 🇺🇸 미국 (각 주) | 영어 |
| 동아시아 | 🇰🇷 한국 | 한국어 |
| 동아시아 | 🇯🇵 일본 | 일본어 |
| 동아시아 | 🇨🇳 중국 | 중국어 |
| 유럽 | 🇩🇪 독일 | 독일어 |
| 유럽 | 🇫🇷 프랑스 | 프랑스어 |
| 유럽 | 🇬🇧 영국 | 영어 |
| 유럽 | 🇪🇺 EU | 영어/다국어 |

---

## 🔧 커스터마이징

### 검색 쿼리 추가
`monitor.py` 의 `DISCOVERY_QUERIES` 리스트에 추가:
```python
DISCOVERY_QUERIES = [
    ...
    "새로운 검색어",
]
```

### 실행 시간 변경
```python
schedule.every().day.at("07:00").do(run_all)   # 오전 7시
schedule.every().day.at("19:00").do(run_all)   # 오후 7시
```

### 알림 채널 추가 (Slack 예시)
`monitor.py` 의 `notify_new_lawsuit()` 에 추가:
```python
def send_slack(text: str):
    requests.post(SLACK_WEBHOOK_URL, json={"text": text})
```

---

## 🗄️ 데이터베이스 구조

```sql
-- 소송 테이블
lawsuits (id, case_name, plaintiff, defendant, country, court,
          jurisdiction, case_number, filed_date, subject_data,
          claims, summary, status, source_urls, discovered_at, last_updated)

-- 업데이트 이력
updates (lawsuit_id, update_type, description, source_url, updated_at)

-- 검색 로그
search_log (query, results_cnt, searched_at)
```

SQLite 직접 조회:
```bash
sqlite3 lawsuits.db
> SELECT case_name, country, status FROM lawsuits;
> SELECT * FROM updates ORDER BY updated_at DESC LIMIT 10;
```

---

## ❓ 자주 묻는 질문

**Q: 알림이 안 와요**
- Gmail의 경우 "앱 비밀번호" (16자리) 사용 필요. 일반 비밀번호 불가
- Telegram: 봇에 먼저 메시지를 보내야 chat_id 확인 가능

**Q: 같은 소송이 중복 감지돼요**
- `make_lawsuit_id()` 함수가 원고+피고+국가 조합으로 중복을 막음
- 같은 사건이 다른 이름으로 검색될 경우 Claude가 통합 분석 예정 (v2)

**Q: 한국 소송이 잘 안 잡혀요**
- 한국 법원은 공개 API 없음. 법률신문, 연합뉴스, 로앤비 등 뉴스 소스 의존
- `DISCOVERY_QUERIES`에 "법률신문 AI 소송" 등 추가 권장

**Q: API 비용은 얼마나 드나요?**
- Claude API: 하루 2회 × 30쿼리 ≈ 약 $0.5~1/일 (Sonnet 기준)
- Serper: 무료 플랜(2,500회/월)으로 충분
- NewsAPI: 무료 플랜(100회/일)으로 충분
