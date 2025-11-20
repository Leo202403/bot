#!/bin/bash
# 【V8.5.2.4.89.3】数据恢复阶段3: 14天/2000机会（全量）

echo "========================================="
echo "📊 阶段3数据恢复: 14天/2000机会（全量）"
echo "========================================="
echo ""

# 修改参数
echo "1️⃣ 修改deepseek配置..."
sed -i 's/LOOKBACK_DAYS = 7/LOOKBACK_DAYS = 14/g' /root/10-23-bot/ds/deepseek_多币种智能版.py
sed -i 's/max_profit_opportunities=1000/max_profit_opportunities=2000/g' /root/10-23-bot/ds/deepseek_多币种智能版.py
sed -i 's/max_scalping_opportunities=1000/max_scalping_opportunities=2000/g' /root/10-23-bot/ds/deepseek_多币种智能版.py
sed -i 's/max_swing_opportunities=1000/max_swing_opportunities=2000/g' /root/10-23-bot/ds/deepseek_多币种智能版.py
sed -i 's/max_combinations=400/max_combinations=800/g' /root/10-23-bot/ds/deepseek_多币种智能版.py
sed -i 's/sample_size=500/sample_size=1000/g' /root/10-23-bot/ds/qwen_多币种智能版.py

echo "2️⃣ 修改qwen配置..."
sed -i 's/LOOKBACK_DAYS = 7/LOOKBACK_DAYS = 14/g' /root/10-23-bot/ds/qwen_多币种智能版.py
sed -i 's/max_profit_opportunities=1000/max_profit_opportunities=2000/g' /root/10-23-bot/ds/qwen_多币种智能版.py
sed -i 's/max_scalping_opportunities=1000/max_scalping_opportunities=2000/g' /root/10-23-bot/ds/qwen_多币种智能版.py
sed -i 's/max_swing_opportunities=1000/max_swing_opportunities=2000/g' /root/10-23-bot/ds/qwen_多币种智能版.py
sed -i 's/max_combinations=400/max_combinations=800/g' /root/10-23-bot/ds/qwen_多币种智能版.py
sed -i 's/sample_size=500/sample_size=1000/g' /root/10-23-bot/ds/qwen_多币种智能版.py

echo ""
echo "✅ 阶段3配置完成（已恢复全量）"
echo ""
echo "📋 新配置:"
echo "   - 回看天数: 14天（原7天）"
echo "   - 机会数: 2000个（原1000个）"
echo "   - 组合数: 800组（原400组）"
echo "   - 样本数: 1000个（原500个）"
echo ""
echo "🚀 运行测试:"
echo "   cd /root/10-23-bot/ds"
echo "   MANUAL_BACKTEST=true python3 run_with_memory_monitor.py > /tmp/backtest_stage3.txt 2>&1 &"
echo "   tail -f /tmp/backtest_stage3.txt"
echo ""
echo "📊 监控内存:"
echo "   cat memory_monitor_simple.log | awk -F',' '{print \$2,\$3}' | sort -n | tail -5"
echo ""
echo "🎉 如果成功，数据已完全恢复！"
echo ""

