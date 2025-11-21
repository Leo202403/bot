#!/bin/bash
# 重建CSV - 只保留字段数完全正确的行

echo "=========================================="
echo "🔧 重建干净的CSV文件"
echo "=========================================="
echo ""

DS_FILE="/root/10-23-bot/ds/trading_data/deepseek/trades_history.csv"

# 1. 备份
BACKUP_FILE="${DS_FILE}.before_rebuild_$(date +%Y%m%d_%H%M%S)"
echo "【步骤1】备份原文件..."
cp "$DS_FILE" "$BACKUP_FILE"
echo "✓ 已备份到: $BACKUP_FILE"
echo ""

# 2. 使用Python重建CSV
echo "【步骤2】重建CSV文件..."
python3 << 'PYEOF'
import re

# 读取表头
with open('/root/10-23-bot/ds/trading_data/deepseek/trades_history.csv', 'r', encoding='utf-8') as f:
    header = f.readline().strip()
    lines = f.readlines()

# 计算表头字段数（简单计数逗号）
# 注意：引号内的逗号不算
def count_csv_fields(line):
    """正确计数CSV字段数"""
    in_quotes = False
    field_count = 1  # 至少有一个字段
    
    for char in line:
        if char == '"':
            in_quotes = not in_quotes
        elif char == ',' and not in_quotes:
            field_count += 1
    
    return field_count

header_fields = count_csv_fields(header)
print(f"表头字段数: {header_fields}")

# 重建CSV
clean_lines = [header]
removed = []
total = 0

for i, line in enumerate(lines, start=2):
    total += 1
    line = line.strip()
    if not line:
        continue
    
    fields_count = count_csv_fields(line)
    
    # 如果字段数不匹配
    if fields_count != header_fields:
        removed.append(i)
        if len(removed) <= 10:  # 只显示前10行
            print(f"  第 {i} 行字段数不匹配: 期望{header_fields}, 实际{fields_count}")
        continue
    
    # 检查关键字段（前两个字段：开仓时间和平仓时间）
    parts = line.split(',', 3)  # 只分割前3个逗号
    open_time = parts[0] if len(parts) > 0 else ''
    close_time = parts[1] if len(parts) > 1 else ''
    
    # 如果开仓时间和平仓时间都为空，跳过
    if not open_time.strip() and not close_time.strip():
        removed.append(i)
        if len(removed) <= 10:
            print(f"  第 {i} 行时间字段都为空")
        continue
    
    clean_lines.append(line)

print(f"\n✓ 原始数据行: {total}")
print(f"✓ 删除问题行: {len(removed)}")
print(f"✓ 保留数据行: {len(clean_lines) - 1}")

if len(removed) > 10:
    print(f"\n问题行号（仅显示前10个）: {removed[:10]}")
else:
    print(f"\n问题行号: {removed}")

# 写入新文件
with open('/root/10-23-bot/ds/trading_data/deepseek/trades_history.csv', 'w', encoding='utf-8') as f:
    f.write('\n'.join(clean_lines) + '\n')

print("\n✓ 文件已重建")
PYEOF

if [ $? -ne 0 ]; then
    echo "❌ 重建失败，恢复备份..."
    cp "$BACKUP_FILE" "$DS_FILE"
    exit 1
fi

echo ""

# 3. 最终验证
echo "【步骤3】最终验证..."
python3 << 'PYEOF'
import csv

try:
    with open('/root/10-23-bot/ds/trading_data/deepseek/trades_history.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        
        # 检查表头
        if None in reader.fieldnames:
            print(f"❌ 表头仍有None字段")
            print(f"字段名: {reader.fieldnames}")
            exit(1)
        
        print(f"✓ 表头正常: {len(reader.fieldnames)} 个字段")
        
        count = 0
        closed = 0
        opening = 0
        
        for i, row in enumerate(reader, start=2):
            # 检查None字段
            if None in row:
                print(f"❌ 第 {i} 行仍有None字段")
                print(f"  行内容: {list(row.keys())}")
                exit(1)
            
            count += 1
            if row.get('平仓时间', '').strip():
                closed += 1
            elif row.get('开仓时间', '').strip():
                opening += 1
        
        print(f"✓ 无None字段")
        print(f"✓ 总记录数: {count}")
        print(f"✓ 已平仓交易: {closed}")
        print(f"✓ 持仓中交易: {opening}")
        print(f"\n✅ CSV文件完全正常！")
        
except Exception as e:
    print(f"❌ 验证失败: {e}")
    import traceback
    traceback.print_exc()
    exit(1)
PYEOF

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ 验证失败，恢复备份..."
    cp "$BACKUP_FILE" "$DS_FILE"
    exit 1
fi

echo ""
echo "=========================================="
echo "✅ CSV重建完成！"
echo "=========================================="
echo ""
echo "📝 下一步："
echo "  cd /root/pythonc程序/my_project"
echo "  pkill -f 'python.*每日壁纸更换.py'"
echo "  nohup python3 每日壁纸更换.py > nohup.out 2>&1 &"
echo "  sleep 3"
echo "  cd /root/10-23-bot/ds && ./test_api.sh"
echo ""

