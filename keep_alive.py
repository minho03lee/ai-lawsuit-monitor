"""
Keep-Alive 서버 및 스케줄러
Render 무료 플랜에서 서비스가 자동 정지되지 않도록 HTTP 서버 실행
동시에 monitor.py의 스케줄러를 별도 스레드에서 실행
"""

import os
import sys
import threading
import time
import logging
from datetime import datetime
from flask import Flask
import schedule

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger(__name__)

# Flask 앱 생성
app = Flask(__name__)

# 스케줄러 전역 변수
scheduler_job = None
last_run = {}

# ==================== Flask 라우트 ====================

@app.route("/", methods=["GET", "HEAD"])
def health():
    """헬스 체크"""
    return {"status": "running", "timestamp": datetime.now().isoformat()}, 200

@app.route("/ping", methods=["GET"])
def ping():
    """Keep-alive 핑"""
    return "pong", 200

@app.route("/health", methods=["GET"])
def health_detailed():
    """상세 헬스 체크"""
    return {
        "status": "running",
        "scheduler": "active",
        "timestamp": datetime.now().isoformat(),
        "last_run": last_run
    }, 200

# ==================== 스케줄러 작업 ====================

def run_monitor_job():
    """monitor.py의 run_all() 함수 호출"""
    global last_run
    
    try:
        log.info("🔔 Scheduled job triggered!")
        
        # monitor.py 임포트
        from monitor import run_all
        
        # 작업 실행
        run_all()
        
        # 마지막 실행 시간 기록
        last_run = {"timestamp": datetime.now().isoformat(), "status": "success"}
        
    except Exception as e:
        log.error(f"❌ Scheduled job error: {e}", exc_info=True)
        last_run = {"timestamp": datetime.now().isoformat(), "status": "error", "error": str(e)}

def scheduler_thread():
    """스케줄러를 별도 스레드에서 실행"""
    log.info("")
    log.info("=" * 60)
    log.info("🌍 Scheduler Thread Started")
    log.info("=" * 60)
    log.info("⏰ Configured run times (UTC):")
    log.info("   - Every day at 23:00 UTC (KST 08:00)")
    log.info("   - Every day at 11:00 UTC (KST 20:00)")
    log.info("=" * 60)
    log.info("")
    
    # 스케줄 설정
    schedule.every().day.at("23:00").do(run_monitor_job)
    schedule.every().day.at("11:00").do(run_monitor_job)
    
    # 스케줄러 무한 루프 (블로킹 없이)
    while True:
        try:
            schedule.run_pending()
            time.sleep(60)  # 1분마다 확인
        except Exception as e:
            log.error(f"Scheduler loop error: {e}", exc_info=True)
            time.sleep(60)

# ==================== 메인 ====================

def main():
    """메인 함수"""
    log.info("")
    log.info("╔" + "=" * 58 + "╗")
    log.info("║" + " " * 58 + "║")
    log.info("║" + "  🚀 Keep-Alive Server Starting...".ljust(58) + "║")
    log.info("║" + " " * 58 + "║")
    log.info("╚" + "=" * 58 + "╝")
    log.info("")
    
    # 스케줄러 스레드 시작
    log.info("📌 Starting scheduler thread...")
    scheduler = threading.Thread(target=scheduler_thread, daemon=True)
    scheduler.start()
    log.info("✅ Scheduler thread started")
    log.info("")
    
    # Flask 서버 시작
    log.info("🌐 Starting Flask server on port 5000...")
    log.info("   Health check: GET / or /health")
    log.info("   Ping: GET /ping")
    log.info("")
    
    # Render 포트 감지
    port = int(os.getenv("PORT", 5000))
    
    try:
        app.run(
            host="0.0.0.0",
            port=port,
            debug=False,
            threaded=True,
            use_reloader=False
        )
    except KeyboardInterrupt:
        log.info("Shutting down...")
        sys.exit(0)

if __name__ == "__main__":
    main()
