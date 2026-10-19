# -*- coding: utf-8 -*-
"""
线上虚假评论检测数据分析系统 —— 后端清洗与评分引擎

模块结构：
    config.py    配置（权重、阈值、公式参数），运行时可被 API 覆盖
    lexicon.py   词库（营销夸张词 / 情感词 / 具体性词 / 套话模板）
    loader.py    数据加载（reviews/*.json 与 all_reviews.jsonl）
    features.py  评论特征抽取
    detector.py  虚假评论检测（多信号融合 → 风险分 + 证据标签）
    scorer.py    净化后酒店评分（贝叶斯收缩 + 真实时间衰减 + 价格弹性）
    store.py     SQLite 持久化
    pipeline.py  端到端编排
    api.py       FastAPI 接口
    serve.py     启动入口
"""

__version__ = "1.0.0"
