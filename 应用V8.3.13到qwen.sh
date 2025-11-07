#!/bin/bash
# 应用V8.3.13到qwen

echo "📦 开始同步V8.3.13到qwen..."

cd ds

# 备份qwen
cp qwen_多币种智能版.py qwen_backup_before_v8313.py
echo "✓ 已备份qwen"

# 方法：直接复制deepseek的V8.3.13代码段

# 1. 提取get_pattern_based_tp_sl (行8472-8527)
sed -n '8472,8527p' deepseek_多币种智能版.py > /tmp/func1.txt
echo "✓ 提取func1: $(wc -l < /tmp/func1.txt)行"

# 2. 提取_simulate_trade_with_params_enhanced (行16910-17022)
sed -n '16910,17022p' deepseek_多币种智能版.py > /tmp/func2.txt
echo "✓ 提取func2: $(wc -l < /tmp/func2.txt)行"

# 3. 提取Per-Symbol等所有函数 (行18051-18350)
sed -n '18051,18350p' deepseek_多币种智能版.py > /tmp/func3.txt
echo "✓ 提取func3: $(wc -l < /tmp/func3.txt)行"

# 找到qwen的插入位置并插入
# 位置1: detect_breakout_candle之前插入func1
line1=$(grep -n "def detect_breakout_candle(curr_ohlc, prev_high, avg_volume):" qwen_多币种智能版.py | head -1 | cut -d: -f1)
echo "✓ 找到插入位置1: 行$line1"

# 位置2: _simulate_trade_with_params之前插入func2  
line2=$(grep -n "def _simulate_trade_with_params(entry_price, direction, atr, future_data," qwen_多币种智能版.py | head -1 | cut -d: -f1)
echo "✓ 找到插入位置2: 行$line2"

# 位置3: analyze_missed_opportunities之前插入func3
line3=$(grep -n "def analyze_missed_opportunities(trends, actual_trades, config):" qwen_多币种智能版.py | head -1 | cut -d: -f1)
echo "✓ 找到插入位置3: 行$line3"

# 执行插入（从后往前，避免行号变化）
# 插入func3
if [ ! -z "$line3" ]; then
    { head -n $((line3-1)) qwen_多币种智能版.py; cat /tmp/func3.txt; echo ""; tail -n +$line3 qwen_多币种智能版.py; } > qwen_temp1.py
    mv qwen_temp1.py qwen_多币种智能版.py
    echo "✓ 已插入Per-Symbol等函数"
fi

# 重新找位置2（因为文件已变化）
line2=$(grep -n "def _simulate_trade_with_params(entry_price, direction, atr, future_data," qwen_多币种智能版.py | head -1 | cut -d: -f1)
# 插入func2
if [ ! -z "$line2" ]; then
    { head -n $((line2-1)) qwen_多币种智能版.py; cat /tmp/func2.txt; echo ""; echo ""; tail -n +$line2 qwen_多币种智能版.py; } > qwen_temp2.py
    mv qwen_temp2.py qwen_多币种智能版.py
    echo "✓ 已插入增强版模拟函数"
fi

# 重新找位置1
line1=$(grep -n "def detect_breakout_candle(curr_ohlc, prev_high, avg_volume):" qwen_多币种智能版.py | head -1 | cut -d: -f1)
# 插入func1
if [ ! -z "$line1" ]; then
    { head -n $((line1-1)) qwen_多币种智能版.py; cat /tmp/func1.txt; echo ""; tail -n +$line1 qwen_多币种智能版.py; } > qwen_temp3.py
    mv qwen_temp3.py qwen_多币种智能版.py
    echo "✓ 已插入形态识别函数"
fi

# 验证
echo ""
echo "📊 验证结果:"
wc -l qwen_多币种智能版.py
python3 -m py_compile qwen_多币种智能版.py && echo "✅ Qwen语法正确" || echo "❌ 语法错误"

# 清理临时文件
rm -f /tmp/func*.txt

echo ""
echo "✅ V8.3.13同步完成！"
