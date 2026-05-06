# -*- coding: utf-8 -*-
"""
龙猫 (Totoro) 交叉验证提纯引擎
加权共识算法 + LLM推理降维打击 -> 终极求真解
"""

import json
import sqlite3
import math
import time
import hashlib
from typing import Dict, List, Optional


# ==================== 权重预处理层 ====================

def score_to_weight(arena_score: float) -> float:
    """Arena Score -> 基准权重 (0.5 ~ 2.0), Sigmoid映射"""
    if arena_score <= 0:
        return 0.5
    normalized = (arena_score - 1000) / 200
    sigmoid = 1.0 / (1.0 + math.exp(-normalized))
    return 0.5 + sigmoid * 1.5


def get_historical_weights(db_path: str, model_ids: List[str], mode: str = "fast") -> Dict[str, float]:
    """从P-L排名获取历史基准权重"""
    cur_month = time.strftime("%Y-%m", time.localtime())
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    weights = {}
    for mid in model_ids:
        cursor.execute(
            "SELECT gamma, wins, losses, ties, impressions FROM model_ratings WHERE model_id=? AND mode=? AND month=?",
            (mid, mode, cur_month)
        )
        row = cursor.fetchone()
        if row:
            gamma, wins, losses, ties, impressions = row
            total = wins + losses + ties
            win_rate = wins / max(total, 1)
            arena_score = gamma * 100 + win_rate * 200
            weights[mid] = round(score_to_weight(arena_score), 3)
        else:
            weights[mid] = 0.8
    conn.close()
    return weights


def build_user_signal(winner_label: str, worst_label: Optional[str],
                      winner_tags: List[str], worst_tags: List[str]) -> Dict:
    """构建用户验真信号, 标签 -> 权重修饰符"""
    TAG_MODIFIERS = {
        # 获胜方标签: 乘法增益
        "factual_grounded": 2.0,
        "code_executable": 2.0,
        "strong_cot": 1.5,
        "perfect_follow": 1.5,
        # 失败方标签: 熔断系数
        "severe_hallucination": 0.0,
        "over_aligned": 0.3,
        "logical_flaws": 0.2,
        "format_breakdown": 0.3,
    }

    signal = {
        "winner": winner_label,
        "worst": worst_label,
        "winner_boost": {},
        "worst_melt": {},
    }
    for tag in winner_tags:
        if tag in TAG_MODIFIERS:
            signal["winner_boost"][tag] = TAG_MODIFIERS[tag]
    for tag in worst_tags:
        if tag in TAG_MODIFIERS:
            signal["worst_melt"][tag] = TAG_MODIFIERS[tag]
    return signal


def preprocess_cross_validation(
    db_path: str,
    battle_id: int,
    winner_label: str,
    worst_label: Optional[str],
    winner_tags: List[str],
    worst_tags: List[str],
    context_data: str = ""
) -> Optional[Dict]:
    """
    权重预处理: 组装龙猫引擎所需的全量输入JSON
    Returns: dict with M1_to_M4_Answers, Historical_Weights, User_Signal, Context_Data, Question
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT model_a, model_b, model_c, model_d, question, "
        "response_a, response_b, response_c, response_d, mode "
        "FROM arena4_battles WHERE id=?",
        (battle_id,)
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None

    model_a, model_b, model_c, model_d, question, resp_a, resp_b, resp_c, resp_d, mode = row
    model_ids = [model_a, model_b, model_c, model_d]
    responses = [resp_a or "", resp_b or "", resp_c or "", resp_d or ""]

    # 1. 四模型回答
    answers = {f"M{i+1}": responses[i] for i in range(4)}

    # 2. 历史排名权重 (model_id -> M1~M4 mapping)
    hist_weights = get_historical_weights(db_path, model_ids, mode or "fast")
    weight_map = {f"M{i+1}": hist_weights.get(model_ids[i], 0.8) for i in range(4)}

    # 3. 用户验真信号 (A/B/C/D -> M1~M4)
    winner_m = f"M{ord(winner_label) - ord('A') + 1}" if winner_label and winner_label in "ABCD" else winner_label
    worst_m = f"M{ord(worst_label) - ord('A') + 1}" if worst_label and worst_label in "ABCD" else worst_label
    user_signal = build_user_signal(winner_m, worst_m, winner_tags, worst_tags)

    return {
        "M1_to_M4_Answers": answers,
        "Historical_Weights": weight_map,
        "User_Signal": user_signal,
        "Context_Data": context_data,
        "Question": question,
    }


# ==================== 龙猫 System Prompt 引擎 ====================

TOTORO_SYSTEM_PROMPT = (
    "你现在是 LLM.中国 的最高交叉验证系统（代号：龙猫）。"
    "你的任务是对四个底层大模型（M1, M2, M3, M4）的回答进行事实提纯，"
    "输出唯一绝对准确的终极求真解。\n\n"
    "请严格执行以下 Scoring_Algorithm（加权共识算法）来评估各个信息点：\n\n"
    "1. 排名基准权重 (Base Rank)：每个模型提供的事实，默认乘以其后台排名权重（传入的 Historical_Weights）。\n\n"
    "2. 共识提及率 (Consensus Overlap)：如果一个核心数据点/逻辑块在 3 个以上的模型中被独立提及，"
    "该信息点置信度激增，权重直接叠加。\n\n"
    "3. 用户验真加持 (User Endorsement)：重点审查用户投票胜出的模型（User_Signal）。"
    "如果用户为其打上了 [事实严谨/无幻觉] 或 [代码/格式零报错] 的标签，"
    "该模型的特有参数或核心代码块权重乘 2.0 采纳。"
    "如果是 [严重事实幻觉] 标签指出的失败方，其特有信息直接执行熔断丢弃。\n\n"
    "4. 依据参数校验 (Evidence Check)：扫描每个模型的回答。"
    "带有确切数值、API 参数、或能与外部真实上下文（Context_Data）完全对齐的信息，"
    "优先级最高；泛泛而谈的废话、缺乏引用的理论，强制剔除。\n\n"
    "输出执行协议：\n"
    "你必须且只能输出两部分内容：\n"
    "1. <终极求真解>：直接输出提纯后的完美答案、可执行代码或精确结论。去伪存真，极度精简，不需要任何开场白。\n"
    "2. <交叉验证战报>：用极简的要点说明（数据流说话）：为什么采用这个答案？"
    "（例如：交叉比对了 M1 和 M3 的共识数据，并结合高优评级剔除了 M4 的幻觉参数）。\n"
)


def build_totoro_messages(preprocessed_data: Dict) -> List[Dict]:
    """组装龙猫引擎的完整消息列表 (system + user)"""
    user_content = (
        "<Input_Data>\n"
        "<Question>{question}</Question>\n\n"
        "<M1_to_M4_Answers>\n{answers}\n</M1_to_M4_Answers>\n\n"
        "<Historical_Weights>\n{weights}\n</Historical_Weights>\n\n"
        "<User_Signal>\n{signal}\n</User_Signal>\n\n"
        "<Context_Data>\n{context}\n</Context_Data>\n"
        "</Input_Data>"
    ).format(
        question=preprocessed_data["Question"],
        answers=json.dumps(preprocessed_data["M1_to_M4_Answers"], ensure_ascii=False, indent=2),
        weights=json.dumps(preprocessed_data["Historical_Weights"], ensure_ascii=False, indent=2),
        signal=json.dumps(preprocessed_data["User_Signal"], ensure_ascii=False, indent=2),
        context=preprocessed_data["Context_Data"] or "无外部上下文",
    )

    return [
        {"role": "system", "content": TOTORO_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


# ==================== 哈希存证 ====================

def generate_proof_hash(
    battle_id: int,
    question: str,
    answers: Dict[str, str],
    weights: Dict[str, float],
    user_signal: Dict,
    refined_answer: str,
    timestamp: Optional[str] = None
) -> str:
    """
    生成SHA-256存证哈希, 唯一确权不可篡改
    """
    if not timestamp:
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    
    proof_payload = json.dumps({
        "battle_id": battle_id,
        "question": question,
        "answers": answers,
        "weights": weights,
        "user_signal": user_signal,
        "refined_answer": refined_answer,
        "timestamp": timestamp,
    }, ensure_ascii=False, sort_keys=True)
    
    return hashlib.sha256(proof_payload.encode("utf-8")).hexdigest()
