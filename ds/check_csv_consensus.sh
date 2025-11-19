#!/bin/bash
# 检查市场快照CSV中indicator_consensus字段的实际情况

MODEL="deepseek"
CSV_DIR="/root/10-23-bot/ds/trading_data/${MODEL}/market_snapshots"

echo "=========================================="
echo "检查CSV文件中的indicator_consensus"
echo "=========================================="

# 找到最新的CSV文件
LATEST_CSV=$(ls -t ${CSV_DIR}/*.csv 2>/dev/null | head -1)

if [ -z "$LATEST_CSV" ]; then
    echo "❌ 未找到CSV文件"
    exit 1
fi

echo ""
echo "✓ 最新CSV文件: $(basename $LATEST_CSV)"
echo ""

# 检查表头
echo "【1. 检查字段名】"
head -1 "$LATEST_CSV" | tr ',' '\n' | grep -n "consensus"
echo ""

# 检查indicator_consensus列的位置
HEADER=$(head -1 "$LATEST_CSV")
FIELD_NUM=$(echo "$HEADER" | tr ',' '\n' | grep -n "^indicator_consensus$" | cut -d: -f1)

if [ -z "$FIELD_NUM" ]; then
    echo "❌ 未找到indicator_consensus字段"
    exit 1
fi

echo "✓ indicator_consensus字段在第 ${FIELD_NUM} 列"
echo ""

# 统计indicator_consensus的值分布
echo "【2. indicator_consensus值分布】"
tail -n +2 "$LATEST_CSV" | cut -d, -f${FIELD_NUM} | sort | uniq -c | sort -rn
echo ""

# 检查前10行的实际值
echo "【3. 前10行数据样本】"
echo "行号 | 币种 | 时间 | indicator_consensus"
echo "----------------------------------------"
tail -n +2 "$LATEST_CSV" | head -10 | awk -F, -v field=$FIELD_NUM '{
    printf "%3d | %s | %s | %s\n", NR, $1, $2, $field
}'
echo ""

# 统计零值和非零值数量
TOTAL=$(tail -n +2 "$LATEST_CSV" | wc -l)
ZERO_COUNT=$(tail -n +2 "$LATEST_CSV" | cut -d, -f${FIELD_NUM} | grep -c "^0$\|^0\.0$")
NONZERO_COUNT=$((TOTAL - ZERO_COUNT))

echo "【4. 统计汇总】"
echo "总行数: $TOTAL"
echo "零值: $ZERO_COUNT ($((ZERO_COUNT * 100 / TOTAL))%)"
echo "非零值: $NONZERO_COUNT ($((NONZERO_COUNT * 100 / TOTAL))%)"
echo ""

# 如果有非零值，显示一些样本
if [ $NONZERO_COUNT -gt 0 ]; then
    echo "【5. 非零值样本（前5个）】"
    echo "币种 | 时间 | indicator_consensus"
    echo "----------------------------------------"
    tail -n +2 "$LATEST_CSV" | awk -F, -v field=$FIELD_NUM '$field != 0 && $field != 0.0 {
        printf "%s | %s | %s\n", $1, $2, $field
    }' | head -5
fi

echo ""
echo "=========================================="
echo "检查完成"
echo "=========================================="

