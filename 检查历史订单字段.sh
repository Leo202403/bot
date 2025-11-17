#!/bin/bash
# 检查 trades_history.csv 字段结构

echo "=========================================="
echo "1. 检查CSV表头字段"
echo "=========================================="
head -1 /root/10-23-bot/ds/trading_data/qwen/trades_history.csv | tr ',' '\n' | nl
echo ""

echo "=========================================="
echo "2. 检查最新3笔记录"
echo "=========================================="
echo "查看完整记录："
tail -n 3 /root/10-23-bot/ds/trading_data/qwen/trades_history.csv
echo ""

echo "=========================================="
echo "3. 提取关键字段（开仓时间,币种,信号分数,共振指标数）"
echo "=========================================="
echo "列索引说明："
head -1 /root/10-23-bot/ds/trading_data/qwen/trades_history.csv | tr ',' '\n' | grep -n "信号分数\|共振指标数\|开仓时间\|币种"
echo ""
echo "最新记录的这些字段："
tail -n 5 /root/10-23-bot/ds/trading_data/qwen/trades_history.csv | awk -F',' '{print $1 " | " $3 " | " $16 " | " $17}'
echo ""

echo "=========================================="
echo "4. 统计有/无信号分数的记录数"
echo "=========================================="
total=$(tail -n +2 /root/10-23-bot/ds/trading_data/qwen/trades_history.csv | wc -l)
has_score=$(tail -n +2 /root/10-23-bot/ds/trading_data/qwen/trades_history.csv | awk -F',' '$16 != "" && $16 != "None" {count++} END {print count+0}')
echo "总记录数: $total"
echo "有信号分数: $has_score"
echo "无信号分数: $((total - has_score))"
echo ""

echo "=========================================="
echo "5. 显示最早有信号分数的记录"
echo "=========================================="
tail -n +2 /root/10-23-bot/ds/trading_data/qwen/trades_history.csv | awk -F',' '$16 != "" && $16 != "None" {print; exit}'
echo ""

echo "✅ 检查完成"
echo "预期结果："
echo "  - 表头应包含'信号分数'和'共振指标数'"
echo "  - 11-17及之后的记录应有数值"
echo "  - 11-16及之前的记录为空（正常）"

