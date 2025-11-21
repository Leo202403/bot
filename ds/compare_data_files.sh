#!/bin/bash
# 对比 DeepSeek 和 Qwen 的数据文件，找出 DeepSeek 不显示的原因

echo "=========================================="
echo "📊 对比 DeepSeek 和 Qwen 数据文件"
echo "=========================================="
echo ""

DS_DIR="/root/10-23-bot/ds/trading_data/deepseek"
QW_DIR="/root/10-23-bot/ds/trading_data/qwen"

# 1. 对比 trades_history.csv 表头
echo "【1】trades_history.csv 表头对比"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "DeepSeek 表头:"
if [ -f "$DS_DIR/trades_history.csv" ]; then
    head -1 "$DS_DIR/trades_history.csv"
else
    echo "❌ 文件不存在: $DS_DIR/trades_history.csv"
fi
echo ""
echo "Qwen 表头:"
if [ -f "$QW_DIR/trades_history.csv" ]; then
    head -1 "$QW_DIR/trades_history.csv"
else
    echo "❌ 文件不存在: $QW_DIR/trades_history.csv"
fi
echo ""

# 2. 检查记录数
echo "【2】记录数对比"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
if [ -f "$DS_DIR/trades_history.csv" ]; then
    DS_COUNT=$(wc -l < "$DS_DIR/trades_history.csv")
    echo "DeepSeek 总行数: $DS_COUNT (包含表头)"
    echo "DeepSeek 数据行数: $((DS_COUNT - 1))"
else
    echo "❌ DeepSeek 文件不存在"
fi
echo ""
if [ -f "$QW_DIR/trades_history.csv" ]; then
    QW_COUNT=$(wc -l < "$QW_DIR/trades_history.csv")
    echo "Qwen 总行数: $QW_COUNT (包含表头)"
    echo "Qwen 数据行数: $((QW_COUNT - 1))"
else
    echo "❌ Qwen 文件不存在"
fi
echo ""

# 3. 检查前3条数据记录（跳过表头）
echo "【3】前3条数据记录"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "DeepSeek 前3条:"
if [ -f "$DS_DIR/trades_history.csv" ]; then
    head -4 "$DS_DIR/trades_history.csv" | tail -3
else
    echo "❌ 文件不存在"
fi
echo ""
echo "Qwen 前3条:"
if [ -f "$QW_DIR/trades_history.csv" ]; then
    head -4 "$QW_DIR/trades_history.csv" | tail -3
else
    echo "❌ 文件不存在"
fi
echo ""

# 4. 检查最后3条记录
echo "【4】最后3条记录"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "DeepSeek 最后3条:"
if [ -f "$DS_DIR/trades_history.csv" ]; then
    tail -3 "$DS_DIR/trades_history.csv"
else
    echo "❌ 文件不存在"
fi
echo ""
echo "Qwen 最后3条:"
if [ -f "$QW_DIR/trades_history.csv" ]; then
    tail -3 "$QW_DIR/trades_history.csv"
else
    echo "❌ 文件不存在"
fi
echo ""

# 5. 对比 system_status.json
echo "【5】system_status.json 对比"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "DeepSeek system_status.json:"
if [ -f "$DS_DIR/system_status.json" ]; then
    cat "$DS_DIR/system_status.json" | python3 -m json.tool 2>&1
else
    echo "❌ 文件不存在: $DS_DIR/system_status.json"
fi
echo ""
echo "Qwen system_status.json:"
if [ -f "$QW_DIR/system_status.json" ]; then
    cat "$QW_DIR/system_status.json" | python3 -m json.tool 2>&1
else
    echo "❌ 文件不存在: $QW_DIR/system_status.json"
fi
echo ""

# 6. 检查字段分隔符和特殊字符
echo "【6】CSV 格式详细检查（前100字符）"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "DeepSeek 表头（十六进制）:"
if [ -f "$DS_DIR/trades_history.csv" ]; then
    head -1 "$DS_DIR/trades_history.csv" | cut -c1-100 | od -c
else
    echo "❌ 文件不存在"
fi
echo ""
echo "Qwen 表头（十六进制）:"
if [ -f "$QW_DIR/trades_history.csv" ]; then
    head -1 "$QW_DIR/trades_history.csv" | cut -c1-100 | od -c
else
    echo "❌ 文件不存在"
fi
echo ""

# 7. 检查空字段
echo "【7】检查空字段情况"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "检查 DeepSeek 是否有空的关键字段..."
if [ -f "$DS_DIR/trades_history.csv" ]; then
    python3 << 'PYEOF'
import csv

try:
    with open('/root/10-23-bot/ds/trading_data/deepseek/trades_history.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        count = 0
        empty_fields = {}
        for row in reader:
            count += 1
            for key, value in row.items():
                if not value or value.strip() == '':
                    if key not in empty_fields:
                        empty_fields[key] = 0
                    empty_fields[key] += 1
        
        print(f"DeepSeek 总记录数: {count}")
        if empty_fields:
            print("发现空字段:")
            for field, cnt in sorted(empty_fields.items(), key=lambda x: -x[1]):
                print(f"  - {field}: {cnt} 条记录为空")
        else:
            print("✓ 所有字段都有值")
except Exception as e:
    print(f"❌ 检查失败: {e}")
PYEOF
else
    echo "❌ 文件不存在"
fi
echo ""

echo "检查 Qwen 是否有空的关键字段..."
if [ -f "$QW_DIR/trades_history.csv" ]; then
    python3 << 'PYEOF'
import csv

try:
    with open('/root/10-23-bot/ds/trading_data/qwen/trades_history.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        count = 0
        empty_fields = {}
        for row in reader:
            count += 1
            for key, value in row.items():
                if not value or value.strip() == '':
                    if key not in empty_fields:
                        empty_fields[key] = 0
                    empty_fields[key] += 1
        
        print(f"Qwen 总记录数: {count}")
        if empty_fields:
            print("发现空字段:")
            for field, cnt in sorted(empty_fields.items(), key=lambda x: -x[1]):
                print(f"  - {field}: {cnt} 条记录为空")
        else:
            print("✓ 所有字段都有值")
except Exception as e:
    print(f"❌ 检查失败: {e}")
PYEOF
else
    echo "❌ 文件不存在"
fi
echo ""

# 8. 模拟后端读取
echo "【8】模拟后端读取 CSV"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "测试后端读取 DeepSeek CSV..."
python3 << 'PYEOF'
import csv

try:
    with open('/root/10-23-bot/ds/trading_data/deepseek/trades_history.csv', 'r', encoding='utf-8') as tf:
        trades_reader = csv.DictReader(tf)
        # 模拟后端的字段清理
        trades_reader.fieldnames = [name.strip() if name else name for name in trades_reader.fieldnames]
        
        print(f"✓ 字段名: {trades_reader.fieldnames}")
        
        all_trades = []
        for i, trade in enumerate(trades_reader):
            trade_cleaned = {k.strip() if k else k: v for k, v in trade.items()}
            all_trades.append(trade_cleaned)
            if i < 2:  # 只显示前2条
                print(f"\n记录 {i+1}:")
                for k, v in trade_cleaned.items():
                    print(f"  {k}: {v}")
        
        print(f"\n✓ 成功读取 {len(all_trades)} 条记录")
        
        # 检查已平仓交易
        closed_trades = [t for t in all_trades if t.get('平仓时间') and t.get('平仓时间').strip()]
        print(f"✓ 已平仓交易: {len(closed_trades)} 条")
        
except Exception as e:
    print(f"❌ 读取失败: {e}")
    import traceback
    traceback.print_exc()
PYEOF
echo ""

echo "=========================================="
echo "✅ 对比完成"
echo "=========================================="

