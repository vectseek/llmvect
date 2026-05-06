# -*- coding: utf-8 -*-
"""
LLM.中国 全端设备指纹与防女巫攻击体系 (Anti-Sybil Identity)

核心逻辑：
- 前端采集 Canvas/WebGL/AudioContext 指纹 + IP 子网 → 生成 Device_Hash
- Device_Hash 绑定 user_id，实现设备级额度锁定
- 同一 Device_Hash 最多绑定 3 个 user_id（防多账号绕过）
- 清除缓存/无痕模式不影响（硬件特征不变则 Device_Hash 不变）
"""
import sqlite3
import hashlib
import time
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "llm_china.db")

# 同一设备指纹最多绑定 user_id 数量
MAX_USERS_PER_DEVICE = 3

# 同一设备指纹 24h 内最多投票数（防并发放大）
MAX_VOTES_PER_DEVICE_DAY = 30


def _get_conn():
    return sqlite3.connect(DB_PATH)


def init_fingerprint_tables():
    """创建设备指纹注册表（由 main.py init_db 调用）"""
    conn = _get_conn()
    c = conn.cursor()
    # 设备指纹注册表
    c.execute("""
        CREATE TABLE IF NOT EXISTS device_fingerprints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_hash TEXT NOT NULL,
            user_id TEXT NOT NULL,
            ip_subnet TEXT DEFAULT '',
            ua_core TEXT DEFAULT '',
            first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
            last_active TEXT DEFAULT CURRENT_TIMESTAMP,
            vote_count INTEGER DEFAULT 0,
            is_blocked INTEGER DEFAULT 0,
            UNIQUE(device_hash, user_id)
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_device_hash ON device_fingerprints(device_hash)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_device_user ON device_fingerprints(user_id)")
    conn.commit()
    conn.close()


def register_device(device_hash: str, user_id: str, ip_subnet: str = "", ua_core: str = "") -> dict:
    """
    注册/更新设备指纹绑定。
    如果设备已被封禁，返回 blocked=True。
    如果设备绑定的 user_id 数超限，返回 overflow=True。
    """
    if not device_hash or len(device_hash) < 8:
        return {"registered": False, "reason": "device_hash too short"}

    conn = _get_conn()
    c = conn.cursor()

    # 检查是否被封禁
    c.execute("SELECT is_blocked FROM device_fingerprints WHERE device_hash = ? AND is_blocked = 1 LIMIT 1",
              (device_hash,))
    if c.fetchone():
        conn.close()
        return {"registered": False, "reason": "device blocked", "blocked": True}

    # 尝试插入或更新
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        c.execute("""
            INSERT INTO device_fingerprints (device_hash, user_id, ip_subnet, ua_core, first_seen, last_active)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (device_hash, user_id, ip_subnet, ua_core, now, now))
        conn.commit()
    except sqlite3.IntegrityError:
        # 已存在，更新 last_active
        c.execute("""
            UPDATE device_fingerprints SET last_active = ?, ip_subnet = ?, ua_core = ?
            WHERE device_hash = ? AND user_id = ?
        """, (now, ip_subnet, ua_core, device_hash, user_id))
        conn.commit()

    # 检查该设备绑定的 user_id 数量
    c.execute("SELECT COUNT(DISTINCT user_id) FROM device_fingerprints WHERE device_hash = ?",
              (device_hash,))
    user_count = c.fetchone()[0]

    if user_count > MAX_USERS_PER_DEVICE:
        conn.close()
        return {"registered": True, "overflow": True, "user_count": user_count,
                "warning": f"Device bound to {user_count} users, exceeding limit {MAX_USERS_PER_DEVICE}"}

    conn.close()
    return {"registered": True, "overflow": False, "user_count": user_count}


def check_device_quota(device_hash: str) -> dict:
    """
    检查设备指纹的每日投票配额。
    返回 {"allowed": bool, "votes_today": int, "remaining": int}
    """
    if not device_hash:
        return {"allowed": True, "votes_today": 0, "remaining": MAX_VOTES_PER_DEVICE_DAY}

    today = datetime.now().strftime("%Y-%m-%d")
    conn = _get_conn()
    c = conn.cursor()

    # 查询该设备今日投票数（通过 user_daily_quota JOIN device_fingerprints）
    c.execute("""
        SELECT COALESCE(SUM(q.blind_used), 0)
        FROM user_daily_quota q
        JOIN device_fingerprints d ON d.user_id = q.user_id
        WHERE d.device_hash = ? AND q.date = ?
    """, (device_hash, today))
    votes_today = c.fetchone()[0]
    conn.close()

    remaining = max(MAX_VOTES_PER_DEVICE_DAY - votes_today, 0)
    return {"allowed": votes_today < MAX_VOTES_PER_DEVICE_DAY, "votes_today": votes_today, "remaining": remaining}


def is_device_blocked(device_hash: str) -> bool:
    """检查设备指纹是否被封禁"""
    if not device_hash:
        return False
    conn = _get_conn()
    c = conn.cursor()
    c.execute("SELECT is_blocked FROM device_fingerprints WHERE device_hash = ? AND is_blocked = 1 LIMIT 1",
              (device_hash,))
    blocked = c.fetchone() is not None
    conn.close()
    return blocked


def block_device(device_hash: str, reason: str = "") -> bool:
    """封禁设备指纹（管理操作）"""
    conn = _get_conn()
    c = conn.cursor()
    c.execute("UPDATE device_fingerprints SET is_blocked = 1 WHERE device_hash = ?", (device_hash,))
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0


def increment_device_vote(device_hash: str, user_id: str):
    """投票后递增设备投票计数"""
    conn = _get_conn()
    c = conn.cursor()
    c.execute("""
        UPDATE device_fingerprints SET vote_count = vote_count + 1, last_active = CURRENT_TIMESTAMP
        WHERE device_hash = ? AND user_id = ?
    """, (device_hash, user_id))
    conn.commit()
    conn.close()
