#!/bin/bash
# 验证AI自主学习闭环是否正常工作

echo "==========================================="
echo "🔍 AI自主学习闭环验证工具"
echo "==========================================="
echo ""

MODEL=${1:-deepseek}
CONFIG_FILE="/root/10-23-bot/ds/trading_data/$MODEL/learning_config.json"
LOG_FILE="/root/10-23-bot/ds/logs/${MODEL}_trading.log"

# 检查1：配置文件是否存在
echo "【1】检查配置文件..."
if [ -f "$CONFIG_FILE" ]; then
    echo "✅ 配置文件存在: $CONFIG_FILE"
else
    echo "❌ 配置文件不存在！"
    exit 1
fi

# 检查2：是否有V8.3.21优化结果
echo ""
echo "【2】检查参数优化结果..."
v8321=$(cat "$CONFIG_FILE" | python3 -c "import sys, json; d=json.load(sys.stdin); print('yes' if d.get('compressed_insights', {}).get('v8321_insights') else 'no')" 2>/dev/null)
if [ "$v8321" = "yes" ]; then
    echo "✅ V8.3.21优化数据存在"
    cat "$CONFIG_FILE" | python3 -c "
import sys, json
d = json.load(sys.stdin)
insights = d.get('compressed_insights', {}).get('v8321_insights', {})
if 'scalping' in insights:
    perf = insights['scalping'].get('performance', {})
    print(f'  超短线: 捕获率{perf.get(\"capture_rate\", 0)*100:.0f}%, 平均利润{perf.get(\"avg_profit\", 0)*100:.1f}%')
if 'swing' in insights:
    perf = insights['swing'].get('performance', {})
    print(f'  波段: 捕获率{perf.get(\"capture_rate\", 0)*100:.0f}%, 平均利润{perf.get(\"avg_profit\", 0)*100:.1f}%')
"
else
    echo "⚠️  V8.3.21优化数据不存在（需要运行回测）"
fi

# 检查3：是否有AI开仓分析
echo ""
echo "【3】检查AI开仓质量分析..."
ai_entry=$(cat "$CONFIG_FILE" | python3 -c "import sys, json; d=json.load(sys.stdin); print('yes' if d.get('compressed_insights', {}).get('ai_entry_analysis') else 'no')" 2>/dev/null)
if [ "$ai_entry" = "yes" ]; then
    echo "✅ AI开仓分析存在"
    cat "$CONFIG_FILE" | python3 -c "
import sys, json
d = json.load(sys.stdin)
analysis = d.get('compressed_insights', {}).get('ai_entry_analysis', {})
print(f'  诊断: {analysis.get(\"diagnosis\", \"N/A\")[:80]}')
print(f'  生成时间: {analysis.get(\"generated_at\", \"N/A\")}')
insights = analysis.get('learning_insights', [])
print(f'  洞察数量: {len(insights)}条')
if insights:
    print(f'  示例: {insights[0][:80]}...')
"
else
    echo "⚠️  AI开仓分析不存在（需要运行手动回测或触发条件）"
fi

# 检查4：是否有AI平仓分析
echo ""
echo "【4】检查AI平仓质量分析..."
ai_exit=$(cat "$CONFIG_FILE" | python3 -c "import sys, json; d=json.load(sys.stdin); print('yes' if d.get('compressed_insights', {}).get('ai_exit_analysis') else 'no')" 2>/dev/null)
if [ "$ai_exit" = "yes" ]; then
    echo "✅ AI平仓分析存在"
    cat "$CONFIG_FILE" | python3 -c "
import sys, json
d = json.load(sys.stdin)
analysis = d.get('compressed_insights', {}).get('ai_exit_analysis', {})
print(f'  诊断: {analysis.get(\"diagnosis\", \"N/A\")[:80]}')
print(f'  生成时间: {analysis.get(\"generated_at\", \"N/A\")}')
insights = analysis.get('learning_insights', [])
print(f'  洞察数量: {len(insights)}条')
if insights:
    print(f'  示例: {insights[0][:80]}...')
"
else
    echo "⚠️  AI平仓分析不存在（需要运行手动回测或触发条件）"
fi

# 检查5：实时AI是否读取洞察
echo ""
echo "【5】检查实时AI应用情况..."
if [ -f "$LOG_FILE" ]; then
    last_context=$(grep "AI Self-Learning Insights" "$LOG_FILE" | tail -1)
    if [ -n "$last_context" ]; then
        echo "✅ 实时AI正在应用历史洞察"
        echo "  最后应用时间: $(grep "AI Self-Learning Insights" "$LOG_FILE" | tail -1 | awk '{print $1, $2}')"
        echo ""
        echo "  详细内容（最近一次）："
        grep -A 30 "AI Self-Learning Insights" "$LOG_FILE" | tail -35 | head -30
    else
        echo "⚠️  日志中未找到AI应用记录（可能还未触发决策）"
    fi
else
    echo "❌ 日志文件不存在: $LOG_FILE"
fi

# 检查6：最近的回测记录
echo ""
echo "【6】检查最近的回测记录..."
last_backtest=$(grep "AI深度学习分析" "$LOG_FILE" 2>/dev/null | tail -1)
if [ -n "$last_backtest" ]; then
    echo "✅ 找到回测记录"
    echo "  最后回测时间: $(echo "$last_backtest" | awk '{print $1, $2}')"
    
    # 显示回测结果摘要
    grep -A 20 "AI深度学习分析" "$LOG_FILE" | tail -25 | head -20
else
    echo "⚠️  未找到回测记录"
fi

# 总结
echo ""
echo "==========================================="
echo "📊 验证总结"
echo "==========================================="
echo ""

all_ok=true
[ "$v8321" != "yes" ] && all_ok=false
[ "$ai_entry" != "yes" ] && all_ok=false
[ "$ai_exit" != "yes" ] && all_ok=false

if [ "$all_ok" = true ]; then
    echo "✅ AI自主学习闭环运行正常！"
    echo ""
    echo "💡 建议操作："
    echo "  - 每周运行一次手动回测：MANUAL_BACKTEST=true python3 ${MODEL}_多币种智能版.py"
    echo "  - 监控实时AI应用效果：tail -f $LOG_FILE | grep 'AI Self-Learning'"
else
    echo "⚠️  部分功能未激活，请运行手动回测："
    echo ""
    echo "  cd /root/10-23-bot/ds"
    echo "  MANUAL_BACKTEST=true python3 ${MODEL}_多币种智能版.py"
    echo ""
    echo "  这将触发AI深度分析并保存洞察"
fi

echo ""

