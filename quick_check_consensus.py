#!/usr/bin/env python3
"""快速检查consensus问题"""

import pandas as pd
from pathlib import Path

# 尝试两个可能的路径
paths_to_try = [
    Path("/root/10-23-bot/ds/trading_data/deepseek/market_snapshots"),
    Path("./ds/trading_data/deepseek/market_snapshots"),
    Path("./trading_data/deepseek/market_snapshots"),
]

snapshot_dir = None
for p in paths_to_try:
    if p.exists():
        snapshot_dir = p
        break

if not snapshot_dir:
    print("❌ 未找到快照目录")
    print("尝试过的路径:")
    for p in paths_to_try:
        print(f"  - {p}")
    exit(1)

print(f"✓ 找到快照目录: {snapshot_dir}")

# 获取最新的CSV文件
csv_files = sorted(snapshot_dir.glob("*.csv"), reverse=True)
if not csv_files:
    print("❌ 未找到CSV文件")
    exit(1)

latest_csv = csv_files[0]
print(f"✓ 最新文件: {latest_csv.name}")

# 读取并检查
df = pd.read_csv(latest_csv, on_bad_lines='skip', encoding='utf-8-sig')

print(f"\n📊 文件信息:")
print(f"  - 总行数: {len(df)}")
print(f"  - 总列数: {len(df.columns)}")

if 'indicator_consensus' in df.columns:
    print(f"\n✓ 找到 indicator_consensus 列")
    print(f"\n  值分布:")
    value_counts = df['indicator_consensus'].value_counts().sort_index()
    for val, count in value_counts.items():
        pct = count / len(df) * 100
        print(f"    {val}: {count:4d}个 ({pct:5.1f}%)")
    
    # 如果全是0，检查原因
    if df['indicator_consensus'].max() == 0:
        print(f"\n  ⚠️  所有consensus都是0，检查原因...")
        
        # 随机抽取一行检查
        sample = df.sample(1).iloc[0]
        print(f"\n  样本检查:")
        print(f"    币种: {sample.get('coin', 'N/A')}")
        print(f"    趋势15m: {sample.get('trend_15m', 'N/A')}")
        print(f"    趋势4h: {sample.get('trend_4h', 'N/A')}")
        print(f"    RSI: {sample.get('rsi_14', 'N/A')}")
        print(f"    MACD: {sample.get('macd_histogram', 'N/A')}")
        
        # 检查可能的问题
        print(f"\n  可能原因:")
        
        # 检查是否有trend_1h列
        if 'trend_1h' not in df.columns:
            print(f"    ❌ 缺少 trend_1h 列（共振计算需要）")
        
        # 检查是否有EMA列
        if 'ema20_1h' not in df.columns or 'ema50_1h' not in df.columns:
            print(f"    ❌ 缺少 EMA列（共振计算需要）")
        
        # 检查数据质量
        null_counts = df[['trend_15m', 'trend_4h', 'rsi_14', 'macd_histogram']].isna().sum()
        if null_counts.sum() > 0:
            print(f"    ⚠️  存在空值:")
            for col, count in null_counts.items():
                if count > 0:
                    print(f"       {col}: {count}个空值")
    
else:
    print(f"\n❌ 未找到 indicator_consensus 列")
    print(f"\n  现有列（前30个）:")
    for i, col in enumerate(df.columns[:30], 1):
        print(f"    {i:2d}. {col}")

