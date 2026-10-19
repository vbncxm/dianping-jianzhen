# -*- coding: utf-8 -*-
"""运行配置：检测权重、判定阈值、清洗策略、评分公式参数。

所有参数都可以在运行时通过 /api/config 覆盖，并重跑整条流水线，
便于演示「调节阈值 → 净化结果与榜单如何变化」。
"""
from dataclasses import dataclass, field, asdict
from typing import Tuple


@dataclass
class Config:
    # ── 一、五类信号在风险分中的权重（和须为 1.0）──────────────────────
    w_text: float = 0.30        # 文本痕迹
    w_temporal: float = 0.25    # 时间行为
    w_account: float = 0.25     # 账号行为
    w_rating: float = 0.15      # 评分异常
    w_media: float = 0.05       # 图文一致性

    # ── 二、判定阈值与清洗策略 ─────────────────────────────────────────
    # 阈值按本样本风险分分布校准：高风险≈P99.6、观察≈P96
    watch_threshold: float = 35.0    # ≥ 该值 → 观察区（降权）
    high_threshold: float = 60.0     # ≥ 该值 → 高风险（剔除）
    drop_high: bool = True           # 高风险评论是否直接剔除
    max_downweight: float = 0.70     # 观察区最大降权幅度（0.7 = 最多削 70%）

    # ── 三、文本类判定参数 ────────────────────────────────────────────
    min_len_short: int = 8           # 短评判定长度
    hype_density_cap: int = 3        # 营销词命中数达到该值即满分
    dup_sim_threshold: float = 0.62  # 字符 bigram Jaccard 相似度 ≥ 此值判模板复用
    exclaim_cap: int = 4             # 感叹号数量达到该值即满分

    # ── 四、时间类判定参数 ────────────────────────────────────────────
    city_burst_min: int = 4          # 单店单日最少条数，低于此值不算爆发
    burst_ratio: float = 3.0         # 单日条数 ≥ 该倍数×酒店日均，判爆发
    night_hours: Tuple[int, ...] = (0, 1, 2, 3, 4, 5)   # 深夜发布时段
    max_gap_days: int = 180          # 评论距入住超过该天数 → 时间错位

    # ── 五、评分公式参数（与《项目申请书》口径对齐）────────────────────
    ahp_overall: float = 0.40        # 总评分权重
    ahp_dims: float = 0.15           # 卫生/设施/环境/服务 各占权重
    bayes_c: float = 30.0            # 贝叶斯收缩强度（虚拟评论数）
    lambda_decay: float = 0.001      # 时间衰减系数 λ（单位：天）
    theta_elastic: float = 0.30      # 价格弹性指数 θ（<1 表示价格敏感度递减）
    elastic_lo: float = 0.70         # 价格弹性系数下界
    elastic_hi: float = 1.40         # 价格弹性系数上界
    as_of: str = ""                  # 时间衰减基准日 YYYY-MM-DD；空=取样本最新评论日

    # ── 六、情感得分合成权重 ──────────────────────────────────────────
    sent_score_w: float = 0.60       # 星级评分归一
    sent_text_w: float = 0.25        # 文本情感极性
    sent_reco_w: float = 0.15        # 是否推荐

    def to_dict(self) -> dict:
        d = asdict(self)
        d["night_hours"] = list(self.night_hours)
        return d

    def update(self, patch: dict) -> "Config":
        """按 dict 局部覆盖，返回自身（便于链式调用）。"""
        allowed = set(self.to_dict().keys())
        for k, v in (patch or {}).items():
            if k not in allowed:
                continue
            if k == "night_hours":
                v = tuple(int(x) for x in v)
            elif isinstance(getattr(self, k), bool):
                v = bool(v)
            elif isinstance(getattr(self, k), float):
                v = float(v)
            elif isinstance(getattr(self, k), int):
                v = int(v)
            setattr(self, k, v)
        return self

    def normalized_weights(self) -> dict:
        """把五类信号权重归一化，避免调用方传错和不为 1。"""
        w = {"text": max(0.0, self.w_text), "temporal": max(0.0, self.w_temporal),
             "account": max(0.0, self.w_account), "rating": max(0.0, self.w_rating),
             "media": max(0.0, self.w_media)}
        s = sum(w.values()) or 1.0
        return {k: v / s for k, v in w.items()}


# 全局默认配置实例
DEFAULT = Config()
