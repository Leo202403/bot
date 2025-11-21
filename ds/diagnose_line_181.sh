#!/bin/bash
# 诊断第181行的具体问题

echo "=========================================="
echo "🔍 诊断 DeepSeek CSV 第181行问题"
echo "=========================================="
echo ""

DS_FILE="/root/10-23-bot/ds/trading_data/deepseek/trades_history.csv"

echo "【步骤1】显示第180-182行原始内容"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
sed -n '180,182p' "$DS_FILE"
echo ""

echo "【步骤2】分析第181行字段"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
python3 << 'PYEOF'
import csv

with open('/root/10-23-bot/ds/trading_data/deepseek/trades_history.csv', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 显示表头
print("表头:")
print(lines[0].strip())
print(f"\n表头字段数: {len(lines[0].split(','))}")

# 显示第181行（实际索引180）
if len(lines) > 181:
    print(f"\n第181行:")
    print(lines[180].strip())
    print(f"\n第181行字段数: {len(lines[180].split(','))}")
    
    # 分析字段
    fields = lines[180].split(',')
    print(f"\n字段详情:")
    for i, field in enumerate(fields[:10]):  # 只显示前10个
        print(f"  字段{i+1}: '{field}'")

# 尝试用CSV读取
print("\n【使用CSV库读取】")
try:
    with open('/root/10-23-bot/ds/trading_data/deepseek/trades_history.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        
        print(f"字段名列表: {reader.fieldnames}")
        print(f"是否有None: {None in reader.fieldnames}")
        
        for i, row in enumerate(reader, start=2):
            if i == 181:
                print(f"\n第181行字段:")
                for key, value in row.items():
                    if key is None or key == 'None':
                        print(f"  ❌ 字段名为None的值: '{value}'")
                    else:
                        print(f"  {key}: '{value}'")
                
                # 检查是否有None key
                if None in row:
                    print(f"\n❌ 发现None字段，值为: '{row[None]}'")
                break
except Exception as e:
    print(f"CSV读取错误: {e}")
    import traceback
    traceback.print_exc()
PYEOF

