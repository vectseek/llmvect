# -*- coding: utf-8 -*-
"""
LLM.中国 后端服务 - FastAPI
支持所有中国大模型 API，Battle Mode 竞技场模式
集成龙虾排名引擎 (Plackett-Luce + UCB-E)
"""

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Header, UploadFile, File, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
from typing import Optional, List, Dict, Any
import sqlite3
import json
import random
import asyncio
import httpx
import secrets
import base64
import time
import hashlib
import collections
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

# 导入模型配置
from models import LLM_PROVIDERS, ALL_MODELS, BATTLE_MODELS, MODEL_ROUTING

# 导入龙虾排名引擎
from lobster import LobsterRankingEngine
from totoro import preprocess_cross_validation, build_totoro_messages
from auto_router import AutoRouter
from category import classify_category, CATEGORY_NAMES, CATEGORY_ICONS
from quota import check_and_consume_quota, get_quota_status, init_quota_tables, BLIND_QUOTA, THINK_QUOTA
from fingerprint import register_device, check_device_quota, is_device_blocked, increment_device_vote, init_fingerprint_tables

# ==================== 数据库 ====================
DB_PATH = os.path.join(os.path.dirname(__file__), "llm_china.db")

def init_db():
    """初始化数据库"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # API Keys 表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT UNIQUE NOT NULL,
            api_key TEXT NOT NULL,
            secret_key TEXT DEFAULT '',
            app_id TEXT DEFAULT '',
            enabled INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 迁移：旧表无 secret_key/app_id 列时自动添加
    try:
        cursor.execute("SELECT secret_key FROM api_keys LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE api_keys ADD COLUMN secret_key TEXT DEFAULT ''")
    try:
        cursor.execute("SELECT app_id FROM api_keys LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE api_keys ADD COLUMN app_id TEXT DEFAULT ''")
    
    # sponsors 表迁移 — 支持多密钥厂商
    try:
        cursor.execute("ALTER TABLE sponsors ADD COLUMN secret_key TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE sponsors ADD COLUMN app_id TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    
    # Battle 记录表（2模型）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS battle_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            model_a TEXT NOT NULL,
            model_b TEXT NOT NULL,
            model_a_name TEXT NOT NULL,
            model_b_name TEXT NOT NULL,
            response_a TEXT NOT NULL,
            response_b TEXT NOT NULL,
            winner TEXT,
            reason TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 对话历史表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            model TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 管理员账号表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 管理员会话表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # ===== 龙虾排名系统新增表 =====
    
    # 4模型竞技场对局表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS arena4_battles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            model_a TEXT NOT NULL,
            model_b TEXT NOT NULL,
            model_c TEXT NOT NULL,
            model_d TEXT NOT NULL,
            response_a TEXT,
            response_b TEXT,
            response_c TEXT,
            response_d TEXT,
            mode TEXT NOT NULL DEFAULT 'fast',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 4模型竞技场投票表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS arena4_votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            battle_id INTEGER NOT NULL,
            winner_label TEXT NOT NULL,
            winner_model TEXT,
            worst_label TEXT,
            user_id TEXT DEFAULT 'anonymous',
            render_complete_time REAL DEFAULT 0,
            user_click_time REAL DEFAULT 0,
            vote_weight REAL DEFAULT 1.0,
            scroll_depth INTEGER DEFAULT 0,
            mode TEXT NOT NULL DEFAULT 'fast',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (battle_id) REFERENCES arena4_battles(id)
        )
    """)
    
    # 模型评分表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS model_ratings (
            model_id TEXT NOT NULL,
            mode TEXT NOT NULL DEFAULT 'fast',
            month TEXT NOT NULL DEFAULT '',
            gamma REAL DEFAULT 1.0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            ties INTEGER DEFAULT 0,
            impressions INTEGER DEFAULT 0,
            last_active_time TEXT,
            status TEXT DEFAULT 'active',
            PRIMARY KEY (model_id, mode, month)
        )
    """)
    
    # 模型路由映射表（管理员可修改）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS model_routing (
            provider TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            fast TEXT NOT NULL,
            expert TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 初始化默认路由数据（如果表为空）
    cursor.execute("SELECT COUNT(*) FROM model_routing")
    if cursor.fetchone()[0] == 0:
        for pid, route in MODEL_ROUTING.items():
            cursor.execute(
                "INSERT INTO model_routing (provider, name, fast, expert) VALUES (?, ?, ?, ?)",
                (pid, route["name"], route["fast"], route["expert"])
            )

    # 创建索引
    # 审计日志表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            user_id TEXT,
            ip_address TEXT,
            fingerprint TEXT,
            detail TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 用户指纹表（服务端签发user_id + 指纹绑定）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_fingerprints (
            user_id TEXT PRIMARY KEY,
            fingerprint_hash TEXT NOT NULL,
            ip_first TEXT,
            vote_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_active TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_votes_battle ON arena4_votes(battle_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_votes_user ON arena4_votes(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ratings_mode_month ON model_ratings(mode, month)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_battles_mode ON arena4_battles(mode)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_votes_mode ON arena4_votes(mode)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_event ON audit_log(event_type, created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id, created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_ip ON audit_log(ip_address, created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_fingerprint_hash ON user_fingerprints(fingerprint_hash)")

    # DPO标签矩阵表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dpo_labels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            battle_id INTEGER NOT NULL,
            vote_id INTEGER,
            question TEXT NOT NULL,
            model_a_id TEXT,
            model_a_response TEXT,
            model_b_id TEXT,
            model_b_response TEXT,
            model_c_id TEXT,
            model_c_response TEXT,
            model_d_id TEXT,
            model_d_response TEXT,
            winner_label TEXT,
            winner_model TEXT,
            winner_tags TEXT DEFAULT '[]',
            worst_label TEXT,
            worst_model TEXT,
            worst_tags TEXT DEFAULT '[]',
            domain TEXT DEFAULT 'knowledge',
            vote_weight REAL DEFAULT 1.0,
            mode TEXT DEFAULT 'fast',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (battle_id) REFERENCES arena4_battles(id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_dpo_battle ON dpo_labels(battle_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_dpo_domain ON dpo_labels(domain)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_dpo_winner_tags ON dpo_labels(winner_tags)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_dpo_worst_tags ON dpo_labels(worst_tags)")

    # 自定义厂商表（管理员可动态添加）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS custom_providers (
            provider_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            api_base TEXT NOT NULL,
            api_key_env TEXT DEFAULT '',
            icon TEXT DEFAULT '🏢',
            color TEXT DEFAULT '#6366F1',
            models TEXT DEFAULT '[]',
            docs TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    
    # ===== 数据库迁移：添加 category 列 =====
    try:
        cursor.execute("ALTER TABLE arena4_battles ADD COLUMN category TEXT DEFAULT 'overall'")
        conn.commit()
    except:
        pass  # 列已存在
    try:
        cursor.execute("ALTER TABLE arena4_votes ADD COLUMN category TEXT DEFAULT 'overall'")
        conn.commit()
    except:
        pass
    try:
        cursor.execute("ALTER TABLE model_ratings ADD COLUMN category TEXT DEFAULT 'overall'")
        conn.commit()
    except:
        pass
    try:
        cursor.execute("ALTER TABLE dpo_labels ADD COLUMN category TEXT DEFAULT 'overall'")
        conn.commit()
    except:
        pass
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_battles_category ON arena4_battles(category)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_votes_category ON arena4_votes(category)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ratings_category ON model_ratings(category, month)")

    # ===== 数据库迁移：添加 is_valid_for_elo 列 =====
    try:
        cursor.execute("ALTER TABLE arena4_votes ADD COLUMN is_valid_for_elo INTEGER DEFAULT 1")
        conn.commit()
    except:
        pass
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_votes_valid ON arena4_votes(is_valid_for_elo)")

    # ===== 数据库迁移：Axiom V-Verification 新列 =====
    for col, dtype in [("device_hash", "TEXT DEFAULT ''"),
                        ("is_think_enabled", "INTEGER DEFAULT 0"),
                        ("task_difficulty_factor", "REAL DEFAULT 1.0")]:
        try:
            cursor.execute(f"ALTER TABLE arena4_votes ADD COLUMN {col} {dtype}")
            conn.commit()
        except:
            pass
    # arena4_battles 难度跟踪列
    for col, dtype in [("total_votes", "INTEGER DEFAULT 0"),
                        ("consensus_rate", "REAL DEFAULT 1.0"),
                        ("difficulty_factor", "REAL DEFAULT 1.0")]:
        try:
            cursor.execute(f"ALTER TABLE arena4_battles ADD COLUMN {col} {dtype}")
            conn.commit()
        except:
            pass
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_votes_device ON arena4_votes(device_hash)")
    conn.commit()

    # ===== 赞助商系统表 =====
    # 赞助用户表（注册/登录）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sponsor_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 赞助商会话表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sponsor_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token TEXT UNIQUE NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 赞助商表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sponsors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            provider TEXT NOT NULL,
            api_key TEXT NOT NULL,
            brand_name TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            verify_detail TEXT DEFAULT '',
            priority INTEGER DEFAULT 0,
            api_verified INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES sponsor_users(id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sponsors_provider ON sponsors(provider, status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sponsors_user ON sponsors(user_id)")

    # ===== 模型自动发现系统表 =====
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS model_discovery (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            model_id TEXT NOT NULL,
            status TEXT DEFAULT 'discovered',
            source TEXT DEFAULT 'api',
            first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
            last_checked TEXT DEFAULT CURRENT_TIMESTAMP,
            last_healthy TEXT,
            fail_count INTEGER DEFAULT 0,
            metadata TEXT DEFAULT '',
            UNIQUE(provider, model_id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_md_status ON model_discovery(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_md_provider ON model_discovery(provider, status)")
    conn.commit()
    
    # 创建默认管理员账号: 首次启动随机生成密码
    default_user = 'admin'
    default_pass = os.environ.get('ADMIN_PASSWORD', secrets.token_urlsafe(12))
    salt, password_hash = hash_password(default_pass)
    stored = f"{salt}${password_hash}"
    
    cursor.execute("SELECT id FROM admin_users WHERE username = ?", (default_user,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO admin_users (username, password_hash) VALUES (?, ?)",
                      (default_user, stored))
        conn.commit()
        print(f"\n{'='*60}")
        print(f"  Admin: {default_user} / {default_pass}")
        print(f"  Change password after first login!")
        print(f"{'='*60}\n")
    
    # 初始化额度追踪表
    init_quota_tables()
    # 初始化设备指纹表
    init_fingerprint_tables()
    
    conn.close()

# ==================== 月度归档定时器 ====================
async def monthly_archive_scheduler():
    """每月1日0时自动归档上月排行榜"""
    last_archive_month = None
    while True:
        now = datetime.now()
        current_month = now.strftime("%Y-%m")
        if now.day == 1 and current_month != last_archive_month:
            if now.month == 1:
                prev_month = f"{now.year - 1}-12"
            else:
                prev_month = f"{now.year}-{now.month - 1:02d}"
            try:
                result = engine.archive_monthly_rankings(month=prev_month)
                print(f"[Archive] {prev_month} archived: {result}")
                last_archive_month = current_month
            except Exception as e:
                print(f"[Archive] Failed: {e}")
        await asyncio.sleep(3600)

# ==================== 反作弊安全层 ====================

# 内存限流器（IP -> [timestamp, ...]）
_rate_limit_store: Dict[str, collections.deque] = {}
# 内存冷却器（user_id -> last_vote_timestamp）
_vote_cooldown_store: Dict[str, float] = {}

# 限流参数
RATE_LIMIT_WINDOW = 60        # 60秒滑动窗口
RATE_LIMIT_MAX_REQUESTS = 20   # 每窗口最大请求数（全局）
RATE_LIMIT_VOTE_MAX = 10       # 每窗口最大投票数
VOTE_COOLDOWN_SEC = 10         # 投票冷却10秒
MAX_VOTES_PER_USER_DAY = 50    # 每用户每日最大投票数
MAX_VOTES_PER_IP_DAY = 100    # 每IP每日最大投票数

def get_client_ip(request: Request) -> str:
    """提取客户端真实IP（支持代理头）"""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP", "")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"

def check_rate_limit(ip: str, action: str = "general", max_requests: int = RATE_LIMIT_MAX_REQUESTS) -> bool:
    """滑动窗口限流检查。返回True=允许，False=超限"""
    key = f"{ip}:{action}"
    now = time.time()
    if key not in _rate_limit_store:
        _rate_limit_store[key] = collections.deque()
    dq = _rate_limit_store[key]
    # 清理过期记录
    while dq and dq[0] < now - RATE_LIMIT_WINDOW:
        dq.popleft()
    if len(dq) >= max_requests:
        return False
    dq.append(now)
    return True

def check_vote_cooldown(user_id: str) -> bool:
    """投票冷却检查。返回True=允许，False=冷却中"""
    now = time.time()
    last = _vote_cooldown_store.get(user_id, 0)
    if now - last < VOTE_COOLDOWN_SEC:
        return False
    _vote_cooldown_store[user_id] = now
    return True

def check_daily_limit(user_id: str, ip: str) -> bool:
    """DB级每日投票上限检查"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("SELECT COUNT(*) FROM arena4_votes WHERE user_id = ? AND created_at LIKE ?",
                  (user_id, today + "%"))
    user_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM audit_log WHERE ip_address = ? AND event_type = 'vote' AND created_at LIKE ?",
                  (ip, today + "%"))
    ip_count = cursor.fetchone()[0]
    conn.close()
    return user_count < MAX_VOTES_PER_USER_DAY and ip_count < MAX_VOTES_PER_IP_DAY

def validate_fingerprint(user_id: str, fingerprint: str, ip: str) -> bool:
    """校验指纹一致性（同一user_id不应切换指纹）。返回True=合法"""
    if not fingerprint or not user_id:
        return False
    fp_hash = hashlib.sha256(fingerprint.encode()).hexdigest()[:32]
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT fingerprint_hash FROM user_fingerprints WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row:
        # 已有记录，检查指纹是否一致
        if row[0] != fp_hash:
            # 指纹不匹配 - 可能的账号盗用
            log_audit("fingerprint_mismatch", user_id, ip, fp_hash, "fingerprint changed")
            conn.close()
            return False
        # 更新活跃时间
        cursor.execute("UPDATE user_fingerprints SET last_active = CURRENT_TIMESTAMP, vote_count = vote_count + 1 WHERE user_id = ?",
                      (user_id,))
        conn.commit()
        conn.close()
        return True
    else:
        # 新用户，绑定指纹
        cursor.execute("INSERT INTO user_fingerprints (user_id, fingerprint_hash, ip_first, vote_count) VALUES (?, ?, ?, 1)",
                      (user_id, fp_hash, ip))
        conn.commit()
        conn.close()
        return True

def detect_anomalous_pattern(user_id: str, ip: str) -> Optional[str]:
    """异常投票模式检测。返回None=正常，否则返回异常描述"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = datetime.now()

    # 1. 短时间高频投票（10分钟内>8票）
    ten_min_ago = (now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("SELECT COUNT(*) FROM audit_log WHERE user_id = ? AND event_type = 'vote' AND created_at > ?",
                  (user_id, ten_min_ago))
    rapid_votes = cursor.fetchone()[0]
    if rapid_votes > 8:
        conn.close()
        return f"rapid_fire: {rapid_votes} votes in 10min"

    # 2. 同一IP关联过多user_id（24小时内>5个）
    day_ago = (now - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("SELECT COUNT(DISTINCT user_id) FROM audit_log WHERE ip_address = ? AND event_type = 'vote' AND created_at > ?",
                  (ip, day_ago))
    ip_users = cursor.fetchone()[0]
    if ip_users > 5:
        conn.close()
        return f"ip_multi_account: {ip_users} distinct users from same IP in 24h"

    # 3. 投票分布异常（只投一个label且>=10次）
    cursor.execute("SELECT winner_label, COUNT(*) as cnt FROM arena4_votes WHERE user_id = ? GROUP BY winner_label ORDER BY cnt DESC",
                  (user_id,))
    label_dist = cursor.fetchall()
    if label_dist and len(label_dist) == 1 and label_dist[0][1] >= 10:
        conn.close()
        return f"biased_voting: only votes {label_dist[0][0]} ({label_dist[0][1]} times)"

    conn.close()
    return None

def log_audit(event_type: str, user_id: str = None, ip: str = None, fingerprint: str = None, detail: str = None):
    """写入审计日志"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO audit_log (event_type, user_id, ip_address, fingerprint, detail)
        VALUES (?, ?, ?, ?, ?)
    """, (event_type, user_id, ip, fingerprint, detail))
    conn.commit()
    conn.close()

def issue_user_id(fingerprint: str, ip: str) -> str:
    """服务端签发user_id，绑定指纹"""
    if not fingerprint:
        return "anon_" + secrets.token_urlsafe(12)
    fp_hash = hashlib.sha256(fingerprint.encode()).hexdigest()[:16]
    # 用指纹哈希生成确定性user_id，同一指纹=同一user_id
    user_id = f"u_{fp_hash}"
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    full_hash = hashlib.sha256(fingerprint.encode()).hexdigest()[:32]
    cursor.execute("SELECT user_id FROM user_fingerprints WHERE fingerprint_hash = ?", (full_hash,))
    row = cursor.fetchone()
    if row:
        # 指纹已存在，返回已有user_id，更新活跃时间
        cursor.execute("UPDATE user_fingerprints SET last_active = CURRENT_TIMESTAMP, ip_first = COALESCE(ip_first, ?) WHERE fingerprint_hash = ?",
                      (ip, full_hash))
        conn.commit()
        conn.close()
        return row[0]
    else:
        # 新指纹，签发新user_id
        cursor.execute("INSERT INTO user_fingerprints (user_id, fingerprint_hash, ip_first) VALUES (?, ?, ?)",
                      (user_id, full_hash, ip))
        conn.commit()
        conn.close()
        return user_id

# ==================== FastAPI 应用 ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(monthly_archive_scheduler())
    # 启动模型发现 + 健康检查定时任务
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        scheduler = AsyncIOScheduler()
        scheduler.add_job(run_discovery, 'interval', hours=6, id='model_discovery', replace_existing=True)
        scheduler.add_job(run_health_check, 'interval', hours=1, id='health_check', replace_existing=True)
        scheduler.start()
    except ImportError:
        print("[WARN] apscheduler not installed, model discovery scheduler disabled")
        scheduler = None
    yield
    task.cancel()
    if scheduler:
        scheduler.shutdown()

app = FastAPI(
    title="LLM.中国 API",
    description="支持所有中国大模型的统一API网关",
    version="1.0.0",
    lifespan=lifespan
)

# 初始化龙虾排名引擎
engine = LobsterRankingEngine(DB_PATH)
auto_router = AutoRouter(DB_PATH)

# 前端文件目录
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")

@app.get("/")
async def root():
    """返回前端页面"""
    content = open(os.path.join(FRONTEND_DIR, "index.html"), "r", encoding="utf-8").read()
    return Response(content=content, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

@app.get("/admin.html")
async def admin_page():
    """返回管理后台页面"""
    return FileResponse(os.path.join(FRONTEND_DIR, "admin.html"))

@app.get("/arena4")
async def arena4_page():
    """返回4模型竞技场页面"""
    return FileResponse(os.path.join(FRONTEND_DIR, "arena4.html"))

@app.get("/leaderboard.html")
async def leaderboard_page():
    """返回排行榜页面"""
    return FileResponse(os.path.join(FRONTEND_DIR, "leaderboard.html"))

@app.get("/rules.html")
async def rules_page():
    """返回规则说明页面"""
    return FileResponse(os.path.join(FRONTEND_DIR, "rules.html"))

@app.get("/protocol.html")
async def protocol_page():
    """返回验证协议白皮书页面"""
    return FileResponse(os.path.join(FRONTEND_DIR, "protocol.html"))

@app.get("/sponsor.html")
async def sponsor_page():
    """返回赞助商用户中心页面"""
    return FileResponse(os.path.join(FRONTEND_DIR, "sponsor.html"))

@app.get("/manifest.json")
async def manifest():
    return FileResponse(os.path.join(FRONTEND_DIR, "manifest.json"), media_type="application/json")

@app.get("/sw.js")
async def service_worker():
    return FileResponse(os.path.join(FRONTEND_DIR, "sw.js"), media_type="application/javascript")

@app.get("/icons/{filename}")
async def icons(filename: str):
    safe = os.path.normpath(filename)
    if safe.startswith("..") or os.path.isabs(safe) or ".." in safe:
        raise HTTPException(status_code=404)
    return FileResponse(os.path.join(FRONTEND_DIR, "icons", safe))

@app.get("/api/detect-region")
async def detect_region(request: Request):
    """根据请求 IP 检测用户所在地区，返回建议语言"""
    # 获取真实 IP（支持反向代理）
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if not ip or ip == "unknown":
        ip = request.headers.get("x-real-ip", "")
    if not ip:
        ip = request.client.host if request.client else ""
    # 本地访问默认中文
    if ip in ("127.0.0.1", "::1", "localhost", ""):
        return {"country": "CN", "lang": "zh", "ip": ip}
    # 使用免费 IP 地理位置 API
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"https://ipwho.is/{ip}")
            if resp.status_code == 200:
                data = resp.json()
                country = data.get("country_code", "")
                # 中国大陆、香港、澳门、台湾、新加坡(大量华人) -> 中文
                cn_regions = {"CN", "HK", "MO", "TW", "SG"}
                lang = "zh" if country in cn_regions else "en"
                return {"country": country, "lang": lang, "ip": ip}
    except Exception:
        pass
    # 备用：ip-api.com
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"http://ip-api.com/json/{ip}?fields=countryCode")
            if resp.status_code == 200:
                country = resp.json().get("countryCode", "")
                cn_regions = {"CN", "HK", "MO", "TW", "SG"}
                lang = "zh" if country in cn_regions else "en"
                return {"country": country, "lang": lang, "ip": ip}
    except Exception:
        pass
    # 都失败了，回退到浏览器语言
    return {"country": "unknown", "lang": None, "ip": ip}

# CORS（不设 credentials 以避免与 wildcard origin 冲突）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==================== 数据模型 ====================
class ChatRequest(BaseModel):
    messages: List[Dict[str, str]]
    model: str
    stream: bool = False

class BattleRequest(BaseModel):
    question: str
    model_a: Optional[str] = None
    model_b: Optional[str] = None

class VoteRequest(BaseModel):
    battle_id: int
    winner: str  # "A", "B", "tie", "both_bad"
    reason: Optional[str] = None

class ApiKeyRequest(BaseModel):
    provider: str
    api_key: str
    secret_key: str = ""
    app_id: str = ""

class LoginRequest(BaseModel):
    username: str
    password: str

# ==================== 管理员认证（PBKDF2 + salt）====================
def hash_password(pwd: str, salt: str = None) -> tuple:
    """PBKDF2-SHA256 with random salt. Returns (salt, hash) or (None, hash) for legacy"""
    import hashlib
    if salt is None:
        salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac('sha256', pwd.encode(), salt.encode(), 200000)
    return (salt, dk.hex())

def verify_admin(username: str, password: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash FROM admin_users WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return False
    stored = row[0]
    # 新格式: salt$hash
    if '$' in stored:
        salt, h = stored.split('$', 1)
        dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 200000)
        return dk.hex() == h
    # 旧格式: plain sha256（向后兼容，登录后自动升级）
    return stored == hashlib.sha256(password.encode()).hexdigest()

def upgrade_password_hash(username: str, password: str):
    """如果仍使用旧sha256格式，自动升级为pbkdf2"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash FROM admin_users WHERE username = ?", (username,))
    row = cursor.fetchone()
    if row and '$' not in row[0]:
        salt, h = hash_password(password)
        cursor.execute("UPDATE admin_users SET password_hash = ? WHERE username = ?",
                      (f"{salt}${h}", username))
        conn.commit()
    conn.close()

def create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(days=7)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO admin_sessions (username, token, expires_at) VALUES (?, ?, ?)",
                  (username, token, expires))
    conn.commit()
    conn.close()
    return token

def verify_token(authorization: str) -> bool:
    if not authorization or not authorization.startswith("Bearer "):
        return False
    token = authorization[7:]
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT expires_at FROM admin_sessions WHERE token = ?", (token,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return False
    expires = datetime.fromisoformat(row[0])
    return expires > datetime.now()

def require_admin(authorization: str = Header(None)):
    if not verify_token(authorization):
        raise HTTPException(status_code=401, detail="请先登录")

# ==================== 管理员接口 ====================
@app.post("/api/admin/login")
async def admin_login(request: LoginRequest, http_request: Request):
    """管理员登录（限流5次/分钟/IP）"""
    ip = get_client_ip(http_request)
    if not check_rate_limit(ip, "admin_login", 5):
        log_audit("admin_bruteforce_blocked", ip=ip, detail=f"target={request.username}")
        raise HTTPException(status_code=429, detail="登录尝试过多，请稍后再试")
    if verify_admin(request.username, request.password):
        upgrade_password_hash(request.username, request.password)
        token = create_session(request.username)
        return {"success": True, "token": token}
    log_audit("admin_login_failed", ip=ip, detail=f"username={request.username}")
    raise HTTPException(status_code=401, detail="账号或密码错误")

@app.post("/api/admin/logout")
async def admin_logout(authorization: str = Header(None)):
    """管理员登出"""
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))
        conn.commit()
        conn.close()
    return {"success": True}

# ==================== 微信小程序登录 ====================
class WxLoginRequest(BaseModel):
    code: str

@app.post("/api/wx/login")
async def wx_login(request: WxLoginRequest):
    """微信小程序登录 - 用code换取openid"""
    # 开发阶段：如果没有配置appid/secret，直接用code作为用户标识
    wx_appid = os.environ.get('WX_APPID', '')
    wx_secret = os.environ.get('WX_SECRET', '')
    
    if wx_appid and wx_secret:
        # 正式模式：调用微信接口换取openid
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(
                    'https://api.weixin.qq.com/sns/jscode2session',
                    params={
                        'appid': wx_appid,
                        'secret': wx_secret,
                        'js_code': request.code,
                        'grant_type': 'authorization_code'
                    },
                    timeout=10
                )
                data = resp.json()
                openid = data.get('openid', '')
                if not openid:
                    raise HTTPException(status_code=400, detail=f"微信登录失败: {data.get('errmsg','unknown')}")
            except httpx.HTTPError:
                raise HTTPException(status_code=500, detail="微信接口调用失败")
    else:
        # 开发模式：code即用户标识
        openid = f"wx_dev_{request.code}"
    
    # 生成本地session token
    token = secrets.token_hex(32)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS wx_users (
            openid TEXT PRIMARY KEY,
            token TEXT,
            nickname TEXT DEFAULT '',
            avatar_url TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            last_login TEXT DEFAULT (datetime('now'))
        )
    """)
    cursor.execute("INSERT OR REPLACE INTO wx_users (openid, token, last_login) VALUES (?, ?, datetime('now'))", (openid, token))
    conn.commit()
    conn.close()
    
    return {"success": True, "token": token, "openid": openid}

# ==================== API Key 管理 ====================
@app.get("/api/keys")
async def list_api_keys(authorization: str = Header(None)):
    """列出所有厂商的API Key状态（含自定义厂商）"""
    require_admin(authorization)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    result = []
    # 1. 硬编码厂商
    for provider_id, provider in LLM_PROVIDERS.items():
        cursor.execute("SELECT api_key, secret_key, app_id, enabled FROM api_keys WHERE provider = ?", (provider_id,))
        row = cursor.fetchone()
        auth_type = provider.get("auth_type", "standard")
        result.append({
            "id": provider_id,
            "name": provider["name"],
            "icon": provider["icon"],
            "color": provider["color"],
            "models": provider["models"],
            "docs": provider["docs"],
            "has_key": row is not None and bool(row[0]),
            "enabled": row[3] if row else 0,
            "api_key_preview": row[0][:8] + "..." if row and row[0] and len(row[0]) > 8 else None,
            "is_custom": False,
            "auth_type": auth_type
        })
    
    # 2. 自定义厂商
    cursor.execute("SELECT provider_id, name, api_base, api_key_env, icon, color, models, docs FROM custom_providers ORDER BY created_at")
    custom_rows = cursor.fetchall()
    for row in custom_rows:
        pid, pname, pbase, penv, picon, pcolor, pmodels, pdocs = row
        cursor.execute("SELECT api_key, enabled FROM api_keys WHERE provider = ?", (pid,))
        krow = cursor.fetchone()
        model_list = json.loads(pmodels) if pmodels else []
        result.append({
            "id": pid,
            "name": pname,
            "icon": picon,
            "color": pcolor,
            "models": model_list,
            "docs": pdocs or pbase,
            "has_key": krow is not None and bool(krow[0]),
            "enabled": krow[1] if krow else 0,
            "api_key_preview": krow[0][:8] + "..." if krow and krow[0] and len(krow[0]) > 8 else None,
            "is_custom": True,
            "api_base": pbase,
            "auth_type": "standard"
        })
    
    conn.close()
    return result

@app.post("/api/keys")
async def set_api_key(request: ApiKeyRequest, authorization: str = Header(None)):
    """设置API Key（支持硬编码和自定义厂商）"""
    require_admin(authorization)
    # 检查是否为硬编码厂商或自定义厂商
    is_known = request.provider in LLM_PROVIDERS
    if not is_known:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT provider_id FROM custom_providers WHERE provider_id = ?", (request.provider,))
        if not cursor.fetchone():
            conn.close()
            raise HTTPException(status_code=400, detail=f"未知的厂商: {request.provider}")
        conn.close()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO api_keys (provider, api_key, secret_key, app_id, enabled, updated_at)
        VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
        ON CONFLICT(provider) DO UPDATE SET 
            api_key = excluded.api_key,
            secret_key = excluded.secret_key,
            app_id = excluded.app_id,
            enabled = 1,
            updated_at = CURRENT_TIMESTAMP
    """, (request.provider, request.api_key, request.secret_key, request.app_id))
    
    conn.commit()
    conn.close()
    
    # 获取厂商名称
    provider_name = request.provider
    if request.provider in LLM_PROVIDERS:
        provider_name = LLM_PROVIDERS[request.provider]['name']
    else:
        conn2 = sqlite3.connect(DB_PATH)
        c2 = conn2.cursor()
        c2.execute("SELECT name FROM custom_providers WHERE provider_id = ?", (request.provider,))
        row = c2.fetchone()
        conn2.close()
        if row:
            provider_name = row[0]
    return {"success": True, "message": f"{provider_name} API Key 已保存"}

@app.delete("/api/keys/{provider}")
async def delete_api_key(provider: str, authorization: str = Header(None)):
    """删除API Key"""
    require_admin(authorization)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM api_keys WHERE provider = ?", (provider,))
    conn.commit()
    conn.close()
    return {"success": True}

@app.post("/api/keys/{provider}/toggle")
async def toggle_api_key(provider: str, enabled: int = 1, authorization: str = Header(None)):
    """启用/禁用API Key"""
    require_admin(authorization)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE api_keys SET enabled = ? WHERE provider = ?", (enabled, provider))
    conn.commit()
    conn.close()
    return {"success": True}

# ==================== API Key 测试端点 ====================
@app.post("/api/keys/test")
async def test_api_key(request: ApiKeyRequest, authorization: str = Header(None)):
    """测试API Key是否有效 — 测试通过后才能保存"""
    require_admin(authorization)
    provider_id = request.provider
    if provider_id not in LLM_PROVIDERS:
        return {"success": False, "message": f"未知厂商: {provider_id}"}
    
    provider = LLM_PROVIDERS[provider_id]
    auth_type = provider.get("auth_type", "standard")
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        # 百度：测试 OAuth2 token 换取
        if auth_type == "baidu":
            if not request.api_key or not request.secret_key:
                return {"success": False, "message": "百度需要 API Key(AK) 和 Secret Key(SK)"}
            try:
                resp = await client.post(
                    "https://aip.baidubce.com/oauth/2.0/token",
                    data={"grant_type": "client_credentials", "client_id": request.api_key, "client_secret": request.secret_key}
                )
                if resp.status_code == 200 and "access_token" in resp.json():
                    return {"success": True, "message": "百度认证成功 ✓", "models": [], "models_note": "百度不支持 /v1/models 自动发现"}
                return {"success": False, "message": f"百度认证失败: {resp.text[:200]}"}
            except Exception as e:
                return {"success": False, "message": f"百度请求失败: {str(e)}"}
        
        # 华为：测试 IAM Token
        elif auth_type == "huawei":
            if not request.api_key or not request.secret_key:
                return {"success": False, "message": "华为需要 AK 和 SK"}
            try:
                resp = await client.post(
                    "https://iam.cn-north-4.myhuaweicloud.com/v3/auth/tokens",
                    json={
                        "auth": {
                            "identity": {
                                "methods": ["hw_ak_sk"],
                                "hw_ak_sk": {"access": {"key": request.api_key}, "secret": {"key": request.secret_key}}
                            },
                            "scope": {"project": {"name": "cn-north-4"}}
                        }
                    }
                )
                if resp.status_code in (200, 201):
                    return {"success": True, "message": "华为IAM认证成功 ✓", "models": [], "models_note": "华为不支持 /v1/models 自动发现"}
                return {"success": False, "message": f"华为IAM认证失败 (HTTP {resp.status_code}): {resp.text[:200]}"}
            except Exception as e:
                return {"success": False, "message": f"华为IAM请求失败: {str(e)}"}
        
        # 科大讯飞：测试 REST API
        elif auth_type == "xfyun":
            if not request.app_id or not request.api_key or not request.secret_key:
                return {"success": False, "message": "科大讯飞需要 APPID、APIKey 和 APISecret"}
            try:
                resp = await client.post(
                    "https://spark-api-open.xf-yun.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {request.api_key}:{request.secret_key}", "Content-Type": "application/json"},
                    json={"model": "generalv3.5", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5}
                )
                if resp.status_code == 200:
                    return {"success": True, "message": "科大讯飞认证成功 ✓", "models": [], "models_note": "科大讯飞不支持 /v1/models 自动发现"}
                return {"success": False, "message": f"科大讯飞认证失败 (HTTP {resp.status_code}): {resp.text[:200]}"}
            except Exception as e:
                return {"success": False, "message": f"科大讯飞请求失败: {str(e)}"}
                
        # Anthropic：测试 x-api-key 认证
        elif auth_type == "anthropic":
            if not request.api_key:
                return {"success": False, "message": "请填写API Key"}
            try:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": request.api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
                    json={"model": "claude-3.5-haiku", "max_tokens": 5, "messages": [{"role": "user", "content": "hi"}]}
                )
                if resp.status_code == 200:
                    # Anthropic 测试成功，尝试获取模型列表
                    models_list = []
                    try:
                        models_resp = await client.get(
                            "https://api.anthropic.com/v1/models",
                            headers={"x-api-key": request.api_key, "anthropic-version": "2023-06-01"}
                        )
                        if models_resp.status_code == 200:
                            models_data = models_resp.json().get("data", [])
                            models_list = [m.get("id", "") for m in models_data if m.get("id")]
                    except Exception:
                        pass
                    result = {"success": True, "message": "Anthropic 认证成功 ✓", "models": models_list}
                    if not models_list:
                        result["models_note"] = "无法获取模型列表，请手动配置"
                    return result
                return {"success": False, "message": f"Anthropic 认证失败 (HTTP {resp.status_code}): {resp.text[:200]}"}
            except Exception as e:
                return {"success": False, "message": f"Anthropic 请求失败: {str(e)}"}
        
        # Cohere：测试 Bearer 认证 (v2 chat endpoint)
        elif auth_type == "cohere":
            if not request.api_key:
                return {"success": False, "message": "请填写API Key"}
            try:
                resp = await client.post(
                    "https://api.cohere.ai/v2/chat",
                    headers={"Authorization": f"Bearer {request.api_key}", "Content-Type": "application/json"},
                    json={"model": "command-r-08-2024", "messages": [{"role": "user", "content": "hi"}]}
                )
                if resp.status_code == 200:
                    # Cohere 测试成功，尝试获取模型列表
                    models_list = []
                    try:
                        models_resp = await client.get(
                            "https://api.cohere.ai/v2/models",
                            headers={"Authorization": f"Bearer {request.api_key}"}
                        )
                        if models_resp.status_code == 200:
                            models_data = models_resp.json().get("models", models_resp.json().get("data", []))
                            models_list = [m.get("name", m.get("id", "")) for m in models_data]
                    except Exception:
                        pass
                    result = {"success": True, "message": "Cohere 认证成功 ✓", "models": models_list}
                    if not models_list:
                        result["models_note"] = "无法获取模型列表，请手动配置"
                    return result
                return {"success": False, "message": f"Cohere 认证失败 (HTTP {resp.status_code}): {resp.text[:200]}"}
            except Exception as e:
                return {"success": False, "message": f"Cohere 请求失败: {str(e)}"}
        
        # Google Gemini：测试 API Key（query param 方式）
        elif auth_type == "google":
            if not request.api_key:
                return {"success": False, "message": "请填写API Key"}
            try:
                resp = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={request.api_key}",
                    headers={"Content-Type": "application/json"},
                    json={"contents": [{"parts": [{"text": "hi"}]}], "generationConfig": {"maxOutputTokens": 5}}
                )
                if resp.status_code == 200:
                    # Google 测试成功，尝试获取模型列表
                    models_list = []
                    try:
                        models_resp = await client.get(
                            f"https://generativelanguage.googleapis.com/v1beta/models?key={request.api_key}"
                        )
                        if models_resp.status_code == 200:
                            models_data = models_resp.json().get("models", [])
                            models_list = [m.get("name", "").replace("models/", "") for m in models_data if m.get("name")]
                    except Exception:
                        pass
                    result = {"success": True, "message": "Google Gemini 认证成功 ✓", "models": models_list}
                    if not models_list:
                        result["models_note"] = "无法获取模型列表，请手动配置"
                    return result
                error_data = resp.json() if resp.text else {}
                return {"success": False, "message": f"Google 认证失败 (HTTP {resp.status_code}): {error_data.get('error', {}).get('message', resp.text[:200])}"}
            except Exception as e:
                return {"success": False, "message": f"Google 请求失败: {str(e)}"}
        

        # 标准OpenAI兼容厂商
        else:
            if not request.api_key:
                return {"success": False, "message": "请填写API Key"}
            api_base = provider.get("api_base", "")
            models = provider.get("models", [])
            if not api_base or not models:
                return {"success": False, "message": f"{provider['name']} 未配置api_base或模型"}
            try:
                resp = await client.post(
                    api_base,
                    headers={"Authorization": f"Bearer {request.api_key}", "Content-Type": "application/json"},
                    json={"model": models[0], "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5}
                )
                if resp.status_code == 200:
                    # 标准厂商测试成功，尝试获取模型列表
                    models_list = await discover_provider_models(provider_id, request.api_key, api_base)
                    result = {"success": True, "message": f"{provider['name']} 连接成功 ✓", "models": models_list}
                    if not models_list:
                        result["models_note"] = "无法获取模型列表（厂商可能不支持 /v1/models 接口）"
                    return result
                return {"success": False, "message": f"{provider['name']} 返回错误 (HTTP {resp.status_code}): {resp.text[:200]}"}
            except Exception as e:
                return {"success": False, "message": f"{provider['name']} 连接失败: {str(e)}"}

# ==================== 模型自动发现 + 健康检查 ====================

# 不支持 /v1/models 的特殊厂商，仅靠健康探测
_NO_MODELS_API_PROVIDERS = {"baidu", "xfyun", "huawei"}

async def discover_provider_models(provider_id: str, api_key: str, api_base: str):
    """调用厂商 /v1/models 接口，发现所有可用模型"""
    if provider_id in _NO_MODELS_API_PROVIDERS:
        return []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # 尝试 /models 和 /v1/models 两种路径
            for path in ["/models", "/v1/models"]:
                try:
                    resp = await client.get(
                        f"{api_base.rstrip('/')}{path}",
                        headers={"Authorization": f"Bearer {api_key}"}
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        models = data.get("data", [])
                        return [m["id"] for m in models if "id" in m]
                except Exception:
                    continue
        return []
    except Exception:
        return []


async def run_discovery():
    """遍历所有已配置 API Key 的厂商，拉取模型列表"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT provider, api_key, COALESCE(secret_key,'') FROM api_keys WHERE enabled = 1")
    keys = cursor.fetchall()

    new_models = []
    deprecated_models = []

    for provider_id, api_key, secret_key in keys:
        provider = LLM_PROVIDERS.get(provider_id, {})
        api_base = provider.get("api_base", "")
        if not api_base or not api_key:
            continue

        remote_models = await discover_provider_models(provider_id, api_key, api_base)
        if not remote_models:
            continue

        # 已知模型（本地配置中的）
        known = set(m["id"] for m in ALL_MODELS if m["provider"] == provider_id)
        remote_set = set(remote_models)

        # 新发现的模型
        for mid in remote_set - known:
            new_models.append({"provider": provider_id, "model_id": mid, "provider_name": provider.get("name", provider_id)})
            cursor.execute("""
                INSERT OR IGNORE INTO model_discovery (provider, model_id, status, source)
                VALUES (?, ?, 'discovered', 'api')
            """, (provider_id, mid))

        # 可能下架的模型
        for mid in known - remote_set:
            deprecated_models.append({"provider": provider_id, "model_id": mid, "provider_name": provider.get("name", provider_id)})
            cursor.execute("""
                UPDATE model_discovery SET status = 'deprecated'
                WHERE provider = ? AND model_id = ? AND status != 'disabled'
            """, (provider_id, mid))

        # 更新已知模型的状态为 verified
        for mid in remote_set & known:
            cursor.execute("""
                INSERT OR IGNORE INTO model_discovery (provider, model_id, status, source)
                VALUES (?, ?, 'verified', 'api')
            """, (provider_id, mid))
            cursor.execute("""
                UPDATE model_discovery SET last_checked = datetime('now'),
                last_healthy = datetime('now'), fail_count = 0, status = 'verified'
                WHERE provider = ? AND model_id = ?
            """, (provider_id, mid))

    conn.commit()
    conn.close()
    return new_models, deprecated_models


async def health_check_model(provider_id: str, model_id: str, api_key: str, secret_key: str = "", app_id: str = ""):
    """发一个极短请求测试模型是否可用"""
    provider = LLM_PROVIDERS.get(provider_id, {})
    api_base = provider.get("api_base", "")
    auth_type = provider.get("auth_type", "standard")

    if not api_base or not api_key:
        return False, "no api_base or api_key"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # 百度：先换 token
            if auth_type == "baidu" and secret_key:
                try:
                    token_resp = await client.post(
                        "https://aip.baidubce.com/oauth/2.0/token",
                        params={"grant_type": "client_credentials", "client_id": api_key, "client_secret": secret_key}
                    )
                    if token_resp.status_code == 200 and "access_token" in token_resp.json():
                        access_token = token_resp.json()["access_token"]
                        resp = await client.post(
                            f"{api_base}/completions",
                            params={"access_token": access_token},
                            json={"model": model_id, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}
                        )
                        return resp.status_code == 200, f"HTTP {resp.status_code}"
                except Exception as e:
                    return False, str(e)

            # 科大讯飞：REST API
            elif auth_type == "xfyun":
                try:
                    resp = await client.post(
                        "https://spark-api-open.xf-yun.com/v1/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}:{secret_key}", "Content-Type": "application/json"},
                        json={"model": model_id, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}
                    )
                    return resp.status_code == 200, f"HTTP {resp.status_code}"
                except Exception as e:
                    return False, str(e)

            # Anthropic
            elif auth_type == "anthropic":
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
                    json={"model": model_id, "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]}
                )
                return resp.status_code == 200, f"HTTP {resp.status_code}"

            # Google Gemini
            elif auth_type == "google":
                resp = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}",
                    headers={"Content-Type": "application/json"},
                    json={"contents": [{"parts": [{"text": "hi"}]}], "generationConfig": {"maxOutputTokens": 1}}
                )
                return resp.status_code == 200, f"HTTP {resp.status_code}"

            # Cohere
            elif auth_type == "cohere":
                resp = await client.post(
                    "https://api.cohere.ai/v2/chat",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": model_id, "messages": [{"role": "user", "content": "hi"}]}
                )
                return resp.status_code == 200, f"HTTP {resp.status_code}"

            # 字节跳动
            elif provider_id == "byteDance":
                resp = await client.post(
                    api_base,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": model_id, "input": [{"role": "user", "content": [{"type": "input_text", "text": "hi"}]}]}
                )
                return resp.status_code == 200, f"HTTP {resp.status_code}"

            # 标准OpenAI兼容
            else:
                resp = await client.post(
                    f"{api_base}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json={"model": model_id, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}
                )
                return resp.status_code == 200, f"HTTP {resp.status_code}"
    except Exception as e:
        return False, str(e)


async def run_health_check():
    """对所有已启用厂商的模型做健康探测"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT provider, api_key, COALESCE(secret_key,''), COALESCE(app_id,'') FROM api_keys WHERE enabled = 1")
    keys = {row[0]: (row[1], row[2], row[3]) for row in cursor.fetchall()}

    # 获取需要探测的模型：所有已知模型 + 已发现的模型
    models_to_check = []

    # 已知模型（BATTLE_MODELS 中的）
    for m in BATTLE_MODELS:
        pid = m["provider"]
        if pid in keys:
            models_to_check.append((pid, m["model"]))

    # 已发现但未在已知列表中的模型
    cursor.execute("SELECT provider, model_id FROM model_discovery WHERE status != 'disabled'")
    for row in cursor.fetchall():
        if (row[0], row[1]) not in set(models_to_check) and row[0] in keys:
            models_to_check.append((row[0], row[1]))

    results = {"healthy": 0, "unhealthy": 0, "newly_disabled": 0}

    for provider_id, model_id in models_to_check:
        api_key, secret_key, app_id = keys[provider_id]
        healthy, detail = await health_check_model(provider_id, model_id, api_key, secret_key, app_id)

        if healthy:
            cursor.execute("""
                INSERT OR IGNORE INTO model_discovery (provider, model_id, status, source)
                VALUES (?, ?, 'verified', 'healthcheck')
            """, (provider_id, model_id))
            cursor.execute("""
                UPDATE model_discovery SET
                last_healthy = datetime('now'),
                last_checked = datetime('now'),
                fail_count = 0,
                status = 'verified'
                WHERE provider = ? AND model_id = ?
            """, (provider_id, model_id))
            results["healthy"] += 1
        else:
            cursor.execute("""
                INSERT OR IGNORE INTO model_discovery (provider, model_id, status, source, fail_count)
                VALUES (?, ?, 'discovered', 'healthcheck', 1)
            """, (provider_id, model_id))
            cursor.execute("""
                UPDATE model_discovery SET
                last_checked = datetime('now'),
                fail_count = fail_count + 1
                WHERE provider = ? AND model_id = ?
            """, (provider_id, model_id))
            # 连续3次失败 -> 自动禁用
            cursor.execute("""
                UPDATE model_discovery SET status = 'disabled'
                WHERE provider = ? AND model_id = ? AND fail_count >= 3 AND status != 'disabled'
            """, (provider_id, model_id))
            if cursor.rowcount > 0:
                results["newly_disabled"] += 1
            results["unhealthy"] += 1

    conn.commit()
    conn.close()
    return results


def get_disabled_models_set():
    """获取当前被禁用的模型ID集合（供 arena 调用过滤）"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT provider, model_id FROM model_discovery WHERE status = 'disabled'")
    disabled = set((row[0], row[1]) for row in cursor.fetchall())
    conn.close()
    return disabled


@app.post("/api/admin/discover")
async def trigger_discovery(authorization: str = Header(None)):
    """手动触发模型发现"""
    require_admin(authorization)
    new, deprecated = await run_discovery()
    return {
        "new_models": new,
        "deprecated_models": deprecated,
        "new_count": len(new),
        "deprecated_count": len(deprecated)
    }


@app.post("/api/admin/health-check")
async def trigger_health_check(authorization: str = Header(None)):
    """手动触发健康探测"""
    require_admin(authorization)
    results = await run_health_check()
    return results


@app.get("/api/admin/model-health")
async def get_model_health(authorization: str = Header(None)):
    """获取所有模型健康状态"""
    require_admin(authorization)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT provider, model_id, status, fail_count,
               last_checked, last_healthy, first_seen, source
        FROM model_discovery ORDER BY
        CASE status
            WHEN 'disabled' THEN 1
            WHEN 'deprecated' THEN 2
            WHEN 'discovered' THEN 3
            WHEN 'verified' THEN 4
        END, provider, model_id
    """)
    rows = cursor.fetchall()
    conn.close()
    return [{
        "provider": r[0],
        "model_id": r[1],
        "provider_name": LLM_PROVIDERS.get(r[0], {}).get("name", r[0]),
        "status": r[2],
        "fail_count": r[3],
        "last_checked": r[4],
        "last_healthy": r[5],
        "first_seen": r[6],
        "source": r[7]
    } for r in rows]


@app.post("/api/admin/model-health/{provider}/{model_id}/toggle")
async def toggle_model_status(provider: str, model_id: str, authorization: str = Header(None)):
    """启用/禁用模型"""
    require_admin(authorization)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM model_discovery WHERE provider = ? AND model_id = ?", (provider, model_id))
    row = cursor.fetchone()
    if not row:
        cursor.execute("""
            INSERT INTO model_discovery (provider, model_id, status, source)
            VALUES (?, ?, 'disabled', 'manual')
        """, (provider, model_id))
        conn.commit()
        conn.close()
        return {"provider": provider, "model_id": model_id, "status": "disabled"}

    new_status = "verified" if row[0] == "disabled" else "disabled"
    cursor.execute("""
        UPDATE model_discovery SET status = ?, fail_count = 0
        WHERE provider = ? AND model_id = ?
    """, (new_status, provider, model_id))
    conn.commit()
    conn.close()
    return {"provider": provider, "model_id": model_id, "status": new_status}


# ==================== 自定义厂商管理 ====================
class CustomProviderRequest(BaseModel):
    provider_id: str
    name: str
    api_base: str
    api_key_env: str = ""
    icon: str = "🏢"
    color: str = "#6366F1"
    models: list = []
    docs: str = ""

@app.get("/api/admin/custom-providers")
async def list_custom_providers(authorization: str = Header(None)):
    """列出所有自定义厂商"""
    require_admin(authorization)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT provider_id, name, api_base, api_key_env, icon, color, models, docs, created_at FROM custom_providers ORDER BY created_at")
    rows = cursor.fetchall()
    conn.close()
    return [{
        "provider_id": r[0], "name": r[1], "api_base": r[2], "api_key_env": r[3],
        "icon": r[4], "color": r[5], "models": json.loads(r[6]) if r[6] else [],
        "docs": r[7], "created_at": r[8]
    } for r in rows]

@app.post("/api/admin/custom-providers")
async def add_custom_provider(req: CustomProviderRequest, authorization: str = Header(None)):
    """添加自定义厂商"""
    require_admin(authorization)
    pid = req.provider_id.strip()
    if not pid or not req.name.strip() or not req.api_base.strip():
        raise HTTPException(status_code=400, detail="厂商ID、名称、API地址不能为空")
    if pid in LLM_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"厂商ID {pid} 已存在于内置列表中")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT provider_id FROM custom_providers WHERE provider_id = ?", (pid,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail=f"厂商ID {pid} 已存在")
    
    models_json = json.dumps(req.models)
    cursor.execute("""
        INSERT INTO custom_providers (provider_id, name, api_base, api_key_env, icon, color, models, docs)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (pid, req.name.strip(), req.api_base.strip(), req.api_key_env, req.icon, req.color, models_json, req.docs))
    
    # 自动创建路由记录（极速/专家模型默认取models前两个）
    fast_model = req.models[0] if len(req.models) > 0 else ""
    expert_model = req.models[-1] if len(req.models) > 1 else fast_model
    cursor.execute("""
        INSERT OR IGNORE INTO model_routing (provider, name, fast, expert)
        VALUES (?, ?, ?, ?)
    """, (pid, req.name.strip(), fast_model, expert_model))
    
    conn.commit()
    conn.close()
    return {"success": True, "message": f"厂商 {req.name} 已添加，路由已自动创建"}

@app.put("/api/admin/custom-providers/{provider_id}")
async def update_custom_provider(provider_id: str, req: CustomProviderRequest, authorization: str = Header(None)):
    """修改自定义厂商"""
    require_admin(authorization)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT provider_id FROM custom_providers WHERE provider_id = ?", (provider_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="厂商不存在")
    
    models_json = json.dumps(req.models)
    cursor.execute("""
        UPDATE custom_providers SET name=?, api_base=?, api_key_env=?, icon=?, color=?, models=?, docs=?
        WHERE provider_id=?
    """, (req.name.strip(), req.api_base.strip(), req.api_key_env, req.icon, req.color, models_json, req.docs, provider_id))
    
    # 同步更新路由名称
    cursor.execute("UPDATE model_routing SET name=? WHERE provider=?", (req.name.strip(), provider_id))
    
    conn.commit()
    conn.close()
    return {"success": True, "message": f"厂商 {req.name} 已更新"}

@app.delete("/api/admin/custom-providers/{provider_id}")
async def delete_custom_provider(provider_id: str, authorization: str = Header(None)):
    """删除自定义厂商"""
    require_admin(authorization)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT provider_id FROM custom_providers WHERE provider_id = ?", (provider_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="厂商不存在")
    
    # 删除厂商、路由、API Key
    cursor.execute("DELETE FROM custom_providers WHERE provider_id = ?", (provider_id,))
    cursor.execute("DELETE FROM model_routing WHERE provider = ?", (provider_id,))
    cursor.execute("DELETE FROM api_keys WHERE provider = ?", (provider_id,))
    conn.commit()
    conn.close()
    return {"success": True, "message": f"厂商 {provider_id} 已删除"}

# ==================== 模型列表 ====================
@app.get("/api/models")
async def list_models():
    """列出所有可用模型"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT provider FROM api_keys WHERE enabled = 1")
    enabled_providers = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    result = []
    for model in ALL_MODELS:
        model_copy = model.copy()
        model_copy["available"] = model["provider"] in enabled_providers
        result.append(model_copy)
    
    return result

@app.get("/api/models/battle")
async def get_battle_models():
    """获取Battle Mode可用的模型池"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT provider FROM api_keys WHERE enabled = 1")
    enabled_providers = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    available = [m for m in BATTLE_MODELS if m["provider"] in enabled_providers]
    return available

# ==================== Battle Mode ====================
@app.post("/api/battle/start")
async def start_battle(request: BattleRequest):
    """开始Battle Mode - 随机选择两个模型"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT provider FROM api_keys WHERE enabled = 1")
    enabled_providers = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    # 筛选可用模型
    available = [m for m in BATTLE_MODELS if m["provider"] in enabled_providers]
    
    if len(available) < 2:
        raise HTTPException(status_code=400, detail="至少需要配置2个模型的API Key")
    
    # 随机选择两个不同的模型
    if request.model_a and request.model_b:
        model_a = next((m for m in available if m["id"] == request.model_a), None)
        model_b = next((m for m in available if m["id"] == request.model_b), None)
        if not model_a or not model_b:
            raise HTTPException(status_code=400, detail="指定的模型不可用")
    else:
        selected = random.sample(available, 2)
        model_a, model_b = selected[0], selected[1]
    
    return {
        "model_a": model_a,
        "model_b": model_b,
        "question": request.question
    }

@app.post("/api/battle/chat")
async def battle_chat(request: BattleRequest):
    """Battle Mode 聊天 - 同时调用两个模型"""
    # 获取模型配置
    model_a = next((m for m in ALL_MODELS if m["id"] == request.model_a), None)
    model_b = next((m for m in ALL_MODELS if m["id"] == request.model_b), None)
    
    if not model_a or not model_b:
        raise HTTPException(status_code=400, detail="模型不存在")
    
    # 获取API Keys
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT api_key, secret_key, app_id FROM api_keys WHERE provider = ?", (model_a["provider"],))
    key_a = cursor.fetchone()
    cursor.execute("SELECT api_key, secret_key, app_id FROM api_keys WHERE provider = ?", (model_b["provider"],))
    key_b = cursor.fetchone()
    conn.close()
    
    if not key_a or not key_b:
        raise HTTPException(status_code=400, detail="API Key未配置")
    
    # 并发调用两个模型
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        tasks = [
            call_llm(client, model_a, key_a[0], request.question, secret_key=key_a[1] or "", app_id=key_a[2] or ""),
            call_llm(client, model_b, key_b[0], request.question, secret_key=key_b[1] or "", app_id=key_b[2] or "")
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 保存Battle记录
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO battle_records (question, model_a, model_b, model_a_name, model_b_name, response_a, response_b)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        request.question,
        model_a["id"],
        model_b["id"],
        f"{model_a['provider_name']} {model_a['model']}",
        f"{model_b['provider_name']} {model_b['model']}",
        responses[0] if not isinstance(responses[0], Exception) else str(responses[0]),
        responses[1] if not isinstance(responses[1], Exception) else str(responses[1])
    ))
    battle_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return {
        "battle_id": battle_id,
        "response_a": responses[0] if not isinstance(responses[0], Exception) else None,
        "response_b": responses[1] if not isinstance(responses[1], Exception) else None,
        "error_a": str(responses[0]) if isinstance(responses[0], Exception) else None,
        "error_b": str(responses[1]) if isinstance(responses[1], Exception) else None
    }

@app.post("/api/battle/vote")
async def submit_vote(request: VoteRequest):
    """提交Battle投票"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE battle_records 
        SET winner = ?, reason = ?
        WHERE id = ?
    """, (request.winner, request.reason, request.battle_id))
    
    # 获取完整记录
    cursor.execute("""
        SELECT model_a_name, model_b_name, question, response_a, response_b, winner, reason
        FROM battle_records WHERE id = ?
    """, (request.battle_id,))
    row = cursor.fetchone()
    conn.commit()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Battle记录不存在")
    
    return {
        "success": True,
        "reveal": {
            "model_a_name": row[0],
            "model_b_name": row[1]
        },
        "record": {
            "question": row[2],
            "response_a": row[3],
            "response_b": row[4],
            "winner": row[5],
            "reason": row[6]
        }
    }

@app.get("/api/battle/stats")
async def get_battle_stats(authorization: str = Header(None)):
    """获取Battle统计数据"""
    require_admin(authorization)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 总数
    cursor.execute("SELECT COUNT(*) FROM battle_records")
    total = cursor.fetchone()[0]
    
    # 各模型胜率
    cursor.execute("""
        SELECT model_a_name, COUNT(*) as wins 
        FROM battle_records WHERE winner = 'A' 
        GROUP BY model_a_name
    """)
    a_wins = dict(cursor.fetchall())
    
    cursor.execute("""
        SELECT model_b_name, COUNT(*) as wins 
        FROM battle_records WHERE winner = 'B' 
        GROUP BY model_b_name
    """)
    b_wins = dict(cursor.fetchall())
    
    conn.close()
    
    # 合并胜率
    all_models = set(a_wins.keys()) | set(b_wins.keys())
    stats = []
    for model in all_models:
        wins = a_wins.get(model, 0) + b_wins.get(model, 0)
        stats.append({"model": model, "wins": wins})
    
    return {"total": total, "leaderboard": sorted(stats, key=lambda x: -x["wins"])}

@app.get("/api/battle/all")
async def get_all_battles(page: int = 1, page_size: int = 20, authorization: str = Header(None)):
    """获取所有Battle记录（分页）"""
    require_admin(authorization)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 获取总数
    cursor.execute("SELECT COUNT(*) FROM battle_records")
    total = cursor.fetchone()[0]
    
    # 获取分页数据
    offset = (page - 1) * page_size
    cursor.execute("""
        SELECT id, question, model_a, model_b, model_a_name, model_b_name,
               response_a, response_b, winner, reason, created_at
        FROM battle_records
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """, (page_size, offset))
    
    rows = cursor.fetchall()
    conn.close()
    
    records = []
    for row in rows:
        records.append({
            "id": row[0],
            "question": row[1],
            "model_a": row[2],
            "model_b": row[3],
            "model_a_name": row[4],
            "model_b_name": row[5],
            "response_a": row[6],
            "response_b": row[7],
            "winner": row[8],
            "reason": row[9],
            "created_at": row[10]
        })
    
    return {"records": records, "total": total, "page": page, "page_size": page_size}

@app.delete("/api/battle/{battle_id}")
async def delete_battle(battle_id: int, authorization: str = Header(None)):
    """删除Battle记录"""
    require_admin(authorization)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM battle_records WHERE id = ?", (battle_id,))
    conn.commit()
    conn.close()
    return {"success": True}

@app.get("/api/battle/{battle_id}")
async def get_battle_detail(battle_id: int, authorization: str = Header(None)):
    """获取Battle详情"""
    require_admin(authorization)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, question, model_a, model_b, model_a_name, model_b_name,
               response_a, response_b, winner, reason, created_at
        FROM battle_records WHERE id = ?
    """, (battle_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="记录不存在")
    
    return {
        "id": row[0],
        "question": row[1],
        "model_a": row[2],
        "model_b": row[3],
        "model_a_name": row[4],
        "model_b_name": row[5],
        "response_a": row[6],
        "response_b": row[7],
        "winner": row[8],
        "reason": row[9],
        "created_at": row[10]
    }

# ==================== LLM 调用 ====================
async def call_llm(client: httpx.AsyncClient, model: dict, api_key: str, question: str, think_mode: bool = False, secret_key: str = "", app_id: str = "") -> str:
    """调用LLM API，think_mode时请求返回思考过程"""
    provider_id = model["provider"]
    provider = LLM_PROVIDERS[provider_id]

    # 字节跳动：/responses 端点
    if provider_id == "byteDance":
        resp = await client.post(
            provider["api_base"],
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model["model"], "input": [{"role": "user", "content": [{"type": "input_text", "text": question}]}]}
        )
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("output", []):
            if item.get("type") == "message":
                for c in item.get("content", []):
                    if c.get("type") == "output_text":
                        return c["text"]
        return "（无内容）"

    
    # OpenAI兼容格式
    if provider.get("special") is None:
        messages = [{"role": "user", "content": question}]
        if think_mode:
            messages.insert(0, {"role": "system", "content": "Please show your step-by-step reasoning process inside <thinking>...</thinking> tags, then provide your final answer outside those tags."})
        response = await client.post(
            f"{provider['api_base']}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": model["model"],
                "messages": messages,
                "temperature": 0.7
            }
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
    
    # 百度文心（自有格式 - 需AK/SK换access_token）
    elif provider.get("special") == "baidu":
        # 如果提供了 secret_key，先用 AK/SK 换取 access_token
        if secret_key:
            try:
                token_resp = await client.post(
                    "https://aip.baidubce.com/oauth/2.0/token",
                    params={
                        "grant_type": "client_credentials",
                        "client_id": api_key,
                        "client_secret": secret_key
                    }
                )
                token_data = token_resp.json()
                access_token = token_data.get("access_token", api_key)
            except Exception:
                access_token = api_key
        else:
            access_token = api_key
        response = await client.post(
            f"{provider['api_base']}/{model['model']}?access_token={access_token}",
            json={"messages": [{"role": "user", "content": question}]}
        )
        response.raise_for_status()
        return response.json().get("result", "")
    
    # Anthropic（自有格式）
    elif provider.get("special") == "anthropic":
        response = await client.post(
            f"{provider['api_base']}/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            },
            json={
                "model": model["model"],
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": question}]
            }
        )
        response.raise_for_status()
        data = response.json()
        return data["content"][0]["text"]
    
    # 科大讯飞（Spark REST API）
    elif provider.get("special") == "xfyun":
        api_base = "https://spark-api-open.xf-yun.com/v1/chat/completions"
        # auth: Bearer <apiKey>:<apiSecret>
        auth_header = f"Bearer {api_key}:{secret_key}" if secret_key else f"Bearer {api_key}"
        response = await client.post(
            api_base,
            headers={"Authorization": auth_header, "Content-Type": "application/json"},
            json={"model": model["model"], "messages": [{"role": "user", "content": question}], "max_tokens": 2048}
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
    
    # 华为云（IAM AK/SK 鉴权 → 盘古模型）
    elif provider.get("special") == "huawei":
        # 1. 先用 AK/SK 换取 IAM token
        if not secret_key:
            raise HTTPException(status_code=400, detail="华为云需要 AK 和 SK")
        iam_resp = await client.post(
            "https://iam.cn-north-4.myhuaweicloud.com/v3/auth/tokens",
            json={
                "auth": {
                    "identity": {
                        "methods": ["hw_ak_sk"],
                        "hw_ak_sk": {"access": {"key": api_key}, "secret": {"key": secret_key}}
                    },
                    "scope": {"project": {"name": "cn-north-4"}}
                }
            }
        )
        iam_resp.raise_for_status()
        x_auth_token = iam_resp.headers.get("X-Subject-Token", "")
        if not x_auth_token:
            raise HTTPException(status_code=500, detail="华为IAM未返回Token")
        # 2. 用 IAM token 调用盘古模型
        response = await client.post(
            f"{provider['api_base']}/chat",
            headers={"X-Auth-Token": x_auth_token, "Content-Type": "application/json"},
            json={"model": model["model"], "messages": [{"role": "user", "content": question}]}
        )
        response.raise_for_status()
        data = response.json()
        return data.get("choices", [{}])[0].get("message", {}).get("content", response.text)
    
    # Google Gemini（自有格式）
    elif provider.get("special") == "google":
        resp = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model['model']}:generateContent?key={api_key}",
            headers={"Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": question}]}]}
        )
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    

    # Cohere（自有 v2 格式）
    elif provider.get("special") == "cohere":
        resp = await client.post(
            "https://api.cohere.ai/v2/chat",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model["model"], "messages": [{"role": "user", "content": question}]}
        )
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"][0]["text"]
    

    else:
        raise NotImplementedError(f"不支持的API格式: {model['provider']}")

# ==================== 流式响应（WebSocket）====================
@app.websocket("/ws/battle/{battle_id}")
async def websocket_battle(websocket: WebSocket, battle_id: int):
    """WebSocket流式响应"""
    await websocket.accept()
    
    try:
        while True:
            data = await websocket.receive_json()
            
            if data["type"] == "chat":
                # 处理聊天请求
                question = data["question"]
                model_a_id = data["model_a"]
                model_b_id = data["model_b"]
                
                # 发送开始信号
                await websocket.send_json({"type": "start"})
                
                # TODO: 实现流式调用
                
                # 发送结束信号
                await websocket.send_json({"type": "done"})
                
    except WebSocketDisconnect:
        pass

# ==================== 语音识别 API ====================
class SpeechToTextRequest(BaseModel):
    audio_base64: str
    model: str = "SenseVoiceSmall"

@app.post("/api/speech-to-text")
async def speech_to_text(request: SpeechToTextRequest):
    """
    语音识别 - 使用硅基流动 SenseVoice
    """
    SILICONFLOW_API_KEY = os.environ.get("SILICONFLOW_API_KEY", "")
    if not SILICONFLOW_API_KEY:
        raise HTTPException(status_code=503, detail="语音识别服务暂不可用")
    SILICONFLOW_API_URL = "https://api.siliconflow.cn/v1/audio/transcriptions"
    
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.post(
                SILICONFLOW_API_URL,
                headers={
                    "Authorization": f"Bearer {SILICONFLOW_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": request.model,
                    "file": request.audio_base64,
                    "response_format": "json"
                }
            )
            
            response.raise_for_status()
            result = response.json()
            
            return {
                "success": True,
                "text": result.get("text", ""),
                "model": request.model
            }
            
    except httpx.HTTPStatusError as e:
        error_detail = ""
        try:
            error_detail = e.response.json()
        except:
            error_detail = str(e)
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"语音识别API错误: {error_detail}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"语音识别失败: {str(e)}")



# ==================== 4模型竞技场 API（集成龙虾排名）====================
class Arena4Request(BaseModel):
    question: str
    mode: str = "fast"  # fast 或 expert
    think_mode: bool = False  # 透视模式

class Arena4VoteRequest(BaseModel):
    battle_id: int
    winner_label: str  # A/B/C/D/tie/both_bad
    worst_label: Optional[str] = None  # A/B/C/D (可选最差模型)
    winner_tags: Optional[List[str]] = []  # 获胜方DPO标签
    worst_tags: Optional[List[str]] = []  # 失败方DPO标签
    user_id: str = "anonymous"
    fingerprint: str = ""  # 浏览器指纹
    device_hash: str = ""  # 全端设备指纹Hash (Canvas+WebGL+Audio+IP)
    render_complete_time: float = 0
    user_click_time: float = 0
    scroll_depth: int = 0  # 0-100 滚动深度百分比
    mode: str = "fast"
    think_mode: bool = False  # 是否开启透视模式

class DpoTagsRequest(BaseModel):
    battle_id: int
    winner_label: str  # A/B/C/D
    worst_label: Optional[str] = None  # A/B/C/D
    winner_tags: List[str] = []  # 获胜方标签
    worst_tags: List[str] = []   # 失败方标签
    user_id: str = "anonymous"


@app.post("/api/arena/user-id")
async def get_arena_user_id(request: Request):
    """服务端签发user_id，前端必须调用此接口获取"""
    body = await request.json()
    fingerprint = body.get("fingerprint", "")
    ip = get_client_ip(request)
    user_id = issue_user_id(fingerprint, ip)
    log_audit("user_id_issued", user_id, ip, fingerprint[:32] if fingerprint else None)
    return {"user_id": user_id}


@app.post("/api/fingerprint/register")
async def register_fingerprint(request: Request):
    """
    注册设备指纹 (Axiom V-Verification)
    前端采集 Canvas+WebGL+Audio 指纹后提交，服务端绑定 user_id
    """
    body = await request.json()
    device_hash = body.get("device_hash", "")
    fingerprint = body.get("fingerprint", "")
    ip = get_client_ip(request)

    if not device_hash:
        return {"registered": False, "reason": "device_hash required"}

    # 签发 user_id
    user_id = issue_user_id(fingerprint, ip)

    # IP 子网提取 (取前3段)
    ip_parts = ip.split(".")
    ip_subnet = ".".join(ip_parts[:3]) + ".0" if len(ip_parts) >= 3 else ip

    # UA 核心特征
    ua = request.headers.get("user-agent", "")
    ua_core = ua[:80] if ua else ""

    # 注册设备指纹
    result = register_device(device_hash, user_id, ip_subnet, ua_core)

    # 检查设备额度
    device_quota = check_device_quota(device_hash)

    # 获取用户配额状态
    quota_status = get_quota_status(user_id)

    log_audit("fingerprint_registered", user_id, ip,
              detail=f"device_hash={device_hash[:16]}... overflow={result.get('overflow')}")

    return {
        "user_id": user_id,
        "registered": result["registered"],
        "device_overflow": result.get("overflow", False),
        "device_quota": device_quota,
        "user_quota": quota_status,
        "quota": {
            "blind_total": BLIND_QUOTA,
            "blind_remaining": quota_status["blind_remaining"],
            "think_total": THINK_QUOTA,
            "think_remaining": quota_status["think_remaining"]
        }
    }

@app.get("/api/arena/models")
async def get_arena_models():
    """获取4模型竞技场可用模型"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT provider FROM api_keys WHERE enabled = 1")
    enabled = {row[0] for row in cursor.fetchall()}
    conn.close()
    available = [m for m in BATTLE_MODELS if m["provider"] in enabled]
    return {"models": available}

@app.post("/api/arena/chat")
async def arena4_chat(request: Arena4Request, http_request: Request):
    """4模型竞技场 - 同时调用4个模型（盲测，返回匿名标签）"""
    import logging
    logger = logging.getLogger("uvicorn")

    # IP限流检查
    ip = get_client_ip(http_request)
    if not check_rate_limit(ip, "chat", RATE_LIMIT_MAX_REQUESTS):
        log_audit("rate_limited", ip=ip, detail="chat endpoint")
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # 优先使用赞助商API Key（按创建时间排序，先到先用）
    cursor.execute("SELECT provider, api_key, COALESCE(secret_key,''), COALESCE(app_id,'') FROM sponsors WHERE status='active' AND api_verified=1 ORDER BY created_at ASC")
    key_map = {}  # provider -> (api_key, secret_key, app_id)
    for row in cursor.fetchall():
        if row[0] not in key_map:
            key_map[row[0]] = (row[1], row[2] or "", row[3] or "")
    # 补充管理员配置的API Key（赞助商没有的provider才用）
    cursor.execute("SELECT provider, api_key, secret_key, app_id FROM api_keys WHERE enabled = 1")
    for row in cursor.fetchall():
        if row[0] not in key_map:
            key_map[row[0]] = (row[1], row[2] or "", row[3] or "")
    conn.close()
    # 过滤被健康检查禁用的模型
    disabled_models = get_disabled_models_set()
    available_providers = set(m["provider"] for m in BATTLE_MODELS if m["provider"] in key_map)
    available_ids = [m["id"] for m in BATTLE_MODELS if m["provider"] in key_map and (m["provider"], m["model"]) not in disabled_models]

    if len(available_providers) < 2:
        raise HTTPException(status_code=400, detail=f"需要至少2个不同厂商的API Key，当前{len(available_providers)}个")

    # 不足4个厂商时，用已有厂商的其他模型填充
    while len(available_providers) < 4:
        # 从已有厂商中循环取，添加它们的其他模型
        extra = [m["id"] for m in BATTLE_MODELS if m["provider"] in available_providers and m["id"] not in available_ids]
        if extra:
            available_ids.extend(extra)
        else:
            # 没有其他模型了，重复已有模型
            available_ids.extend(available_ids[:4 - len(available_ids)])
            break

    # ===== 自动路由引擎：意图识别 + 4槽位强制探索 =====
    mode = request.mode if request.mode in ("fast", "expert") else "fast"
    domain = auto_router.get_domain(request.question)
    logger.info(f"[AutoRouter] question domain={domain}")

    # 使用4槽位分层选择（最强兜底 / UCB动态 / observing灰度 / 爆冷）
    selected_ids = auto_router.select_with_exploration(
        available_ids, question=request.question, mode=mode
    )
    logger.info(f"[AutoRouter] selected: {selected_ids}")

    # 构建4个模型槽位（允许同厂商不同模型）
    model_slots = []
    used_indices = set()
    
    # 优先选selected_ids中的模型
    for mid in (selected_ids or []):
        for i, m in enumerate(BATTLE_MODELS):
            if m["id"] == mid and i not in used_indices:
                model_slots.append(m)
                used_indices.add(i)
                break
        if len(model_slots) == 4:
            break
    
    # 不够4个，从available_ids补充
    if len(model_slots) < 4:
        for mid in available_ids:
            for i, m in enumerate(BATTLE_MODELS):
                if m["id"] == mid and i not in used_indices:
                    model_slots.append(m)
                    used_indices.add(i)
                    break
            if len(model_slots) == 4:
                break
    
    # 仍不够4个，允许重复
    while len(model_slots) < 4 and model_slots:
        model_slots.append(model_slots[len(model_slots) % len(model_slots)])

    # 根据 mode 解析每个 model 应该使用的具体模型
    mode = request.mode if request.mode in ("fast", "expert") else "fast"
    models = []  # [(model_dict, api_key), ...]
    for m in model_slots[:4]:
        pid = m["provider"]
        resolved_model_name = resolve_model_for_mode(pid, mode)
        model_dict = {
            "id": f"{pid}:{resolved_model_name}",
            "provider": pid,
            "provider_name": LLM_PROVIDERS[pid]["name"],
            "model": resolved_model_name,
            "icon": LLM_PROVIDERS[pid]["icon"],
            "color": LLM_PROVIDERS[pid]["color"]
        }
        models.append((model_dict, key_map[pid]))

    logger.info(f"[Arena4] mode={mode} selected: {[m[0]['id'] for m in models]}")

    # 并发调用4个模型
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        tasks = [call_llm(client, m, k[0], request.question, request.think_mode, secret_key=k[1], app_id=k[2]) for m, k in models]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

    for i, (m, r) in enumerate(zip(models, responses)):
        if isinstance(r, Exception):
            logger.error(f"[Arena4] {m[0]['id']} FAILED: {type(r).__name__}: {str(r)[:100]}")
            # 实时熔断：记录失败到 model_discovery
            try:
                conn2 = sqlite3.connect(DB_PATH)
                cur2 = conn2.cursor()
                cur2.execute("""
                    INSERT OR IGNORE INTO model_discovery (provider, model_id, status, source, fail_count)
                    VALUES (?, ?, 'discovered', 'arena', 1)
                """, (m[0]["provider"], m[0]["model"]))
                cur2.execute("""
                    UPDATE model_discovery SET
                    last_checked = datetime('now'),
                    fail_count = fail_count + 1
                    WHERE provider = ? AND model_id = ?
                """, (m[0]["provider"], m[0]["model"]))
                cur2.execute("""
                    UPDATE model_discovery SET status = 'disabled'
                    WHERE provider = ? AND model_id = ? AND fail_count >= 3
                """, (m[0]["provider"], m[0]["model"]))
                conn2.commit()
                conn2.close()
            except Exception:
                pass
        else:
            logger.info(f"[Arena4] {m[0]['id']} OK: {r[:50]}...")
            # 成功则重置失败计数
            try:
                conn2 = sqlite3.connect(DB_PATH)
                cur2 = conn2.cursor()
                cur2.execute("""
                    UPDATE model_discovery SET fail_count = 0,
                    last_healthy = datetime('now'), status = 'verified'
                    WHERE provider = ? AND model_id = ?
                """, (m[0]["provider"], m[0]["model"]))
                conn2.commit()
                conn2.close()
            except Exception:
                pass

    # 自动分类问题
    category = classify_category(request.question)
    logger.info(f"[Arena4] category={category} for question: {request.question[:50]}")

    # 保存对局记录
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO arena4_battles (question, model_a, model_b, model_c, model_d, 
                                    response_a, response_b, response_c, response_d, mode, category)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        request.question,
        models[0][0]["id"],
        models[1][0]["id"],
        models[2][0]["id"],
        models[3][0]["id"],
        responses[0] if not isinstance(responses[0], Exception) else None,
        responses[1] if not isinstance(responses[1], Exception) else None,
        responses[2] if not isinstance(responses[2], Exception) else None,
        responses[3] if not isinstance(responses[3], Exception) else None,
        mode,
        category,
    ))
    battle_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # 返回盲测格式：不返回模型真名，只返回匿名标签 A/B/C/D 和 battle_id
    return {
        "battle_id": battle_id,
        "category": category,
        "category_name": CATEGORY_NAMES.get(category, category),
        "responses": [
            {"content": r if not isinstance(r, Exception) else None,
             "error": str(r) if isinstance(r, Exception) else None}
            for r in responses
        ]
    }

@app.post("/api/arena/vote")
async def arena4_vote(request: Arena4VoteRequest, http_request: Request):
    """记录投票并更新龙虾排名（含反作弊安全校验）"""
    ip = get_client_ip(http_request)
    user_id = request.user_id
    fingerprint = request.fingerprint

    # === 安全检查链 ===
    # 1. IP限流
    if not check_rate_limit(ip, "vote", RATE_LIMIT_VOTE_MAX):
        log_audit("rate_limited", user_id, ip, fingerprint[:32] if fingerprint else None, "vote endpoint")
        raise HTTPException(status_code=429, detail="投票过于频繁，请稍后再试")

    # 2. 重复投票检查
    conn_check = sqlite3.connect(DB_PATH)
    cc = conn_check.cursor()
    cc.execute("SELECT COUNT(*) FROM arena4_votes WHERE battle_id = ? AND user_id = ?",
              (request.battle_id, user_id))
    if cc.fetchone()[0] > 0:
        conn_check.close()
        log_audit("duplicate_vote", user_id, ip, None, f"battle_id={request.battle_id}")
        raise HTTPException(status_code=409, detail="你已对此对局投过票")
    conn_check.close()

    # 3. 投票冷却
    if not check_vote_cooldown(user_id):
        log_audit("cooldown", user_id, ip, fingerprint[:32] if fingerprint else None, "vote too fast")
        raise HTTPException(status_code=429, detail="请等待片刻再投票")

    # 3. 每日上限
    if not check_daily_limit(user_id, ip):
        log_audit("daily_limit", user_id, ip, fingerprint[:32] if fingerprint else None, "exceeded daily limit")
        raise HTTPException(status_code=429, detail="今日投票已达上限")

    # 5. 指纹校验
    if fingerprint and not validate_fingerprint(user_id, fingerprint, ip):
        log_audit("fingerprint_fail", user_id, ip, fingerprint[:32] if fingerprint else None, "fingerprint mismatch")
        raise HTTPException(status_code=403, detail="身份校验失败")

    # 5. 异常模式检测
    anomaly = detect_anomalous_pattern(user_id, ip)
    if anomaly:
        log_audit("anomaly_detected", user_id, ip, fingerprint[:32] if fingerprint else None, anomaly)
        raise HTTPException(status_code=403, detail="检测到异常行为，请稍后再试")

    # ===== 双轨额度检查 =====
    quota_result = check_and_consume_quota(user_id, is_think_mode=request.think_mode)
    is_valid_for_elo = quota_result["is_valid_for_elo"]
    if not is_valid_for_elo:
        log_audit("quota_exceeded", user_id, ip, fingerprint[:32] if fingerprint else None,
                  f"think_mode={request.think_mode} blind_remaining={quota_result['blind_remaining']}")

    # ===== 设备指纹封禁检查 =====
    if request.device_hash:
        if is_device_blocked(request.device_hash):
            log_audit("device_blocked", user_id, ip, request.device_hash[:16], "blocked device attempted vote")
            raise HTTPException(status_code=403, detail="设备已被系统风控封禁")
        device_quota_check = check_device_quota(request.device_hash)
        if not device_quota_check["allowed"]:
            log_audit("device_quota_exceeded", user_id, ip, request.device_hash[:16],
                      f"device votes={device_quota_check['votes_today']}")
            raise HTTPException(status_code=429, detail="设备今日投票已达上限")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 获取对局信息
    cursor.execute("""
        SELECT model_a, model_b, model_c, model_d, question, category, mode
        FROM arena4_battles WHERE id = ?
    """, (request.battle_id,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="对局不存在")
    
    model_a, model_b, model_c, model_d, question, battle_category, battle_mode = row
    all_models = [model_a, model_b, model_c, model_d]
    
    # 计算投票权重（诚意过滤）
    vote_weight = engine.compute_vote_weight(
        request.user_id,
        question,
        request.render_complete_time,
        request.user_click_time,
        request.scroll_depth
    )
    
    # 确定胜者模型ID
    winner_model = None
    if request.winner_label in ("A", "B", "C", "D"):
        winner_idx = ord(request.winner_label) - ord("A")
        winner_model = all_models[winner_idx] if winner_idx < len(all_models) else None
    
    # 使用对局记录中的 category（而非前端传的 mode）
    vote_category = battle_category or classify_category(question)

    # ===== 动态难度系数计算 (必须在 update_ratings 之前) =====
    # 查询现有投票分布 (不含当前票) 计算共识率
    cursor.execute("""
        SELECT winner_label, COUNT(*) as cnt FROM arena4_votes
        WHERE battle_id = ? AND winner_label IN ('A','B','C','D')
        GROUP BY winner_label ORDER BY cnt DESC LIMIT 1
    """, (request.battle_id,))
    top_row = cursor.fetchone()
    if top_row:
        cursor.execute("SELECT COUNT(*) FROM arena4_votes WHERE battle_id = ? AND winner_label IN ('A','B','C','D')", (request.battle_id,))
        total_v = cursor.fetchone()[0]
        # 计算加入当前票后的共识率
        future_votes = total_v + 1
        if request.winner_label == top_row[0]:
            consensus_rate = (top_row[1] + 1) / future_votes
        else:
            consensus_rate = max(top_row[1], 1) / future_votes
    else:
        consensus_rate = 1.0
    # D-Factor 映射: consensus=1.0→0.2, consensus≤0.25→3.0, 线性插值
    if consensus_rate >= 1.0:
        difficulty_factor = 0.2
    elif consensus_rate <= 0.25:
        difficulty_factor = 3.0
    else:
        difficulty_factor = round(1.0 + (1.0 - consensus_rate) * 2.67, 2)

    # 更新排名（仅高保真选票参与ELO计算）
    if is_valid_for_elo:
        # 1) 综合榜：所有对战都参与
        engine.update_ratings(
            request.battle_id,
            request.winner_label,
            all_models,
            vote_weight,
            mode="overall",
            worst_label=request.worst_label,
            difficulty_factor=difficulty_factor
        )
        # 2) 分类榜：仅当分类为 coding/writing 时更新对应子榜
        if vote_category in ("coding", "writing"):
            engine.update_ratings(
                request.battle_id,
                request.winner_label,
                all_models,
                vote_weight,
                mode=vote_category,
                worst_label=request.worst_label,
                difficulty_factor=difficulty_factor
            )
    else:
        logger.info(f"[Quota] vote is_valid_for_elo=False, skip ELO update. user={user_id} think_mode={request.think_mode}")

    # 记录投票
    cursor.execute("""
        INSERT INTO arena4_votes (battle_id, winner_label, winner_model, worst_label, user_id,
                                  render_complete_time, user_click_time, vote_weight, scroll_depth, mode, category,
                                  is_valid_for_elo, device_hash, is_think_enabled, task_difficulty_factor)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        request.battle_id,
        request.winner_label,
        winner_model,
        request.worst_label,
        request.user_id,
        request.render_complete_time,
        request.user_click_time,
        vote_weight,
        request.scroll_depth,
        battle_mode or "fast",
        vote_category,
        1 if is_valid_for_elo else 0,
        request.device_hash or "",
        1 if request.think_mode else 0,
        difficulty_factor
    ))

    # 更新 arena4_battles 难度统计
    cursor.execute("UPDATE arena4_battles SET total_votes = total_votes + 1, consensus_rate = ?, difficulty_factor = ? WHERE id = ?",
                   (round(consensus_rate, 4), difficulty_factor, request.battle_id))
    # 写入DPO标签矩阵
    worst_model = None
    if request.worst_label and request.worst_label in ("A", "B", "C", "D"):
        worst_idx = ord(request.worst_label) - ord("A")
        worst_model = all_models[worst_idx] if worst_idx < len(all_models) else None

    # 获取各模型回答内容
    cursor.execute("SELECT response_a, response_b, response_c, response_d FROM arena4_battles WHERE id=?", (request.battle_id,))
    resp_row = cursor.fetchone()
    resp_a, resp_b, resp_c, resp_d = (resp_row if resp_row else (None, None, None, None))

    # 获取领域标签
    domain = auto_router.get_domain(question) if question else "knowledge"
    vote_mode_for_dpo = battle_mode or "fast"  # 保留fast/expert用于DPO路由

    import json as _json
    cursor.execute("""
        INSERT INTO dpo_labels (battle_id, vote_id, question,
            model_a_id, model_a_response, model_b_id, model_b_response,
            model_c_id, model_c_response, model_d_id, model_d_response,
            winner_label, winner_model, winner_tags,
            worst_label, worst_model, worst_tags,
            domain, vote_weight, mode, category)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        request.battle_id, cursor.lastrowid, question,
        model_a, resp_a, model_b, resp_b,
        model_c, resp_c, model_d, resp_d,
        request.winner_label, winner_model, _json.dumps(request.winner_tags, ensure_ascii=False),
        request.worst_label, worst_model, _json.dumps(request.worst_tags, ensure_ascii=False),
        domain, vote_weight, vote_mode_for_dpo, vote_category
    ))

    # 查询赞助商品牌名
    brand_map = {}
    model_provider_map = {m["id"]: m["provider"] for m in BATTLE_MODELS}
    for mid in all_models:
        provider = model_provider_map.get(mid, "")
        if provider:
            c2 = sqlite3.connect(DB_PATH)
            cur2 = c2.cursor()
            cur2.execute("SELECT brand_name FROM sponsors WHERE provider=? AND status='active' AND api_verified=1 ORDER BY created_at ASC LIMIT 1", (provider,))
            r2 = cur2.fetchone()
            c2.close()
            if r2:
                brand_map[mid] = r2[0]
    
    conn.commit()
    # 更新设备指纹投票计数
    if request.device_hash:
        increment_device_vote(request.device_hash, user_id)
    conn.close()
    
    log_audit("vote", user_id, ip, fingerprint[:32] if fingerprint else None,
              f"bid={request.battle_id} cat={vote_category} win={request.winner_label} worst={request.worst_label} weight={vote_weight:.2f} D={difficulty_factor}")
    
    return {
        "success": True,
        "vote_weight": vote_weight,
        "is_valid_for_elo": is_valid_for_elo,
        "difficulty_factor": difficulty_factor,
        "quota": {
            "blind_remaining": quota_result["blind_remaining"],
            "think_remaining": quota_result["think_remaining"],
            "blind_quota": BLIND_QUOTA,
            "think_quota": THINK_QUOTA
        },
        "dpo_saved": True,
        "reveal": {
            "A": {"model_id": model_a, "sponsor_brand": brand_map.get(model_a, "")},
            "B": {"model_id": model_b, "sponsor_brand": brand_map.get(model_b, "")},
            "C": {"model_id": model_c, "sponsor_brand": brand_map.get(model_c, "")},
            "D": {"model_id": model_d, "sponsor_brand": brand_map.get(model_d, "")}
        }
    }

# ==================== DPO 数据导出 API ====================

@app.get("/api/dpo/export")
async def export_dpo(limit: int = 100, domain: str = None, mode: str = None, http_request: Request = None):
    """导出DPO微调数据集（限流）"""
    if http_request:
        ip = get_client_ip(http_request)
        if not check_rate_limit(ip, "dpo_export", 5):
            log_audit("rate_limited", ip=ip, detail="dpo_export")
            raise HTTPException(status_code=429, detail="导出请求过于频繁")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    query = "SELECT * FROM dpo_labels WHERE 1=1"
    params = []
    if domain:
        query += " AND domain=?"
        params.append(domain)
    if mode:
        query += " AND mode=?"
        params.append(mode)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(min(limit, 1000))
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    import json as _json
    dpo_dataset = []
    for row in rows:
        entry = {
            "battle_id": row["battle_id"],
            "question": row["question"],
            "models": {
                "A": {"id": row["model_a_id"], "response": row["model_a_response"]},
                "B": {"id": row["model_b_id"], "response": row["model_b_response"]},
                "C": {"id": row["model_c_id"], "response": row["model_c_response"]},
                "D": {"id": row["model_d_id"], "response": row["model_d_response"]},
            },
            "winner_label": row["winner_label"],
            "winner_model": row["winner_model"],
            "winner_tags": _json.loads(row["winner_tags"]) if row["winner_tags"] else [],
            "worst_label": row["worst_label"],
            "worst_model": row["worst_model"],
            "worst_tags": _json.loads(row["worst_tags"]) if row["worst_tags"] else [],
            "domain": row["domain"],
            "vote_weight": row["vote_weight"],
            "mode": row["mode"],
            "created_at": row["created_at"],
        }
        dpo_dataset.append(entry)
    
    return {"count": len(dpo_dataset), "data": dpo_dataset}

@app.get("/api/dpo/stats")
async def dpo_stats():
    """DPO标签统计"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM dpo_labels")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT domain, COUNT(*) FROM dpo_labels GROUP BY domain")
    by_domain = {r[0]: r[1] for r in cursor.fetchall()}
    conn.close()
    return {"total": total, "by_domain": by_domain}

# ==================== DPO 标签 API ====================

@app.post("/api/arena/dpo-tags")
async def submit_dpo_tags(request: DpoTagsRequest, http_request: Request):
    """提交结构化DPO标签（投票后的标签评价）"""
    import json as _json
    ip = get_client_ip(http_request)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT model_a, model_b, model_c, model_d, question, response_a, response_b, response_c, response_d FROM arena4_battles WHERE id = ?", (request.battle_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="对局不存在")
    model_a, model_b, model_c, model_d, question, resp_a, resp_b, resp_c, resp_d = row
    all_models = [model_a, model_b, model_c, model_d]
    winner_idx = ord(request.winner_label) - ord("A") if request.winner_label in "ABCD" else -1
    winner_model = all_models[winner_idx] if 0 <= winner_idx < len(all_models) else None
    worst_idx = ord(request.worst_label) - ord("A") if request.worst_label and request.worst_label in "ABCD" else -1
    worst_model = all_models[worst_idx] if 0 <= worst_idx < len(all_models) else None
    domain = auto_router.get_domain(question) if question else "knowledge"
    cursor.execute("INSERT INTO dpo_labels (battle_id, question, model_a_id, model_a_response, model_b_id, model_b_response, model_c_id, model_c_response, model_d_id, model_d_response, winner_label, winner_model, winner_tags, worst_label, worst_model, worst_tags, domain) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
        request.battle_id, question,
        model_a, resp_a or "", model_b, resp_b or "",
        model_c, resp_c or "", model_d, resp_d or "",
        request.winner_label, winner_model,
        _json.dumps(request.winner_tags, ensure_ascii=False),
        request.worst_label, worst_model,
        _json.dumps(request.worst_tags, ensure_ascii=False),
        domain
    ))
    conn.commit()
    conn.close()
    log_audit("dpo_tags", request.user_id, ip, None, f"bid={request.battle_id} win={request.winner_label} worst={request.worst_label}")
    return {"success": True, "message": "DPO标签已记录"}


@app.get("/api/arena/dpo/{battle_id}")
async def export_dpo_data(battle_id: int):
    """导出单局DPO数据"""
    import json as _json
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM dpo_labels WHERE battle_id = ? ORDER BY created_at DESC", (battle_id,))
    rows = cursor.fetchall()
    conn.close()
    records = []
    for row in rows:
        r = dict(row)
        r["winner_tags"] = _json.loads(r["winner_tags"]) if r.get("winner_tags") else []
        r["worst_tags"] = _json.loads(r["worst_tags"]) if r.get("worst_tags") else []
        records.append(r)
    return {"dpo_records": records}


@app.get("/api/arena/dpo-export/all")
async def export_all_dpo(http_request: Request):
    """导出全部DPO微调数据（限流）"""
    ip = get_client_ip(http_request)
    if not check_rate_limit(ip, "dpo_export_all", 2):
        log_audit("rate_limited", ip=ip, detail="dpo_export_all")
        raise HTTPException(status_code=429, detail="导出请求过于频繁")
    import json as _json
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM dpo_labels ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    records = []
    for row in rows:
        r = dict(row)
        r["winner_tags"] = _json.loads(r["winner_tags"]) if r.get("winner_tags") else []
        r["worst_tags"] = _json.loads(r["worst_tags"]) if r.get("worst_tags") else []
        records.append(r)
    return {"total": len(records), "dpo_records": records}


# ==================== 龙猫交叉验证 API ====================

class CrossValidateRequest(BaseModel):
    battle_id: int
    winner_label: str  # A/B/C/D
    worst_label: Optional[str] = None
    winner_tags: List[str] = []
    worst_tags: List[str] = []
    context_data: str = ""  # 可选: 搜索探针结果


@app.post("/api/arena/cross-validate")
async def cross_validate(request: CrossValidateRequest, http_request: Request):
    """龙猫交叉验证: 权重预处理 + LLM推理提纯 = 终极求真解"""
    import json as _json
    ip = get_client_ip(http_request)
    
    # 限流：每分钟最多3次交叉验证
    if not check_rate_limit(ip, "cross_validate", 3):
        log_audit("rate_limited", ip=ip, detail="cross_validate")
        raise HTTPException(status_code=429, detail="交叉验证请求过于频繁，请稍后重试")
    
    import logging; logger = logging.getLogger("uvicorn")
    logger.info(f"[Totoro] cross-validate battle_id={request.battle_id}")

    # 1. 权重预处理
    preprocessed = preprocess_cross_validation(
        DB_PATH, request.battle_id,
        request.winner_label, request.worst_label,
        request.winner_tags, request.worst_tags,
        request.context_data
    )
    if not preprocessed:
        raise HTTPException(status_code=404, detail="对局不存在")

    # 2. 组装龙猫消息
    messages = build_totoro_messages(preprocessed)

    # 3. 选择龙猫调用模型 (按优先级回退，自动重试)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT provider, api_key FROM api_keys WHERE enabled = 1")
    key_map = {row[0]: row[1] for row in cursor.fetchall()}
    conn.close()

    preferred_order = ["alibaba", "zhipu", "deepseek", "moonshot", "baichuan", "tencent", "stepfun", "byteDance"]
    candidate_providers = [pid for pid in preferred_order if pid in key_map]
    if not candidate_providers:
        raise HTTPException(status_code=500, detail="无可用API Key执行交叉验证")

    last_error = None
    for totoro_provider in candidate_providers:
        totoro_api_key = key_map[totoro_provider]
        totoro_model_name = resolve_model_for_mode(totoro_provider, "fast")
        provider_config = LLM_PROVIDERS[totoro_provider]
        try:
            async with httpx.AsyncClient(timeout=90.0, follow_redirects=True) as client:
                if provider_config.get("special") == "baidu":
                    resp = await client.post(
                        f"{provider_config['api_base']}/{totoro_model_name}?access_token={totoro_api_key}",
                        json={"messages": messages}
                    )
                elif totoro_provider == "byteDance":
                    resp = await client.post(
                        provider_config["api_base"],
                        headers={"Authorization": f"Bearer {totoro_api_key}", "Content-Type": "application/json"},
                        json={"model": totoro_model_name, "input": [{"role": "user", "content": [{"type": "input_text", "text": messages[-1]["content"]}]}]}
                    )
                else:
                    resp = await client.post(
                        f"{provider_config['api_base']}/chat/completions",
                        headers={"Authorization": f"Bearer {totoro_api_key}", "Content-Type": "application/json"},
                        json={
                            "model": totoro_model_name,
                            "messages": messages,
                            "temperature": 0.3
                        }
                    )
                resp.raise_for_status()
                data = resp.json()

            # 解析响应
            if totoro_provider == "byteDance":
                totoro_result = ""
                for item in data.get("output", []):
                    if item.get("type") == "message":
                        for c in item.get("content", []):
                            if c.get("type") == "output_text":
                                totoro_result += c["text"]
            elif provider_config.get("special") == "baidu":
                totoro_result = data.get("result", "")
            else:
                totoro_result = data["choices"][0]["message"]["content"]

            logger.info(f"[Totoro] provider={totoro_provider} model={totoro_model_name} len={len(totoro_result)}")
            break  # 成功，跳出循环

        except Exception as e:
            last_error = e
            logger.warning(f"[Totoro] provider={totoro_provider} failed: {e}, trying next...")
            continue
    else:
        # 所有 provider 都失败
        logger.error(f"[Totoro] all providers failed, last error: {last_error}")
        raise HTTPException(status_code=500, detail=f"交叉验证失败(已尝试{len(candidate_providers)}个提供商): {str(last_error)}")

    # 4. 解析 <终极求真解> 和 <交叉验证战报>
    refined_answer = totoro_result
    battle_report = ""
    if "<终极求真解>" in totoro_result:
        import re
        m1 = re.search(r'<终极求真解>(.*?)</终极求真解>', totoro_result, re.DOTALL)
        m2 = re.search(r'<交叉验证战报>(.*?)</交叉验证战报>', totoro_result, re.DOTALL)
        if m1:
            refined_answer = m1.group(1).strip()
        if m2:
            battle_report = m2.group(1).strip()

    # 5. 生成存证哈希
    from totoro import generate_proof_hash
    proof_hash = generate_proof_hash(
        request.battle_id,
        preprocessed["Question"],
        preprocessed["M1_to_M4_Answers"],
        preprocessed["Historical_Weights"],
        preprocessed["User_Signal"],
        refined_answer
    )

    # 6. 战报统计
    hallucination_count = 0
    if battle_report:
        import re as _re
        hallucination_count = len(_re.findall(r'幻觉|hallucination|熔断|剔除|舍弃|错误参数', battle_report, _re.IGNORECASE))

    total_input_chars = sum(len(v) for v in preprocessed["M1_to_M4_Answers"].values())
    output_chars = len(refined_answer)
    token_leverage = round(total_input_chars / max(output_chars, 1), 2)

    log_audit("cross_validate", "", ip, None, f"bid={request.battle_id} provider={totoro_provider} len={len(totoro_result)}")

    return {
        "success": True,
        "refined_answer": refined_answer,
        "battle_report": battle_report,
        "totoro_model": f"{totoro_provider}:{totoro_model_name}",
        "weights_used": preprocessed["Historical_Weights"],
        "user_signal_applied": preprocessed["User_Signal"],
        "proof_hash": proof_hash,
        "proof_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "hallucination_count": hallucination_count,
        "token_leverage": token_leverage,
        "question_summary": preprocessed["Question"][:80] + ("..." if len(preprocessed["Question"]) > 80 else ""),
    }


# ==================== 模型路由 API ====================

@app.get("/api/routing")
async def get_model_routing(authorization: str = Header(None)):
    """获取模型路由配置（需登录）"""
    require_admin(authorization)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT provider, name, fast, expert FROM model_routing ORDER BY provider")
    rows = cursor.fetchall()
    conn.close()
    routing = []
    for row in rows:
        routing.append({
            "provider": row[0],
            "name": row[1],
            "fast": row[2],
            "expert": row[3]
        })
    return {"routing": routing}

@app.put("/api/routing/{provider}")
async def update_model_routing(provider: str, fast: str = None, expert: str = None, authorization: str = Header(None)):
    """管理员修改某厂商的极速/专家模型映射（支持UPSERT）"""
    require_admin(authorization)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # 检查厂商是否存在（硬编码或自定义）
    is_builtin = provider in LLM_PROVIDERS
    cursor.execute("SELECT provider_id FROM custom_providers WHERE provider_id = ?", (provider,))
    is_custom = cursor.fetchone() is not None
    if not is_builtin and not is_custom:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Provider {provider} not found")
    
    # 确定name
    name = LLM_PROVIDERS[provider]["name"] if is_builtin else ""
    if not name:
        cursor.execute("SELECT name FROM custom_providers WHERE provider_id = ?", (provider,))
        row = cursor.fetchone()
        name = row[0] if row else provider
    
    # UPSERT
    cursor.execute("SELECT provider FROM model_routing WHERE provider = ?", (provider,))
    if cursor.fetchone():
        updates = []
        params = []
        if fast is not None:
            updates.append("fast = ?")
            params.append(fast)
        if expert is not None:
            updates.append("expert = ?")
            params.append(expert)
        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            sql = f"UPDATE model_routing SET {', '.join(updates)} WHERE provider = ?"
            params.append(provider)
            cursor.execute(sql, params)
    else:
        # 新建路由
        cursor.execute("INSERT INTO model_routing (provider, name, fast, expert) VALUES (?, ?, ?, ?)",
                      (provider, name, fast or "", expert or ""))
    conn.commit()
    conn.close()
    return {"success": True, "message": f"{provider} routing updated"}

from typing import List

@app.put("/api/routing")
async def batch_update_routing(routing_updates: List[dict], authorization: str = Header(None)):
    """管理员批量修改模型路由"""
    require_admin(authorization)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    for item in routing_updates:
        provider = item.get("provider")
        fast = item.get("fast")
        expert = item.get("expert")
        if provider and (fast or expert):
            cursor.execute(
                """UPDATE model_routing 
                   SET fast = COALESCE(?, fast), 
                       expert = COALESCE(?, expert),
                       updated_at = CURRENT_TIMESTAMP
                   WHERE provider = ?""",
                (fast, expert, provider)
            )
    conn.commit()
    conn.close()
    return {"success": True, "message": f"Updated {len(routing_updates)} routing entries"}


def resolve_model_for_mode(provider_id: str, mode: str) -> str:
    """根据 mode (fast/expert) 解析该 provider 应该使用的具体模型名"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT fast, expert FROM model_routing WHERE provider = ?", (provider_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        fast_model, expert_model = row
        if mode == "expert" and expert_model:
            return expert_model
        elif mode == "fast" and fast_model:
            return fast_model
        # 兜底：如果对应模式为空，用另一个模式
        return expert_model if mode == "fast" and not fast_model else fast_model
    # 兜底：如果路由表没有该 provider，用默认模型的第一个
    if provider_id in LLM_PROVIDERS:
        models = LLM_PROVIDERS[provider_id]["models"]
        return models[0] if models else "unknown"
    return "unknown"


@app.get("/api/arena/leaderboard")
async def get_arena_leaderboard(mode: str = "overall", month: str = ""):
    """获取龙虾排行榜（按category+月份分流，含中文名）
    mode参数: overall/coding/writing
    """
    cur_mode = mode if mode in ("overall", "coding", "writing") else "overall"
    # 构建 model_id -> 中文名 反向映射
    model_cn_map = {}
    for provider, info in MODEL_ROUTING.items():
        model_cn_map[info.get("fast", "")] = info.get("name", provider)
        model_cn_map[info.get("expert", "")] = info.get("name", provider)
    lb = engine.get_leaderboard(mode=cur_mode, month=month)
    for item in lb:
        item["cn_name"] = model_cn_map.get(item["model_id"], item["model_id"])
    return {"leaderboard": lb}

@app.get("/api/arena/stats")
async def get_arena_stats():
    """获取竞技场统计"""
    return engine.get_stats()

# ==================== 月度归档 API ====================

@app.get("/api/arena/categories")
async def get_categories():
    """获取可用分类列表及名称映射"""
    from category import CATEGORY_NAMES, CATEGORY_ICONS
    categories = []
    for key, name in CATEGORY_NAMES.items():
        categories.append({
            "key": key,
            "name": name,
            "icon": CATEGORY_ICONS.get(key, "")
        })
    return {"categories": categories}

@app.get("/api/arena/quota")
async def get_user_quota(http_request: Request):
    """查询当前用户的高保真额度状态"""
    fingerprint = http_request.query_params.get("fingerprint", "")
    ip = get_client_ip(http_request)
    user_id = issue_user_id(fingerprint, ip) if fingerprint else ip
    status = get_quota_status(user_id)
    return status

@app.post("/api/arena/archive")
async def archive_monthly(authorization: str = Header(None), month: str = ""):
    """管理员手动触发月度归档（快照+重置）"""
    require_admin(authorization)
    result = engine.archive_monthly_rankings(month=month)
    return {"success": True, **result}

@app.get("/api/arena/archives")
async def get_archives(month: str = "", mode: str = ""):
    """查询月度归档排行榜"""
    archives = engine.get_monthly_archives(month=month, mode=mode)
    return {"archives": archives}

@app.get("/api/arena/archives/months")
async def get_available_months():
    """获取所有有归档数据的月份"""
    months = engine.get_available_months()
    return {"months": months}

@app.delete("/api/arena/archives/month")
async def delete_archive(month: str = "", authorization: str = Header(None)):
    """管理员删除指定月份的归档记录（month通过query param传入）"""
    require_admin(authorization)
    if not month:
        raise HTTPException(status_code=400, detail="month parameter required")
    result = engine.delete_monthly_archive(month)
    return {"success": True, **result}

# ==================== 竞技场4模型对战记录管理 ====================

@app.get("/api/admin/arena4/battles")
async def admin_arena4_battles(
    page: int = 1,
    page_size: int = 20,
    model: str = "",
    provider: str = "",
    start_date: str = "",
    end_date: str = "",
    mode: str = "",
    authorization: str = Header(None)
):
    """管理后台：查询arena4对战记录（支持厂商/模型/时间/模式筛选）"""
    require_admin(authorization)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    where_clauses = []
    params = []
    
    if start_date:
        where_clauses.append("b.created_at >= ?")
        params.append(start_date)
    if end_date:
        where_clauses.append("b.created_at <= ?")
        params.append(end_date + " 23:59:59")
    if mode:
        where_clauses.append("b.mode = ?")
        params.append(mode)
    if model:
        where_clauses.append("(b.model_a = ? OR b.model_b = ? OR b.model_c = ? OR b.model_d = ?)")
        params.extend([model, model, model, model])
    if provider:
        # 根据厂商ID查找该厂商的所有模型，然后筛选
        provider_models = set()
        if provider in LLM_PROVIDERS:
            provider_models.update(LLM_PROVIDERS[provider]["models"])
        cursor.execute("SELECT models FROM custom_providers WHERE provider_id = ?", (provider,))
        crow = cursor.fetchone()
        if crow:
            provider_models.update(json.loads(crow[0]) if crow[0] else [])
        cursor.execute("SELECT fast, expert FROM model_routing WHERE provider = ?", (provider,))
        rrow = cursor.fetchone()
        if rrow:
            if rrow[0]: provider_models.add(rrow[0])
            if rrow[1]: provider_models.add(rrow[1])
        if provider_models:
            placeholders = ",".join(["?"] * len(provider_models))
            where_clauses.append(f"(b.model_a IN ({placeholders}) OR b.model_b IN ({placeholders}) OR b.model_c IN ({placeholders}) OR b.model_d IN ({placeholders}))")
            pml = list(provider_models)
            params.extend(pml * 4)
        else:
            where_clauses.append("1=0")
    
    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    
    # 总数
    cursor.execute(f"SELECT COUNT(*) FROM arena4_battles b {where_sql}", params)
    total = cursor.fetchone()[0]
    
    # 分页数据
    offset = (page - 1) * page_size
    cursor.execute(f"""
        SELECT b.id, b.question, b.model_a, b.model_b, b.model_c, b.model_d,
               b.response_a, b.response_b, b.response_c, b.response_d,
               b.mode, b.created_at
        FROM arena4_battles b
        {where_sql}
        ORDER BY b.created_at DESC
        LIMIT ? OFFSET ?
    """, params + [page_size, offset])
    
    rows = cursor.fetchall()
    
    battles = []
    for row in rows:
        battle_id = row[0]
        # 查询该battle的投票记录
        cursor.execute("""
            SELECT id, winner_label, winner_model, worst_label, user_id,
                   render_complete_time, user_click_time, vote_weight, scroll_depth, mode, created_at
            FROM arena4_votes WHERE battle_id = ?
        """, (battle_id,))
        vote_rows = cursor.fetchall()
        votes = []
        for v in vote_rows:
            votes.append({
                "id": v[0],
                "winner_label": v[1],
                "winner_model": v[2],
                "worst_label": v[3],
                "user_id": v[4],
                "render_complete_time": v[5],
                "user_click_time": v[6],
                "vote_weight": v[7],
                "scroll_depth": v[8],
                "mode": v[9],
                "created_at": v[10]
            })
        
        battles.append({
            "id": row[0],
            "question": row[1],
            "model_a": row[2],
            "model_b": row[3],
            "model_c": row[4],
            "model_d": row[5],
            "response_a": row[6],
            "response_b": row[7],
            "response_c": row[8],
            "response_d": row[9],
            "mode": row[10],
            "created_at": row[11],
            "votes": votes
        })
    
    conn.close()
    return {"battles": battles, "total": total, "page": page, "page_size": page_size}


@app.get("/api/admin/arena4/export")
async def admin_arena4_export(
    model: str = "",
    provider: str = "",
    start_date: str = "",
    end_date: str = "",
    mode: str = "",
    page: int = 1,
    page_size: int = 5000,
    authorization: str = Header(None)
):
    """管理后台：导出arena4对战记录为CSV（支持厂商筛选+分批导出）"""
    require_admin(authorization)
    import csv, io
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    where_clauses = []
    params = []
    
    if start_date:
        where_clauses.append("b.created_at >= ?")
        params.append(start_date)
    if end_date:
        where_clauses.append("b.created_at <= ?")
        params.append(end_date + " 23:59:59")
    if mode:
        where_clauses.append("b.mode = ?")
        params.append(mode)
    if model:
        where_clauses.append("(b.model_a = ? OR b.model_b = ? OR b.model_c = ? OR b.model_d = ?)")
        params.extend([model, model, model, model])
    if provider:
        provider_models = set()
        if provider in LLM_PROVIDERS:
            provider_models.update(LLM_PROVIDERS[provider]["models"])
        cursor.execute("SELECT models FROM custom_providers WHERE provider_id = ?", (provider,))
        crow = cursor.fetchone()
        if crow:
            provider_models.update(json.loads(crow[0]) if crow[0] else [])
        cursor.execute("SELECT fast, expert FROM model_routing WHERE provider = ?", (provider,))
        rrow = cursor.fetchone()
        if rrow:
            if rrow[0]: provider_models.add(rrow[0])
            if rrow[1]: provider_models.add(rrow[1])
        if provider_models:
            placeholders = ",".join(["?"] * len(provider_models))
            where_clauses.append(f"(b.model_a IN ({placeholders}) OR b.model_b IN ({placeholders}) OR b.model_c IN ({placeholders}) OR b.model_d IN ({placeholders}))")
            pml = list(provider_models)
            params.extend(pml * 4)
        else:
            where_clauses.append("1=0")
    
    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    
    # 总数
    cursor.execute(f"SELECT COUNT(*) FROM arena4_battles b {where_sql}", params)
    total = cursor.fetchone()[0]
    
    # 分批查询
    offset = (page - 1) * page_size
    cursor.execute(f"""
        SELECT b.id, b.question, b.model_a, b.model_b, b.model_c, b.model_d,
               b.response_a, b.response_b, b.response_c, b.response_d,
               b.mode, b.created_at
        FROM arena4_battles b
        {where_sql}
        ORDER BY b.created_at DESC
        LIMIT ? OFFSET ?
    """, params + [page_size, offset])
    
    rows = cursor.fetchall()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', '时间', '模式', '问题', 
                     '模型A', '模型B', '模型C', '模型D',
                     '回复A', '回复B', '回复C', '回复D',
                     '投票胜者标签', '投票胜者模型', '投票最差标签', '投票用户ID', '投票时间'])
    
    for row in rows:
        battle_id = row[0]
        base = [row[0], row[11], row[10], row[1], row[2], row[3], row[4], row[5],
                row[6], row[7], row[8], row[9]]
        
        cursor.execute("""
            SELECT winner_label, winner_model, worst_label, user_id, created_at
            FROM arena4_votes WHERE battle_id = ?
        """, (battle_id,))
        vote_rows = cursor.fetchall()
        
        if vote_rows:
            for v in vote_rows:
                writer.writerow(base + [v[0], v[1], v[2], v[3], v[4]])
        else:
            writer.writerow(base + ['无投票', '', '', '', ''])
    
    conn.close()
    
    output.seek(0)
    from fastapi.responses import StreamingResponse
    import codecs
    # UTF-8 BOM for Excel compatibility
    bom = codecs.BOM_UTF8.decode('utf-8')
    csv_content = bom + output.getvalue()
    
    filename = f"arena4_export_{start_date or 'all'}_{end_date or 'all'}_p{page}.csv"
    pages = (total + page_size - 1) // page_size
    return StreamingResponse(
        iter([csv_content.encode('utf-8-sig')]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "X-Total-Count": str(total),
            "X-Total-Pages": str(pages),
            "X-Current-Page": str(page),
            "X-Page-Size": str(page_size)
        }
    )


@app.get("/api/admin/arena4/models")
async def admin_arena4_models(authorization: str = Header(None)):
    """管理后台：获取所有出现过的模型列表（用于筛选）"""
    require_admin(authorization)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""SELECT DISTINCT model FROM (
        SELECT model_a as model FROM arena4_battles
        UNION SELECT model_b FROM arena4_battles
        UNION SELECT model_c FROM arena4_battles
        UNION SELECT model_d FROM arena4_battles
    ) WHERE model IS NOT NULL AND model != '' ORDER BY model""")
    models = [row[0] for row in cursor.fetchall()]
    conn.close()
    return {"models": models}

@app.get("/api/admin/arena4/providers-models")
async def admin_arena4_providers_models(authorization: str = Header(None)):
    """管理后台：获取厂商→模型级联结构（用于级联下拉筛选）"""
    require_admin(authorization)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 获取所有出现过的模型
    cursor.execute("""SELECT DISTINCT model FROM (
        SELECT model_a as model FROM arena4_battles
        UNION SELECT model_b FROM arena4_battles
        UNION SELECT model_c FROM arena4_battles
        UNION SELECT model_d FROM arena4_battles
    ) WHERE model IS NOT NULL AND model != ''""")
    all_battle_models = set(row[0] for row in cursor.fetchall())
    
    # 构建厂商→模型映射
    result = {}
    # 1. 从model_routing表获取厂商→模型
    cursor.execute("SELECT provider, name, fast, expert FROM model_routing")
    for row in cursor.fetchall():
        provider, pname, fast, expert = row
        models = []
        # 从battle数据中找属于该厂商的模型
        if fast and fast in all_battle_models:
            models.append(fast)
        if expert and expert in all_battle_models and expert != fast:
            models.append(expert)
        # 也检查该厂商的所有已知模型
        if provider in LLM_PROVIDERS:
            for m in LLM_PROVIDERS[provider]["models"]:
                if m in all_battle_models and m not in models:
                    models.append(m)
        cursor2 = conn.cursor()  # separate cursor
        cursor2.execute("SELECT models FROM custom_providers WHERE provider_id = ?", (provider,))
        crow = cursor2.fetchone()
        if crow:
            for m in json.loads(crow[0]) if crow[0] else []:
                if m in all_battle_models and m not in models:
                    models.append(m)
        if models:
            result[provider] = {"name": pname, "models": sorted(models)}
    
    # 2. 检查是否有battle中的模型不在任何厂商中
    assigned_models = set()
    for pdata in result.values():
        assigned_models.update(pdata["models"])
    unassigned = all_battle_models - assigned_models
    if unassigned:
        result["_other"] = {"name": "其他模型", "models": sorted(unassigned)}
    
    conn.close()
    return {"providers": result}

# 赞助商系统
from sponsor_api import router as sponsor_router
app.include_router(sponsor_router)

# ==================== 启动 ====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
