# -*- coding: utf-8 -*-
"""
LLM.中国 双轨额度系统 — 防疲劳 & 抗污染

核心逻辑：
- 每用户每日 5 次高保真盲测额度 (blind_quota)
- 透视模式(显示思考过程)每日仅 1 次有效票 (think_quota)
- 超额选票 is_valid_for_elo=False，正常返回成功但不计入排行榜
"""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "llm_china.db")

BLIND_QUOTA = 5      # 每日高保真盲测额度
THINK_QUOTA = 1      # 透视模式每日有效票额度


def _get_conn():
    return sqlite3.connect(DB_PATH)


def init_quota_tables():
    """创建额度追踪表（由 main.py init_db 调用）"""
    conn = _get_conn()
    c = conn.cursor()
    # 日级额度追踪表
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_daily_quota (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            date TEXT NOT NULL,
            blind_used INTEGER DEFAULT 0,
            think_used INTEGER DEFAULT 0,
            UNIQUE(user_id, date)
        )
    """)
    conn.commit()
    conn.close()


def check_and_consume_quota(user_id: str, is_think_mode: bool = False) -> dict:
    """
    检查并消耗额度，返回额度状态。

    Returns:
        {
            "allowed": bool,          # 是否允许投票（始终True，超额只降权）
            "is_valid_for_elo": bool,  # 是否计入排行榜
            "blind_remaining": int,    # 剩余盲测额度
            "think_remaining": int,    # 剩余透视额度
            "quota_type": str,         # "blind" | "think"
        }
    """
    today = datetime.now().strftime("%Y-%m-%d")
    conn = _get_conn()
    c = conn.cursor()

    # 获取或创建今日记录
    c.execute(
        "SELECT blind_used, think_used FROM user_daily_quota WHERE user_id=? AND date=?",
        (user_id, today)
    )
    row = c.fetchone()

    if row is None:
        c.execute(
            "INSERT INTO user_daily_quota (user_id, date, blind_used, think_used) VALUES (?,?,0,0)",
            (user_id, today)
        )
        conn.commit()
        blind_used, think_used = 0, 0
    else:
        blind_used, think_used = row

    if is_think_mode:
        # 透视模式：每日仅1次有效票
        think_remaining = max(THINK_QUOTA - think_used, 0)
        is_valid = think_used < THINK_QUOTA

        # 消耗透视额度
        c.execute(
            "UPDATE user_daily_quota SET think_used=think_used+1 WHERE user_id=? AND date=?",
            (user_id, today)
        )
        # 透视模式也消耗盲测额度
        c.execute(
            "UPDATE user_daily_quota SET blind_used=blind_used+1 WHERE user_id=? AND date=?",
            (user_id, today)
        )
        conn.commit()

        blind_remaining = max(BLIND_QUOTA - blind_used - 1, 0)
        return {
            "allowed": True,
            "is_valid_for_elo": is_valid,
            "blind_remaining": blind_remaining,
            "think_remaining": max(think_remaining - 1, 0),
            "quota_type": "think"
        }
    else:
        # 普通盲测模式
        blind_remaining = max(BLIND_QUOTA - blind_used, 0)
        is_valid = blind_used < BLIND_QUOTA

        c.execute(
            "UPDATE user_daily_quota SET blind_used=blind_used+1 WHERE user_id=? AND date=?",
            (user_id, today)
        )
        conn.commit()

        think_remaining = max(THINK_QUOTA - think_used, 0)
        return {
            "allowed": True,
            "is_valid_for_elo": is_valid,
            "blind_remaining": max(blind_remaining - 1, 0),
            "think_remaining": think_remaining,
            "quota_type": "blind"
        }


def get_quota_status(user_id: str) -> dict:
    """查询用户当前额度状态（不消耗额度）"""
    today = datetime.now().strftime("%Y-%m-%d")
    conn = _get_conn()
    c = conn.cursor()

    c.execute(
        "SELECT blind_used, think_used FROM user_daily_quota WHERE user_id=? AND date=?",
        (user_id, today)
    )
    row = c.fetchone()
    conn.close()

    if row is None:
        return {
            "blind_used": 0, "blind_remaining": BLIND_QUOTA,
            "think_used": 0, "think_remaining": THINK_QUOTA,
            "blind_quota": BLIND_QUOTA, "think_quota": THINK_QUOTA
        }

    blind_used, think_used = row
    return {
        "blind_used": blind_used,
        "blind_remaining": max(BLIND_QUOTA - blind_used, 0),
        "think_used": think_used,
        "think_remaining": max(THINK_QUOTA - think_used, 0),
        "blind_quota": BLIND_QUOTA,
        "think_quota": THINK_QUOTA
    }
