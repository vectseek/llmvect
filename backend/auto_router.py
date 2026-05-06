# -*- coding: utf-8 -*-
"""
自动路由引擎 - 带强制探索机制的4槽位分层选择

槽位1: 最强兜底 - 该领域评分最高模型
槽位2: 动态挑战 - UCB算法兼顾胜率+低曝光
槽位3: 随机灰度 - observing状态模型中随机1个
槽位4: 强制爆冷 - 胜率垫底30%模型中随机1个
"""

import math
import random
import re
import sqlite3
from typing import Dict, List, Optional, Tuple


# ==================== 意图分类器 ====================

INTENT_RULES = {
    "code": {
        "keywords": [
            "代码", "编程", "函数", "bug", "debug", "API", "接口", "算法",
            "程序", "脚本", "编译", "运行", "报错", "异常", "报错",
            "python", "java", "javascript", "typescript", "golang", "rust",
            "c++", "cpp", "html", "css", "sql", "shell", "bash",
            "实现", "开发", "部署", "重构", "优化代码",
            "how to implement", "write code", "code review",
            "function", "class", "method", "variable", "import",
        ],
        "patterns": [
            r"写[一个|段|个].*(代码|函数|程序|脚本|类|算法)",
            r"(如何|怎么).*(实现|开发|编写|部署)",
            r"(bug|error|exception|traceback)",
            r"```",
            r"(def |class |func |function |import |from )",
            r"(帮我写|给我写).*(算法|代码|函数|程序)",
        ],
    },
    "logic": {
        "keywords": [
            "推理", "逻辑", "证明", "数学", "计算", "分析", "推导",
            "概率", "统计", "公式", "定理", "方程", "求解",
            "思考", "判断", "论证", "辩证",
            "math", "logic", "reasoning", "proof", "calculate",
            "prove", "derive", "equation", "theorem",
        ],
        "patterns": [
            r"(证明|推导|计算|求解).*(定理|公式|方程)",
            r"(如果|假设|已知).*(那么|则|求)",
            r"(\d+\s*[+\-*/^=]\s*\d+)",
        ],
    },
    "creative": {
        "keywords": [
            "写", "创作", "故事", "小说", "诗", "歌词", "文案",
            "创意", "想象", "虚构", "角色", "剧情", "对话",
            "广告", "营销", "slogan", "标语", "品牌",
            "write", "create", "story", "poem", "creative", "imagine",
            "fiction", "novel", "song", "lyrics",
        ],
        "patterns": [
            r"(写|创作|编).*(故事|小说|诗|歌词|文案|文章)",
            r"(帮我想|给我写|帮我写)(?!.*(?:代码|函数|程序|算法|开发|实现|排序))",
        ],
    },
    "knowledge": {
        "keywords": [
            "什么是", "解释", "介绍", "定义", "概念", "原理",
            "历史", "背景", "原因", "区别", "对比", "分类",
            "how", "what", "why", "explain", "describe", "define",
            "difference", "compare", "introduction",
        ],
        "patterns": [
            r"(什么是|什么叫|解释一下|介绍一下)",
            r"(和|与|跟).*(区别|不同|差异|对比)",
            r"(为什么|为何|原因|缘由)",
        ],
    },
}


def classify_intent(question: str) -> str:
    """
    轻量意图分类器：基于关键词+正则，零外部依赖，毫秒级响应
    
    Returns:
        领域标签: code / logic / creative / knowledge
    """
    q_lower = question.lower()
    scores = {}

    for domain, rules in INTENT_RULES.items():
        score = 0.0
        # 关键词匹配
        for kw in rules["keywords"]:
            if kw.lower() in q_lower:
                score += 1.0
        # 正则匹配（权重更高）
        for pattern in rules["patterns"]:
            if re.search(pattern, question, re.IGNORECASE):
                score += 2.0
        scores[domain] = score

    # 无明确意图时默认knowledge
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "knowledge"

    return best


# ==================== 4槽位分层选择引擎 ====================

class AutoRouter:
    """带强制探索机制的自动路由引擎"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _get_ratings(self, model_ids: List[str], mode: str = "fast") -> Dict[str, dict]:
        """批量获取模型评分数据"""
        conn = self._get_conn()
        cursor = conn.cursor()
        ratings = {}
        for mid in model_ids:
            cursor.execute(
                "SELECT * FROM model_ratings WHERE model_id=? AND mode=? AND month=''",
                (mid, mode)
            )
            row = cursor.fetchone()
            if row:
                ratings[mid] = dict(row)
            else:
                # 新模型默认值
                ratings[mid] = {
                    "model_id": mid,
                    "gamma": 1.0,
                    "wins": 0,
                    "losses": 0,
                    "ties": 0,
                    "impressions": 0,
                    "status": "observing",
                }
        conn.close()
        return ratings

    def _win_rate(self, r: dict) -> float:
        """计算胜率"""
        total = r.get("wins", 0) + r.get("losses", 0) + r.get("ties", 0)
        if total == 0:
            return 0.5  # 未知模型默认0.5
        return r.get("wins", 0) / total

    def _ucb_score(self, r: dict, total_impressions: int) -> float:
        """计算UCB-E分数"""
        if r.get("impressions", 0) == 0:
            return 10.0  # 未曝光模型最高探索权重
        exploration = 1.0 * math.sqrt(
            math.log(max(total_impressions, 1)) / r["impressions"]
        )
        return r.get("gamma", 1.0) + exploration

    def select_with_exploration(
        self,
        available_models: List[str],
        question: str = "",
        mode: str = "fast",
    ) -> List[str]:
        """
        4槽位强制探索选择

        Args:
            available_models: 可选模型ID列表（已过滤有API key的）
            question: 用户问题（用于意图识别）
            mode: fast/expert

        Returns:
            选中的4个模型ID列表
        """
        if len(available_models) <= 4:
            return available_models[:]

        # 1. 意图识别
        domain = classify_intent(question) if question else "knowledge"

        # 2. 获取评分
        ratings = self._get_ratings(available_models, mode=mode)
        total_impressions = sum(r.get("impressions", 0) for r in ratings.values())

        # 按provider去重准备（每个provider只留最佳模型）
        provider_map = {}  # provider -> best model_id
        for mid in available_models:
            pid = mid.split(":")[0]
            if pid not in provider_map:
                provider_map[pid] = mid

        # 为每个provider选代表模型（用该provider下评分最高的）
        provider_representatives = {}
        for pid, mid in provider_map.items():
            provider_representatives[pid] = mid

        # 候选池：每个provider一个代表
        candidates = list(provider_representatives.values())

        if len(candidates) < 4:
            # provider不够4个，直接返回
            return candidates[:4]

        # 3. 四槽位选择
        selected = []
        used_providers = set()

        # --- 槽位1：最强兜底 ---
        best_mid = max(candidates, key=lambda m: ratings[m].get("gamma", 1.0))
        selected.append(best_mid)
        used_providers.add(best_mid.split(":")[0])

        # --- 槽位2：动态挑战（UCB） ---
        remaining = [m for m in candidates if m.split(":")[0] not in used_providers]
        if remaining:
            ucb_scores = {m: self._ucb_score(ratings[m], total_impressions) for m in remaining}
            # 加权随机：UCB分数越高被选中概率越大，但不保证最高
            total_ucb = sum(ucb_scores.values())
            if total_ucb > 0:
                r = random.random() * total_ucb
                cumsum = 0
                chosen = remaining[-1]
                for m in remaining:
                    cumsum += ucb_scores[m]
                    if cumsum >= r:
                        chosen = m
                        break
            else:
                chosen = random.choice(remaining)
            selected.append(chosen)
            used_providers.add(chosen.split(":")[0])

        # --- 槽位3：随机灰度（observing模型） ---
        remaining = [m for m in candidates if m.split(":")[0] not in used_providers]
        observing = [m for m in remaining if ratings[m].get("status", "active") == "observing"]
        if observing:
            chosen = random.choice(observing)
        elif remaining:
            chosen = random.choice(remaining)
        else:
            # 所有provider都用完了，从已选的里面换
            chosen = None
        if chosen:
            selected.append(chosen)
            used_providers.add(chosen.split(":")[0])

        # --- 槽位4：强制爆冷（胜率垫底30%） ---
        remaining = [m for m in candidates if m.split(":")[0] not in used_providers]
        if remaining:
            # 按胜率排序
            sorted_by_wr = sorted(remaining, key=lambda m: self._win_rate(ratings[m]))
            # 取垫底30%
            bottom_count = max(1, len(sorted_by_wr) // 3)
            bottom_pool = sorted_by_wr[:bottom_count]
            chosen = random.choice(bottom_pool)
            selected.append(chosen)
            used_providers.add(chosen.split(":")[0])

        # 如果不足4个（provider不够），从remaining补充
        if len(selected) < 4:
            remaining = [m for m in candidates if m.split(":")[0] not in used_providers]
            for m in remaining:
                if len(selected) >= 4:
                    break
                selected.append(m)
                used_providers.add(m.split(":")[0])

        return selected[:4]

    def get_domain(self, question: str) -> str:
        """公开接口：获取问题领域标签"""
        return classify_intent(question)
