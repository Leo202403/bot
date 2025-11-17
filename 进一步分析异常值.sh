#!/bin/bash

echo "进一步分析信号分数异常值"

python3 << 'EOF'
import pandas as pd

df = pd.read_csv("/root/10-23-bot/ds/trading_data/qwen/trades_history.csv", encoding="utf-8")

print("=" * 60)
print("1. 按信号分数分组统计")
print("=" * 60)
print(df.groupby('信号分数', dropna=False).size())

print(f"\n" + "=" * 60)
print("2. 查看信号分数=100的记录")
print("=" * 60)
df_100 = df[df['信号分数'] == 100.0]
print(f"总数: {len(df_100)}")
print(f"开仓时间范围: {df_100['开仓时间'].min()} ~ {df_100['开仓时间'].max()}")
print(f"\n样本（显示开仓理由末尾）:")
for idx, row in df_100.head(3).iterrows():
    reason = str(row['开仓理由'])
    reason_end = reason[-50:] if len(reason) > 50 else reason
    print(f"  [{idx}] {row['开仓时间']} {row['币种']} 理由末尾: ...{reason_end}")

print(f"\n" + "=" * 60)
print("3. 查看信号分数=80的记录")
print("=" * 60)
df_80 = df[df['信号分数'] == 80.0]
print(f"总数: {len(df_80)}")
if len(df_80) > 0:
    print(f"开仓时间: {df_80['开仓时间'].values[0]}")
    print(f"开仓理由: {str(df_80['开仓理由'].values[0])[:100]}...")

print(f"\n" + "=" * 60)
print("4. 检查是否都是'剩余'记录")
print("=" * 60)
df_100_with_remaining = df_100[df_100['开仓理由'].str.contains('剩余', na=False)]
print(f"信号分数=100的记录中，包含'剩余'的: {len(df_100_with_remaining)}/{len(df_100)}")

print(f"\n" + "=" * 60)
print("5. 查看原始开仓记录（不含'剩余'）的信号分数")
print("=" * 60)
df_original = df[~df['开仓理由'].str.contains('剩余', na=False)]
print(f"原始开仓记录数: {len(df_original)}")
print(f"有信号分数的: {df_original['信号分数'].notna().sum()}")
print(f"信号分数唯一值: {df_original['信号分数'].unique()}")
print(f"\n最新5条原始开仓:")
print(df_original[['开仓时间', '币种', '信号分数', '共振指标数']].tail(5).to_string())

EOF

