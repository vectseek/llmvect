# -*- coding: utf-8 -*-
"""
龙虾排名引擎 - Plackett-Luce + UCB-E 曝光控制 + 反作弊诚意过滤
"""

import math
import random
import sqlite3
import time
from typing import Dict, List, Optional, Tuple

# ==================== 常量 ====================
BASE_K = 32              # 基础分值（类似Elo的K因子）
BASE_SCORE = 1200        # Arena Score 基准分
INITIAL_GAMMA = 1.0      # 初始实力值 γ
MIN_GAMMA = 0.01         # γ 下限，防止除零

# UCB-E 参数
UCB_EXPLORATION = 0.5    # 探索系数 c
ELIMINATION_THRESHOLD = 0.15   # 自动淘汰胜率阈值
MIN_IMPRESSIONS_ELIM = 20      # 淘汰所需最少曝光次数
OBSERVATION_POOL_RATE = 0.05   # 灰度复出抽检概率

# 诚意过滤参数
MIN_DWELL_TIME = 2.0     # 最小停留时间（秒），低于此权重为0
DWELL_LOW_FACTOR = 0.8   # 用户均值乘以此值为权重下限
DWELL_HIGH_FACTOR = 1.5  # 用户均值乘以此值为权重上限
MAX_VOTE_WEIGHT = 1.5    # 最大投票权重
MIN_VOTE_WEIGHT = 0.3    # 最小投票权重(非零)

# 重算触发阈值
RECALC_TRIGGER = 100     # 每100次点击触发全局重算


# ==================== ModelRating 数据类 ====================
class ModelRating:
    """模型评分数据"""
    def __init__(self, model_id: str, mode: str = "fast", month: str = ""):
        self.model_id = model_id
        self.mode = mode              # fast / expert
        self.month = month or time.strftime("%Y-%m", time.localtime())
        self.gamma = INITIAL_GAMMA    # Plackett-Luce 实力值
        self.wins = 0
        self.losses = 0
        self.ties = 0
        self.impressions = 0
        self.last_active_time: Optional[str] = None
        self.status = "active"        # active / observing / eliminated

    @property
    def total_games(self) -> int:
        return self.wins + self.losses + self.ties

    @property
    def win_rate(self) -> float:
        if self.total_games == 0:
            return 0.0
        return self.wins / self.total_games

    def get_arena_score(self) -> float:
        """将 γ 转为可读的 Arena Score (AS)"""
        # AS = BASE_SCORE + 400 * log10(γ)
        # γ=1 → 1200, γ=2 → ~1320, γ=0.5 → ~1080
        return BASE_SCORE + 400.0 * math.log10(max(self.gamma, MIN_GAMMA))

    def get_confidence(self) -> float:
        """基于曝光次数计算置信区间（标准差估计）"""
        if self.impressions < 5:
            return 200.0  # 极低置信度
        if self.impressions < 20:
            return 100.0
        if self.impressions < 50:
            return 50.0
        if self.impressions < 200:
            return 25.0
        return 15.0  # 高置信度

    def get_24h_win_rate(self, db_path: str) -> float:
        """查询最近24小时胜率"""
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM arena4_votes v
            JOIN arena4_battles b ON v.battle_id = b.id
            WHERE (b.model_a = ? OR b.model_b = ? OR b.model_c = ? OR b.model_d = ?)
            AND v.winner_model = ?
            AND v.created_at >= datetime('now', '-1 day')
        """, (self.model_id, self.model_id, self.model_id, self.model_id, self.model_id))
        wins_24h = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*) FROM arena4_battles
            WHERE (model_a = ? OR model_b = ? OR model_c = ? OR model_d = ?)
            AND created_at >= datetime('now', '-1 day')
        """, (self.model_id, self.model_id, self.model_id, self.model_id))
        total_24h = cursor.fetchone()[0]
        conn.close()

        if total_24h == 0:
            return 0.0
        return wins_24h / total_24h


# ==================== 排名引擎 ====================
class LobsterRankingEngine:
    """龙虾排名引擎 - 核心逻辑"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._vote_count = 0  # 内存中的投票计数器

    def _get_conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def get_or_create_rating(self, model_id: str, mode: str = "fast", month: str = "") -> ModelRating:
        """获取或创建模型评分（按mode+月份隔离）"""
        cur_month = month or time.strftime("%Y-%m", time.localtime())
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT gamma, wins, losses, ties, impressions, last_active_time, status
            FROM model_ratings WHERE model_id = ? AND mode = ? AND month = ?
        """, (model_id, mode, cur_month))
        row = cursor.fetchone()
        conn.close()

        if row:
            mr = ModelRating(model_id, mode, cur_month)
            mr.gamma = row[0]
            mr.wins = row[1]
            mr.losses = row[2]
            mr.ties = row[3]
            mr.impressions = row[4]
            mr.last_active_time = row[5]
            mr.status = row[6]
            return mr

        # 新建
        mr = ModelRating(model_id, mode, cur_month)
        self._save_rating(mr)
        return mr

    def _save_rating(self, mr: ModelRating):
        """保存模型评分到数据库（按model_id+mode+month唯一）"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO model_ratings (model_id, mode, month, gamma, wins, losses, ties, impressions, last_active_time, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(model_id, mode, month) DO UPDATE SET
                gamma = excluded.gamma,
                wins = excluded.wins,
                losses = excluded.losses,
                ties = excluded.ties,
                impressions = excluded.impressions,
                last_active_time = excluded.last_active_time,
                status = excluded.status
        """, (mr.model_id, mr.mode, mr.month, mr.gamma, mr.wins, mr.losses, mr.ties,
              mr.impressions, mr.last_active_time, mr.status))
        conn.commit()
        conn.close()

    def update_ratings(self, battle_id: int, winner_label: str,
                       all_models: List[str], weight: float = 1.0,
                       mode: str = "fast", worst_label: str = None,
                       difficulty_factor: float = 1.0):
        """
        根据4模型对战结果更新 Plackett-Luce 排名

        Args:
            battle_id: 对战ID
            winner_label: 胜者标签 (A/B/C/D/tie/both_bad)
            worst_label: 最差模型标签 (A/B/C/D/None)，用于定向惩罚
            all_models: 参战的4个模型ID列表 [model_a, model_b, model_c, model_d]
            weight: 投票权重（诚意过滤后的权重）
            mode: 模式 (fast/expert)
        """
        # 卫语句：无效票(weight<=0)绝不进入核心统计逻辑
        if weight <= 0:
            return

        # 加载所有参战模型的评分
        ratings = [self.get_or_create_rating(mid, mode=mode) for mid in all_models]

        # 计算总实力值
        total_gamma = sum(r.gamma for r in ratings)

        # 计算动态K因子: Dynamic_K = BASE_K * D
        dynamic_k = BASE_K * difficulty_factor

        if winner_label in ("A", "B", "C", "D"):
            # 单一胜者
            winner_idx = ord(winner_label) - ord("A")
            if winner_idx >= len(ratings):
                return

            winner = ratings[winner_idx]
            p_win = winner.gamma / total_gamma  # 胜者获胜概率

            # 胜者加分 = K * (1 - P_win) * weight * D-factor
            winner.gamma += dynamic_k * (1.0 - p_win) * weight / dynamic_k
            winner.wins += 1

            # 解析最差模型索引
            worst_idx = None
            if worst_label and worst_label in ("A", "B", "C", "D"):
                worst_idx = ord(worst_label) - ord("A")
                # 最差不等于胜者才有意义
                if worst_idx == winner_idx:
                    worst_idx = None

            # 败者扣分：双向极值投票逻辑
            # 有worst时：最差者吃定向惩罚(2x)，其余败者均分治底
            # 无worst时：均分惩罚（原始逻辑）
            losers = [(i, r) for i, r in enumerate(ratings) if i != winner_idx]
            if worst_idx is not None and len(losers) > 1:
                # 最差者吃 2/3 的总惩罚池
                total_penalty = dynamic_k * p_win * weight / dynamic_k
                worst_penalty = total_penalty * 2.0 / 3.0
                remaining_penalty = total_penalty - worst_penalty
                each_remaining = remaining_penalty / (len(losers) - 1)
                for i, r in losers:
                    if i == worst_idx:
                        r.gamma = max(r.gamma - worst_penalty, MIN_GAMMA)
                    else:
                        r.gamma = max(r.gamma - each_remaining, MIN_GAMMA)
                    r.losses += 1
            else:
                # 均分惩罚
                penalty = dynamic_k * p_win / (len(ratings) - 1) * weight / dynamic_k
                for i, r in enumerate(ratings):
                    if i != winner_idx:
                        r.gamma = max(r.gamma - penalty, MIN_GAMMA)
                        r.losses += 1

        elif winner_label == "tie":
            # 平局：按 gamma 比例微量积分
            # 弱者微量加分，强者微量减分（趋向均衡）
            avg_gamma = total_gamma / len(ratings)
            for i, r in enumerate(ratings):
                diff = avg_gamma - r.gamma
                r.gamma += diff * 0.02 * weight * difficulty_factor  # 微调2%
                r.gamma = max(r.gamma, MIN_GAMMA)
                r.ties += 1

            # worst定向惩罚：平局中仍标记最差，额外扣分
            if worst_idx is not None:
                worst_r = ratings[worst_idx]
                worst_r.gamma = max(worst_r.gamma * (1.0 - 0.02 * weight), MIN_GAMMA)

        elif winner_label == "both_bad":
            # 都不好：按比例微量扣分
            for i, r in enumerate(ratings):
                if i == worst_idx:
                    # 最差者吃3倍惩罚
                    r.gamma = max(r.gamma * (1.0 - 0.03 * weight * difficulty_factor), MIN_GAMMA)
                else:
                    r.gamma = max(r.gamma * (1.0 - 0.01 * weight * difficulty_factor), MIN_GAMMA)
                r.losses += 1

        # 更新曝光次数和活跃时间
        now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        for r in ratings:
            r.impressions += 1
            r.last_active_time = now
            # 检查淘汰/复出条件
            self._check_status(r)
            self._save_rating(r)

        # 增加投票计数器
        self._vote_count += 1
        if self._vote_count >= RECALC_TRIGGER:
            self._vote_count = 0
            self.full_recalculate(mode=mode)

    def _check_status(self, mr: ModelRating):
        """检查模型状态（active / observing / probation / eliminated）"""
        if mr.impressions < MIN_IMPRESSIONS_ELIM:
            mr.status = "active"
            return

        if mr.win_rate < ELIMINATION_THRESHOLD:
            if mr.status == "active":
                mr.status = "observing"  # 降级到观察池
            elif mr.status == "observing":
                mr.status = "eliminated"  # 持续表现差则淘汰
            elif mr.status == "probation":
                mr.status = "eliminated"  # 观察期仍差，回退淘汰
        else:
            # 表现恢复
            if mr.status == "observing":
                mr.status = "active"  # 观察池恢复
            elif mr.status == "eliminated":
                # 淘汰→灰度观察期，不直接跳active
                mr.status = "probation"
            elif mr.status == "probation":
                # 观察期LCB复活判定：置信下界超过active池均值才复活
                if self._lcb_above_active_avg(mr):
                    mr.status = "active"
                # 否则留在probation继续观察

    def _lcb_above_active_avg(self, mr: ModelRating) -> bool:
        """判定probation模型的LCB是否超过active池平均gamma"""
        # LCB = gamma - z * confidence (z=1.0即1σ)
        lcb = mr.gamma - mr.get_confidence()

        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT AVG(gamma) FROM model_ratings WHERE status = 'active' AND mode = ? AND month = ?",
            (mr.mode, mr.month)
        )
        row = cursor.fetchone()
        conn.close()

        active_avg = row[0] if row and row[0] else INITIAL_GAMMA
        return lcb > active_avg

    def full_recalculate(self, mode: str = "fast"):
        """
        全局重算 - 基于当前mode+month的历史记录重新计算 γ
        使用迭代最大似然估计（简化版）
        """
        # 获取当前月份
        now = time.localtime()
        current_month = f"{now.tm_year}-{now.tm_mon:02d}"

        conn = self._get_conn()
        cursor = conn.cursor()

        # 仅获取当前mode+month的模型
        cursor.execute("SELECT model_id FROM model_ratings WHERE mode = ? AND month = ?", (mode, current_month))
        all_model_ids = [row[0] for row in cursor.fetchall()]

        if not all_model_ids:
            conn.close()
            return

        # 初始化所有模型的γ
        gammas = {mid: INITIAL_GAMMA for mid in all_model_ids}

        # 获取当前mode的有效投票记录（按mode分区隔离，仅高保真选票）
        cursor.execute("""
            SELECT b.model_a, b.model_b, b.model_c, b.model_d, v.winner_label
            FROM arena4_votes v
            JOIN arena4_battles b ON v.battle_id = b.id
            WHERE v.winner_label IN ('A', 'B', 'C', 'D')
              AND b.mode = ?
              AND COALESCE(v.is_valid_for_elo, 1) = 1
        """, (mode,))
        votes = cursor.fetchall()
        conn.close()

        if len(votes) < 10:
            return  # 数据太少，不重算

        # 标准Plackett-Luce MM迭代（Minorize-Maximize）
        # γ_i^{new} = W_i / Σ_{r: i∈r} (γ_i / Σ_{j∈r} γ_j)
        # W_i = 模型i的胜场数，分母 = 模型i在每场参赛中被选概率之和
        for _ in range(20):
            numerators = {mid: 0 for mid in all_model_ids}   # W_i: 胜场计数
            denominators = {mid: 0.0 for mid in all_model_ids}  # Σ(γ_i/Σγ)

            for row in votes:
                models = [row[0], row[1], row[2], row[3]]
                winner_idx = ord(row[4]) - ord("A")
                if winner_idx >= len(models):
                    continue
                winner_id = models[winner_idx]

                # 胜者分子+1
                if winner_id in numerators:
                    numerators[winner_id] += 1

                # 分母：每个参战模型的P(被选|本场)=γ_i/Σγ
                total_g = sum(gammas.get(m, MIN_GAMMA) for m in models)
                if total_g <= 0:
                    continue
                for m in models:
                    if m in denominators:
                        denominators[m] += gammas.get(m, MIN_GAMMA) / total_g

            # MM更新: γ_i^{new} = W_i / denom_i
            max_delta = 0.0
            for mid in all_model_ids:
                if denominators[mid] > 0 and numerators[mid] > 0:
                    new_gamma = max(numerators[mid] / denominators[mid], MIN_GAMMA)
                    max_delta = max(max_delta, abs(new_gamma - gammas[mid]))
                    gammas[mid] = new_gamma

            # 收敛检测：γ变化<1e-6则提前终止
            if max_delta < 1e-6:
                break

        # 保存重算结果
        for mid in all_model_ids:
            mr = self.get_or_create_rating(mid, mode=mode)
            mr.gamma = gammas[mid]
            self._save_rating(mr)

    # ==================== UCB-E 曝光控制 ====================
    def get_exposure_weights(self, available_models: List[str],
                              mode: str = "fast") -> Dict[str, float]:
        """
        计算每个模型的UCB-E曝光权重

        Returns:
            {model_id: weight} 权重字典，用于加权随机选择
        """
        ratings = {mid: self.get_or_create_rating(mid, mode=mode) for mid in available_models}

        weights = {}
        for mid, mr in ratings.items():
            if mr.status == "eliminated":
                # 淘汰模型：5%灰度复出概率
                weights[mid] = OBSERVATION_POOL_RATE
            elif mr.status == "probation":
                # 观察期模型：15%权重，低于observing但高于eliminated
                weights[mid] = 0.15
            elif mr.status == "observing":
                # 观察池模型：降低权重但仍可被选中
                weights[mid] = 0.3
            else:
                # 活跃模型：UCB-E 计算
                if mr.impressions == 0:
                    # 未曝光过的模型给予最高探索权重
                    weights[mid] = 10.0
                else:
                    # UCB-E: w = γ + c * sqrt(ln(N) / n_i)
                    # N = 总曝光次数, n_i = 该模型曝光次数
                    total_impressions = sum(r.impressions for r in ratings.values())
                    if total_impressions > 0 and mr.impressions > 0:
                        exploration = UCB_EXPLORATION * math.sqrt(
                            math.log(max(total_impressions, 1)) / mr.impressions
                        )
                        weights[mid] = mr.gamma + exploration
                    else:
                        weights[mid] = mr.gamma + 1.0

        return weights

    def select_models(self, available_models: List[str], count: int = 4,
                       mode: str = "fast") -> List[str]:
        """
        基于UCB-E权重选择模型（加权随机采样）

        Args:
            available_models: 可选模型ID列表
            count: 需要选出的模型数量
            mode: 模式 (fast/expert)

        Returns:
            选中的模型ID列表
        """
        if len(available_models) <= count:
            return available_models[:]

        weights = self.get_exposure_weights(available_models, mode=mode)
        selected = []

        remaining = list(available_models)
        for _ in range(count):
            if not remaining:
                break

            w = [weights.get(m, 1.0) for m in remaining]
            total_w = sum(w)
            if total_w <= 0:
                # 退化为均匀随机
                chosen = random.choice(remaining)
            else:
                # 加权随机选择
                r = random.random() * total_w
                cumsum = 0
                chosen = remaining[-1]
                for i, wi in enumerate(w):
                    cumsum += wi
                    if cumsum >= r:
                        chosen = remaining[i]
                        break

            selected.append(chosen)
            remaining.remove(chosen)

        return selected

    # ==================== 反作弊诚意过滤 ====================
    def compute_vote_weight(self, user_id: str, question: str,
                            render_complete_time: float,
                            user_click_time: float,
                            scroll_depth: int = 0) -> float:
        """
        计算投票权重（诚意过滤）

        Args:
            user_id: 用户标识（IP或session）
            question: 用户问题
            render_complete_time: 模型回答完成时间戳
            user_click_time: 用户投票时间戳
            scroll_depth: 滚动深度0-100

        Returns:
            投票权重 0.0 ~ 1.5
        """
        # 1. 首次触发检查：同一用户同一Prompt多次尝试，仅第一次计入
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM arena4_votes v
            JOIN arena4_battles b ON v.battle_id = b.id
            WHERE v.user_id = ? AND b.question = ?
        """, (user_id, question))
        prior_votes = cursor.fetchone()[0]

        if prior_votes > 0:
            # 已投过，这次不计入
            conn.close()
            return 0.0

        # 2. Dwell-Time Weighting
        dwell_time = user_click_time - render_complete_time

        if dwell_time < MIN_DWELL_TIME:
            # 停留时间太短，权重为0
            conn.close()
            return 0.0

        # 获取该用户历史平均停留时间
        cursor.execute("""
            SELECT AVG(v.user_click_time - v.render_complete_time)
            FROM arena4_votes v
            WHERE v.user_id = ? AND v.user_click_time > 0 AND v.render_complete_time > 0
        """, (user_id,))
        avg_row = cursor.fetchone()
        conn.close()

        avg_dwell = avg_row[0] if avg_row and avg_row[0] else 10.0  # 默认10秒

        # 停留时间在用户均值的0.8~1.5倍范围内，权重1.5
        if DWELL_LOW_FACTOR * avg_dwell <= dwell_time <= DWELL_HIGH_FACTOR * avg_dwell:
            return MAX_VOTE_WEIGHT

        # 其他情况：线性衰减
        if dwell_time < DWELL_LOW_FACTOR * avg_dwell:
            # 偏短：从0.5到1.5线性
            ratio = dwell_time / (DWELL_LOW_FACTOR * avg_dwell)
            return 0.5 + ratio
        else:
            # 偏长：从1.5缓慢降到1.0
            ratio = min((dwell_time - DWELL_HIGH_FACTOR * avg_dwell) / avg_dwell, 1.0)
            weight = MAX_VOTE_WEIGHT - 0.5 * ratio

        # 3. Scroll Depth Bonus: 未滚动(<5%)惩罚0.7x, 深度滚动(>60%)加成1.15x
        if scroll_depth < 5:
            weight *= 0.7
        elif scroll_depth > 60:
            weight *= 1.15

        return round(max(weight, MIN_VOTE_WEIGHT), 4)

    # ==================== D-Factor 映射 ====================
    @staticmethod
    def compute_difficulty_factor(consensus_rate: float) -> float:
        """
        根据共识率计算动态难度系数
        - consensus_rate=1.0 (全员通过,极简任务) → D=0.2
        - consensus_rate≤0.25 (高难度) → D=3.0
        - 中间线性插值
        """
        if consensus_rate >= 1.0:
            return 0.2
        if consensus_rate <= 0.25:
            return 3.0
        return round(1.0 + (1.0 - consensus_rate) * 2.67, 2)
    def get_leaderboard(self, mode: str = "fast", month: str = "") -> List[Dict]:
        """获取实时排行榜数据（按mode+月份过滤）"""
        cur_month = month or time.strftime("%Y-%m", time.localtime())
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT model_id FROM model_ratings WHERE mode = ? AND month = ?",
            (mode, cur_month))
        all_ids = [row[0] for row in cursor.fetchall()]
        conn.close()

        leaderboard = []
        for mid in all_ids:
            mr = self.get_or_create_rating(mid, mode=mode, month=cur_month)
            leaderboard.append({
                "model_id": mid,
                "mode": mode,
                "month": cur_month,
                "arena_score": round(mr.get_arena_score(), 1),
                "confidence": round(mr.get_confidence(), 1),
                "win_rate_24h": round(mr.get_24h_win_rate(self.db_path) * 100, 1),
                "wins": mr.wins,
                "losses": mr.losses,
                "ties": mr.ties,
                "impressions": mr.impressions,
                "status": mr.status,
                "gamma": round(mr.gamma, 4),
            })

        # 按 Arena Score 降序排列
        leaderboard.sort(key=lambda x: -x["arena_score"])
        return leaderboard

    # ==================== 月度归档 ====================
    def archive_monthly_rankings(self, month: str = "") -> Dict:
        """
        月度归档：将指定月份的 model_ratings 快照到 monthly_rankings 表，
        然后重置该月所有记录的 gamma/wins/losses/ties/impressions 归零。

        Args:
            month: 要归档的月份，格式 YYYY-MM，默认上月

        Returns:
            {"archived_count": int, "month": str}
        """
        if not month:
            # 默认归档上月
            now = time.localtime()
            if now.tm_mon == 1:
                month = f"{now.tm_year - 1}-12"
            else:
                month = f"{now.tm_year}-{now.tm_mon - 1:02d}"

        conn = self._get_conn()
        cursor = conn.cursor()

        # 确保 monthly_rankings 表存在
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS monthly_rankings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                month TEXT NOT NULL,
                arena_score REAL,
                gamma REAL,
                wins INTEGER,
                losses INTEGER,
                ties INTEGER,
                impressions INTEGER,
                status TEXT,
                archived_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(model_id, mode, month)
            )
        """)

        # 查询该月所有 rating 记录
        cursor.execute("""
            SELECT model_id, mode, month, gamma, wins, losses, ties, impressions, status
            FROM model_ratings WHERE month = ?
        """, (month,))
        rows = cursor.fetchall()

        if not rows:
            conn.close()
            return {"archived_count": 0, "month": month}

        # 快照到 monthly_rankings
        for row in rows:
            model_id, mode_val, month_val, gamma, wins, losses, ties, impressions, status = row
            arena_score = BASE_SCORE + 400.0 * math.log10(max(gamma, MIN_GAMMA))
            cursor.execute("""
                INSERT INTO monthly_rankings (model_id, mode, month, arena_score, gamma, wins, losses, ties, impressions, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(model_id, mode, month) DO UPDATE SET
                    arena_score = excluded.arena_score,
                    gamma = excluded.gamma,
                    wins = excluded.wins,
                    losses = excluded.losses,
                    ties = excluded.ties,
                    impressions = excluded.impressions,
                    status = excluded.status,
                    archived_at = CURRENT_TIMESTAMP
            """, (model_id, mode_val, month_val, round(arena_score, 1), gamma, wins, losses, ties, impressions, status))

        # 重置该月 model_ratings
        cursor.execute("""
            UPDATE model_ratings
            SET gamma = ?, wins = 0, losses = 0, ties = 0, impressions = 0, status = 'active'
            WHERE month = ?
        """, (INITIAL_GAMMA, month))

        conn.commit()
        conn.close()

        return {"archived_count": len(rows), "month": month}

    def get_monthly_archives(self, month: str = "", mode: str = "") -> List[Dict]:
        """查询月度归档排行榜"""
        conn = self._get_conn()
        cursor = conn.cursor()

        # 确保表存在
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS monthly_rankings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                month TEXT NOT NULL,
                arena_score REAL,
                gamma REAL,
                wins INTEGER,
                losses INTEGER,
                ties INTEGER,
                impressions INTEGER,
                status TEXT,
                archived_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(model_id, mode, month)
            )
        """)

        query = "SELECT model_id, mode, month, arena_score, gamma, wins, losses, ties, impressions, status, archived_at FROM monthly_rankings WHERE 1=1"
        params = []
        if month:
            query += " AND month = ?"
            params.append(month)
        if mode:
            query += " AND mode = ?"
            params.append(mode)
        query += " ORDER BY arena_score DESC"

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        return [{
            "model_id": r[0], "mode": r[1], "month": r[2],
            "arena_score": r[3], "gamma": round(r[4], 4),
            "wins": r[5], "losses": r[6], "ties": r[7],
            "impressions": r[8], "status": r[9], "archived_at": r[10]
        } for r in rows]

    def delete_monthly_archive(self, month: str) -> Dict:
        """删除指定月份的归档记录"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS monthly_rankings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                month TEXT NOT NULL,
                arena_score REAL,
                gamma REAL,
                wins INTEGER,
                losses INTEGER,
                ties INTEGER,
                impressions INTEGER,
                status TEXT,
                archived_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(model_id, mode, month)
            )
        """)
        cursor.execute("DELETE FROM monthly_rankings WHERE month = ?", (month,))
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        return {"deleted_count": deleted, "month": month}

    def get_available_months(self) -> List[str]:
        """获取所有有归档数据的月份列表"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS monthly_rankings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                month TEXT NOT NULL,
                arena_score REAL,
                gamma REAL,
                wins INTEGER,
                losses INTEGER,
                ties INTEGER,
                impressions INTEGER,
                status TEXT,
                archived_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(model_id, mode, month)
            )
        """)
        cursor.execute("SELECT DISTINCT month FROM monthly_rankings ORDER BY month DESC")
        months = [row[0] for row in cursor.fetchall()]
        conn.close()
        return months

    def get_stats(self) -> Dict:
        """获取全局统计"""
        conn = self._get_conn()
        cursor = conn.cursor()

        # 总对局数
        cursor.execute("SELECT COUNT(*) FROM arena4_battles")
        total_battles = cursor.fetchone()[0]

        # 总投票数
        cursor.execute("SELECT COUNT(*) FROM arena4_votes")
        total_votes = cursor.fetchone()[0]

        # 今日对局数
        cursor.execute("""
            SELECT COUNT(*) FROM arena4_battles
            WHERE created_at >= datetime('now', '-1 day')
        """)
        today_battles = cursor.fetchone()[0]

        # 今日投票数
        cursor.execute("""
            SELECT COUNT(*) FROM arena4_votes
            WHERE created_at >= datetime('now', '-1 day')
        """)
        today_votes = cursor.fetchone()[0]

        # 活跃模型数
        cursor.execute("SELECT COUNT(*) FROM model_ratings WHERE status = 'active'")
        active_models = cursor.fetchone()[0]

        # 观察池模型数
        cursor.execute("SELECT COUNT(*) FROM model_ratings WHERE status = 'observing'")
        observing_models = cursor.fetchone()[0]

        # 按category分类统计
        category_stats = {}
        try:
            cursor.execute("""
                SELECT COALESCE(category, 'overall') as cat, COUNT(*) as cnt
                FROM arena4_battles GROUP BY cat
            """)
            for row in cursor.fetchall():
                category_stats[row[0]] = category_stats.get(row[0], {})
                category_stats[row[0]]['battles'] = row[1]
            cursor.execute("""
                SELECT COALESCE(category, 'overall') as cat, COUNT(*) as cnt
                FROM arena4_votes GROUP BY cat
            """)
            for row in cursor.fetchall():
                category_stats.setdefault(row[0], {})['votes'] = row[1]
        except Exception:
            pass  # category列可能不存在(旧数据)

        conn.close()

        result = {
            "total_battles": total_battles,
            "total_votes": total_votes,
            "today_battles": today_battles,
            "today_votes": today_votes,
            "active_models": active_models,
            "observing_models": observing_models,
            "recalc_counter": self._vote_count,
            "recalc_trigger": RECALC_TRIGGER,
        }
        if category_stats:
            result["category_stats"] = category_stats
        return result
