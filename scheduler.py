"""
스케줄러 - Flask와 완전히 분리된 별도 프로세스
매일 UTC 23:00 (KST 08:00), UTC 11:00 (KST 20:00)에 실행
"""

import os
import time
import logging
import schedule
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger(__name__)


def run_monitor_job():
    """monitor.py의 run_all() 실행"""
    try:
        log.info("🔔 Scheduled job triggered!")
        from monitor import run_all
        run_all()
        log.info("✅ Scheduled job completed!")
    except Exception as e:
        log.error(f"❌ Scheduled job error: {e}", exc_info=True)


def main():
    log.info("")
    log.info("╔" + "=" * 58 + "╗")
    log.info("║" + "  ⏰ Scheduler Process Starting...".ljust(58) + "║")
    log.info("╚" + "=" * 58 + "╝")
    log.info("")

    # DB 초기화
    log.info("🗄️ Initializing database...")
    from monitor import init_db
    init_db()
    log.info("✅ Database initialized")
    log.info("")

    # 배포 시 즉시 첫 실행
    if os.getenv("FIRST_RUN") == "true" or os.getenv("RUN_NOW") == "true":
        log.info("🔄 FIRST RUN DETECTED - Running immediately...")
        log.info("")
        run_monitor_job()
        log.info("✅ First run completed!")
        log.info("")

    # 스케줄 설정 (UTC 기준)
    # KST 08:00 = UTC 23:00
    # KST 20:00 = UTC 11:00
    schedule.every().day.at("23:00").do(run_monitor_job)
    schedule.every().day.at("11:00").do(run_monitor_job)

    log.info("🌍 Timezone: UTC (Render server)")
    log.info("📅 Scheduled runs:")
    log.info("   ⏰ UTC 23:00 → KST 08:00 (morning)")
    log.info("   ⏰ UTC 11:00 → KST 20:00 (evening)")
    log.info("")

    next_run = schedule.next_run()
    log.info(f"⏳ Next run at: {next_run} UTC")
    log.info("")
    log.info("🟢 Scheduler is running. Waiting...")
    log.info("")

    while True:
        try:
            schedule.run_pending()
            time.sleep(30)
        except Exception as e:
            log.error(f"Scheduler loop error: {e}", exc_info=True)
            time.sleep(30)


if __name__ == "__main__":
    main()
