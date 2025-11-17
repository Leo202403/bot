#!/bin/bash

echo "=========================================="
echo "回测盈利但实盘亏损 - 系统诊断"
echo "=========================================="
echo ""

MODEL="qwen"  # 可以改为deepseek

echo "1. 检查当前配置参数"
echo "=========================================="
if [ -f "/root/10-23-bot/ds/trading_data/$MODEL/learning_config.json" ]; then
    echo "✓ learning_config.json 存在"
    echo ""
    echo "Scalping参数:"
    cat /root/10-23-bot/ds/trading_data/$MODEL/learning_config.json | jq '.scalping_params | {min_risk_reward, atr_tp_multiplier, atr_stop_multiplier, max_holding_hours, min_signal_score}'
    echo ""
    echo "Swing参数:"
    cat /root/10-23-bot/ds/trading_data/$MODEL/learning_config.json | jq '.swing_params | {min_risk_reward, atr_tp_multiplier, atr_stop_multiplier, max_holding_hours, min_signal_score}'
else
    echo "❌ learning_config.json 不存在"
fi
echo ""

echo "2. 检查最近的交易记录（最新5笔）"
echo "=========================================="
if [ -f "/root/10-23-bot/ds/trading_data/$MODEL/trades_history.csv" ]; then
    echo "开仓时间,币种,方向,仓位,杠杆,盈亏比,盈亏(U),信号分数,共振数"
    tail -n 5 /root/10-23-bot/ds/trading_data/$MODEL/trades_history.csv | awk -F',' '{print $1","$3","$4","$8","$9","$12","$13","$16","$17}'
else
    echo "❌ trades_history.csv 不存在"
fi
echo ""

echo "3. 计算回测期 vs 实盘期的平均盈亏"
echo "=========================================="
python3 << 'EOF'
import pandas as pd
import sys

try:
    df = pd.read_csv('/root/10-23-bot/ds/trading_data/qwen/trades_history.csv')
    
    # 只统计已平仓的订单
    df_closed = df[df['平仓时间'].notna()].copy()
    
    if len(df_closed) == 0:
        print("⚠️ 没有已平仓的订单")
        sys.exit(0)
    
    # 转换时间
    df_closed['开仓时间'] = pd.to_datetime(df_closed['开仓时间'])
    
    # 回测期（11-04 ~ 11-16）
    backtest = df_closed[(df_closed['开仓时间'] >= '2025-11-04') & (df_closed['开仓时间'] < '2025-11-17')]
    
    # 实盘期（11-17+）
    live = df_closed[df_closed['开仓时间'] >= '2025-11-17']
    
    print(f"回测期（11-04~11-16）:")
    if len(backtest) > 0:
        print(f"  总笔数: {len(backtest)}")
        print(f"  盈利笔数: {len(backtest[backtest['盈亏(U)'] > 0])}")
        print(f"  胜率: {len(backtest[backtest['盈亏(U)'] > 0]) / len(backtest) * 100:.1f}%")
        print(f"  平均盈亏: {backtest['盈亏(U)'].mean():.3f}U")
        print(f"  总盈亏: {backtest['盈亏(U)'].sum():.2f}U")
    else:
        print("  无数据")
    
    print(f"\n实盘期（11-17+）:")
    if len(live) > 0:
        print(f"  总笔数: {len(live)}")
        print(f"  盈利笔数: {len(live[live['盈亏(U)'] > 0])}")
        print(f"  胜率: {len(live[live['盈亏(U)'] > 0]) / len(live) * 100:.1f}%")
        print(f"  平均盈亏: {live['盈亏(U)'].mean():.3f}U")
        print(f"  总盈亏: {live['盈亏(U)'].sum():.2f}U")
    else:
        print("  无数据（可能今天还没有平仓订单）")
    
    if len(backtest) > 0 and len(live) > 0:
        diff = live['盈亏(U)'].mean() - backtest['盈亏(U)'].mean()
        print(f"\n📊 差距: {diff:+.3f}U")
        if diff < -0.1:
            print("  ⚠️ 实盘表现明显差于回测期")
        elif diff > 0.1:
            print("  ✅ 实盘表现好于回测期")
        else:
            print("  ≈ 实盘表现与回测期持平")

except FileNotFoundError:
    print("❌ trades_history.csv 不存在")
except Exception as e:
    print(f"❌ 分析失败: {e}")
EOF
echo ""

echo "4. 检查最近的AI决策记录"
echo "=========================================="
AI_DECISIONS_DIR="/root/10-23-bot/ds/trading_data/$MODEL/ai_decisions"
if [ -d "$AI_DECISIONS_DIR" ]; then
    LATEST_FILE=$(ls -t $AI_DECISIONS_DIR/*.json 2>/dev/null | head -1)
    if [ -n "$LATEST_FILE" ]; then
        echo "最近的AI决策文件: $(basename $LATEST_FILE)"
        echo ""
        echo "AI决策的操作:"
        cat $LATEST_FILE | jq -r '.actions[]? | "\(.action) \(.symbol) - 理由前100字: \(.reason[0:100])"' | head -n 5
    else
        echo "⚠️ 没有AI决策记录"
    fi
else
    echo "❌ ai_decisions目录不存在"
fi
echo ""

echo "5. 检查参数调整记录"
echo "=========================================="
if [ -f "/root/10-23-bot/ds/trading_data/$MODEL/_iterative_history" ]; then
    echo "迭代历史:"
    cat /root/10-23-bot/ds/trading_data/$MODEL/learning_config.json | jq '._iterative_history | {total_rounds, last_updated: .phase2.timestamp}'
else
    echo "⚠️ 未找到迭代历史"
fi
echo ""

echo "6. 诊断结论"
echo "=========================================="
python3 << 'EOF'
import json
import pandas as pd

try:
    # 读取配置
    with open('/root/10-23-bot/ds/trading_data/qwen/learning_config.json', 'r') as f:
        config = json.load(f)
    
    scalp = config.get('scalping_params', {})
    swing = config.get('swing_params', {})
    
    issues = []
    
    # 检查1：参数是否是默认值
    if scalp.get('min_risk_reward') == 2.0:
        issues.append("⚠️ Scalping的min_risk_reward=2.0（可能是默认值，未经优化）")
    
    if scalp.get('atr_tp_multiplier') == 2.5 and scalp.get('atr_stop_multiplier') == 1.5:
        issues.append("⚠️ Scalping的ATR倍数=2.5/1.5（可能是默认值）")
    
    # 检查2：读取交易记录
    try:
        df = pd.read_csv('/root/10-23-bot/ds/trading_data/qwen/trades_history.csv')
        df_closed = df[df['平仓时间'].notna()].copy()
        
        if len(df_closed) > 0:
            # 检查实际盈亏比
            df_closed['实际RR'] = abs(df_closed['盈亏(U)'] / (df_closed['开仓价格'] * df_closed['数量'] / df_closed['杠杆率']))
            actual_rr = df_closed['实际RR'].median()
            expected_rr = scalp.get('min_risk_reward', 2.0)
            
            if actual_rr < expected_rr * 0.5:
                issues.append(f"⚠️ 实际R:R({actual_rr:.2f})远低于预期({expected_rr:.2f})")
            
            # 检查胜率
            win_rate = len(df_closed[df_closed['盈亏(U)'] > 0]) / len(df_closed)
            if win_rate < 0.4:
                issues.append(f"⚠️ 胜率过低({win_rate*100:.0f}%)")
        
    except:
        pass
    
    print("\n诊断结果:")
    if issues:
        for issue in issues:
            print(issue)
        print("\n建议:")
        print("1. 检查learning_config.json是否包含最新优化的参数")
        print("2. 检查AI决策是否遵循这些参数")
        print("3. 考虑增加回测数据量（从14天增加到30天）")
    else:
        print("✅ 参数配置看起来正常")
        print("\n可能的原因:")
        print("1. 市场环境变化（回测期和实盘期市场不同）")
        print("2. AI过早平仓（检查平仓理由）")
        print("3. 滑点和执行延迟")
        print("4. 样本量不足（需要更多数据验证）")

except Exception as e:
    print(f"❌ 诊断失败: {e}")
EOF
echo ""

echo "=========================================="
echo "✅ 诊断完成"
echo "=========================================="
echo ""
echo "详细分析文档: ds/回测盈利实盘亏损根本原因分析.md"

