#!/bin/bash
# 【V8.5.2.4.89.3】数据恢复阶段2: 7天/1000机会

echo "========================================="
echo "📊 阶段2数据恢复: 7天/1000机会"
echo "========================================="
echo ""

# 修改参数
echo "1️⃣ 修改deepseek配置..."
sed -i 's/LOOKBACK_DAYS = 3/LOOKBACK_DAYS = 7/g' /root/10-23-bot/ds/deepseek_多币种智能版.py
sed -i 's/max_profit_opportunities=500/max_profit_opportunities=1000/g' /root/10-23-bot/ds/deepseek_多币种智能版.py
sed -i 's/max_scalping_opportunities=500/max_scalping_opportunities=1000/g' /root/10-23-bot/ds/deepseek_多币种智能版.py
sed -i 's/max_swing_opportunities=500/max_swing_opportunities=1000/g' /root/10-23-bot/ds/deepseek_多币种智能版.py
sed -i 's/max_combinations=200/max_combinations=400/g' /root/10-23-bot/ds/deepseek_多币种智能版.py
sed -i 's/sample_size=250/sample_size=500/g' /root/10-23-bot/ds/deepseek_多币种智能版.py

echo "2️⃣ 修改qwen配置..."
sed -i 's/LOOKBACK_DAYS = 3/LOOKBACK_DAYS = 7/g' /root/10-23-bot/ds/qwen_多币种智能版.py
sed -i 's/max_profit_opportunities=500/max_profit_opportunities=1000/g' /root/10-23-bot/ds/qwen_多币种智能版.py
sed -i 's/max_scalping_opportunities=500/max_scalping_opportunities=1000/g' /root/10-23-bot/ds/qwen_多币种智能版.py
sed -i 's/max_swing_opportunities=500/max_swing_opportunities=1000/g' /root/10-23-bot/ds/qwen_多币种智能版.py
sed -i 's/max_combinations=200/max_combinations=400/g' /root/10-23-bot/ds/qwen_多币种智能版.py
sed -i 's/sample_size=250/sample_size=500/g' /root/10-23-bot/ds/qwen_多币种智能版.py

echo ""
echo "✅ 阶段2配置完成"
echo ""
echo "📋 新配置:"
echo "   - 回看天数: 7天（原3天）"
echo "   - 机会数: 1000个（原500个）"
echo "   - 组合数: 400组（原200组）"
echo "   - 样本数: 500个（原250个）"
echo ""
echo "🚀 运行测试:"
echo "   cd /root/10-23-bot/ds"
echo "   MANUAL_BACKTEST=true python3 run_with_memory_monitor.py > /tmp/backtest_stage2.txt 2>&1 &"
echo "   tail -f /tmp/backtest_stage2.txt"
echo ""
echo "📊 监控内存:"
echo "   cat memory_monitor_simple.log | awk -F',' '{print \$2,\$3}' | sort -n | tail -5"
echo ""

