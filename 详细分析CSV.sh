#!/bin/bash

echo "=========================================="
echo "详细分析CSV文件结构和数据"
echo "=========================================="
echo ""

FILE="/root/10-23-bot/ds/trading_data/qwen/trades_history.csv"

echo "1. 统计CSV列数"
head -1 "$FILE" | awk -F',' '{print "总列数:", NF}'
echo ""

echo "2. 查看原始开仓记录（非分批）"
echo "查找11-16开仓且无'剩余'标记的记录："
grep "2025-11-16" "$FILE" | grep -v "剩余" | head -n 3 | awk -F',' '{print "开仓时间:", $1, "| 币种:", $3, "| 信号分数:", $16, "| 共振:", $17}'
echo ""

echo "3. 查找包含'剩余'的记录"
grep "剩余" "$FILE" | tail -n 3 | awk -F',' '{print "开仓时间:", $1, "| 币种:", $3, "| 信号分数:", $16, "| 共振:", $17, "| 开仓理由末尾:", substr($14, length($14)-20)}'
echo ""

echo "4. 检查CSV文件编码和特殊字符"
file "$FILE"
head -1 "$FILE" | od -c | head -n 5
echo ""

echo "5. 使用python pandas读取"
python3 << 'PYTHON_EOF'
import pandas as pd
import sys

try:
    df = pd.read_csv("/root/10-23-bot/ds/trading_data/qwen/trades_history.csv", encoding="utf-8")
    print(f"DataFrame形状: {df.shape}")
    print(f"列名: {df.columns.tolist()}")
    print(f"\n最后5行的信号数据:")
    print(df[['开仓时间', '币种', '信号分数', '共振指标数']].tail(5))
    print(f"\n信号分数的数据类型: {df['信号分数'].dtype}")
    print(f"信号分数的唯一值（前10个）: {df['信号分数'].unique()[:10]}")
    print(f"\n信号分数统计:")
    print(df['信号分数'].describe())
except Exception as e:
    print(f"错误: {e}")
    import traceback
    traceback.print_exc()
PYTHON_EOF
echo ""

echo "6. 查看V8.5.1.8部署前后的记录"
echo "11-16及之前（V8.5.1.8之前）："
grep "2025-11-16" "$FILE" | head -n 2 | awk -F',' '{print $1, $3, $16, $17}'
echo "11-17及之后（V8.5.1.8之后）："
grep "2025-11-17" "$FILE" | head -n 2 | awk -F',' '{print $1, $3, $16, $17}'
echo ""

echo "✅ 分析完成"

