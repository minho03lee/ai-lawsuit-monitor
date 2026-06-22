#!/usr/bin/env python3
"""
Render 무료 플랜 자동 정지 방지용 간단한 HTTP 서버
monitor.py와 병렬 실행

구조:
- monitor.py: 스케줄 작동 (백그라운드)
- keep_alive.py: HTTP 응답 (포트 5000, 15분마다 ping)
"""

import os
import time
from flask import Flask
from threading import Thread

# monitor.py와 동시 실행
def run_monitor():
    import subprocess
    subprocess.run(["python", "monitor.py"])

app = Flask(__name__)

@app.route("/ping")
def ping():
    """Keep-alive 엔드포인트"""
    return {"status": "alive", "timestamp": time.time()}, 200

@app.route("/health")
def health():
    """Health check"""
    import sqlite3
    db_path = os.getenv("DB_PATH", "lawsuits.db")
    try:
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            count = conn.execute("SELECT COUNT(*) FROM lawsuits").fetchone()[0]
            conn.close()
            return {
                "status": "healthy",
                "database": "ok",
                "total_lawsuits": count
            }, 200
        else:
            return {"status": "initializing"}, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

if __name__ == "__main__":
    # 백그라운드에서 monitor.py 실행
    monitor_thread = Thread(target=run_monitor, daemon=True)
    monitor_thread.start()
    
    # Flask 실행 (포트 5000)
    app.run(host="0.0.0.0", port=5000, debug=False)
