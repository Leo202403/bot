#!/bin/bash

echo "=========================================="
echo "快速验证信号质量修复"
echo "=========================================="
echo ""

MODEL="qwen"  # 可以改为deepseek
CSV_FILE="/root/10-23-bot/ds/trading_data/$MODEL/trades_history.csv"

if [ ! -f "$CSV_FILE" ]; then
    echo "❌ 找不到交易记录文件: $CSV_FILE"
    exit 1
fi

echo "1. 检查最新订单的信号数据"
echo "=========================================="
echo ""

# 获取最新的一条记录
LATEST=$(tail -n 1 "$CSV_FILE")

# 提取字段（假设信号分数是第16列，共振是第17列）
SIGNAL=$(echo "$LATEST" | awk -F',' '{print $16}')
CONSENSUS=$(echo "$LATEST" | awk -F',' '{print $17}')
COIN=$(echo "$LATEST" | awk -F',' '{print $3}')
DIRECTION=$(echo "$LATEST" | awk -F',' '{print $4}')
OPEN_TIME=$(echo "$LATEST" | awk -F',' '{print $1}')

echo "最新订单:"
echo "  开仓时间: $OPEN_TIME"
echo "  币种: $COIN"
echo "  方向: $DIRECTION"
echo "  信号分数: $SIGNAL"
echo "  共振指标数: $CONSENSUS"
echo ""

# 判断是否正常
if [ "$SIGNAL" = "100.0" ] && [ "$CONSENSUS" = "0.0" ]; then
    echo "❌ 异常！仍然是100.0/0.0"
    echo ""
    echo "可能原因:"
    echo "  1. 系统未重启（修复未生效）"
    echo "  2. 这条记录是旧数据"
    echo "  3. market_data获取失败"
    echo ""
    echo "建议操作:"
    echo "  1. 确认系统已重启: bash ~/快速重启_修复版.sh $MODEL"
    echo "  2. 等待下一个订单"
    echo "  3. 再次运行此脚本"
elif [ "$SIGNAL" = "0.0" ] || [ "$SIGNAL" = "0" ]; then
    echo "⚠️  信号分数为0"
    echo ""
    echo "可能原因:"
    echo "  1. market_data获取失败"
    echo "  2. 信号质量确实很低"
    echo ""
    echo "建议检查日志:"
    echo "  tail -f ~/10-23-bot/logs/${MODEL}_*.log | grep '信号评分'"
elif [[ "$SIGNAL" =~ ^[0-9]+\.?[0-9]*$ ]] && (( $(echo "$SIGNAL >= 50" | bc -l) )) && (( $(echo "$SIGNAL <= 100" | bc -l) )); then
    echo "✅ 信号分数正常！($SIGNAL分)"
    
    if [ "$CONSENSUS" = "0.0" ] || [ "$CONSENSUS" = "0" ]; then
        echo "⚠️  共振指标数为0（可能market_data缺失）"
    else
        echo "✅ 共振指标数正常！($CONSENSUS个)"
    fi
    
    echo ""
    echo "✅ 开仓质量修复已生效！"
else
    echo "⚠️  信号分数异常: $SIGNAL"
    echo ""
    echo "可能需要进一步检查"
fi

echo ""
echo "2. 统计最近10笔订单的信号分布"
echo "=========================================="
echo ""

python3 << 'EOF'
import pandas as pd
import sys

try:
    df = pd.read_csv('/root/10-23-bot/ds/trading_data/qwen/trades_history.csv')
    
    # 只看有开仓时间的记录
    df = df[df['开仓时间'].notna()].copy()
    
    if len(df) == 0:
        print("❌ 没有交易记录")
        sys.exit(0)
    
    # 最近10笔
    recent = df.tail(10)
    
    print(f"总记录数: {len(df)}")
    print(f"最近10笔:")
    print("")
    
    # 转换为数字类型
    recent['信号分数_num'] = pd.to_numeric(recent['信号分数'], errors='coerce')
    recent['共振指标数_num'] = pd.to_numeric(recent['共振指标数'], errors='coerce')
    
    # 统计
    signal_100_count = len(recent[recent['信号分数_num'] == 100.0])
    signal_0_count = len(recent[recent['信号分数_num'] == 0.0])
    signal_normal_count = len(recent[(recent['信号分数_num'] > 0) & (recent['信号分数_num'] < 100)])
    
    consensus_0_count = len(recent[recent['共振指标数_num'] == 0.0])
    consensus_normal_count = len(recent[recent['共振指标数_num'] > 0])
    
    print(f"信号分数分布:")
    print(f"  = 100.0: {signal_100_count}笔 {'⚠️ 异常' if signal_100_count > 0 else ''}")
    print(f"  = 0.0:   {signal_0_count}笔")
    print(f"  正常值:  {signal_normal_count}笔 ✅")
    print("")
    
    print(f"共振指标数分布:")
    print(f"  = 0:     {consensus_0_count}笔")
    print(f"  > 0:     {consensus_normal_count}笔 ✅")
    print("")
    
    # 如果有正常值，显示统计
    if signal_normal_count > 0:
        normal_signals = recent[(recent['信号分数_num'] > 0) & (recent['信号分数_num'] < 100)]
        avg_signal = normal_signals['信号分数_num'].mean()
        print(f"正常信号分数:")
        print(f"  平均值: {avg_signal:.1f}")
        print(f"  范围: {normal_signals['信号分数_num'].min():.0f} - {normal_signals['信号分数_num'].max():.0f}")
    
    if consensus_normal_count > 0:
        normal_consensus = recent[recent['共振指标数_num'] > 0]
        avg_consensus = normal_consensus['共振指标数_num'].mean()
        print(f"正常共振指标数:")
        print(f"  平均值: {avg_consensus:.1f}")
        print(f"  范围: {normal_consensus['共振指标数_num'].min():.0f} - {normal_consensus['共振指标数_num'].max():.0f}")
    
    print("")
    
    # 判断
    if signal_100_count == 0 and signal_normal_count > 0:
        print("✅ 修复已生效！不再出现100.0异常值")
    elif signal_100_count > 5:
        print("❌ 仍有大量100.0异常值，可能修复未生效")
    else:
        print("⚠️  少量100.0值可能是旧数据")

except FileNotFoundError:
    print("❌ trades_history.csv 不存在")
except Exception as e:
    print(f"❌ 分析失败: {e}")
    import traceback
    traceback.print_exc()
EOF

echo ""
echo "=========================================="
echo "✅ 验证完成"
echo "=========================================="
echo ""
echo "如果看到异常值，建议:"
echo "  1. 确认系统已重启"
echo "  2. 等待新订单开仓"
echo "  3. 查看日志: tail -f ~/10-23-bot/logs/${MODEL}_*.log"

