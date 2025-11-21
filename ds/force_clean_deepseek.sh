#!/bin/bash
# 强力清理 DeepSeek CSV - 直接删除所有空记录和问题行

echo "=========================================="
echo "🔧 强力清理 DeepSeek CSV"
echo "=========================================="
echo ""

DS_FILE="/root/10-23-bot/ds/trading_data/deepseek/trades_history.csv"

if [ ! -f "$DS_FILE" ]; then
    echo "❌ 文件不存在: $DS_FILE"
    exit 1
fi

# 1. 备份原文件
BACKUP_FILE="${DS_FILE}.before_force_clean_$(date +%Y%m%d_%H%M%S)"
echo "【步骤1】备份原文件..."
cp "$DS_FILE" "$BACKUP_FILE"
echo "✓ 已备份到: $BACKUP_FILE"
echo ""

# 2. 获取表头
echo "【步骤2】保存表头..."
HEADER=$(head -1 "$DS_FILE")
FIELD_COUNT=$(echo "$HEADER" | awk -F',' '{print NF}')
echo "表头字段数: $FIELD_COUNT"
echo ""

# 3. 强力清理：只保留字段数正确且有有效数据的行
echo "【步骤3】强力清理数据..."
python3 << PYEOF
try:
    header = '$HEADER'
    field_count = $FIELD_COUNT
    
    with open('$DS_FILE', 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # 保留表头
    clean_lines = [header.strip()]
    removed = 0
    
    for i, line in enumerate(lines[1:], start=2):
        line = line.strip()
        if not line:
            removed += 1
            continue
        
        # 按逗号分割，精确匹配字段数
        fields = line.split(',')
        
        # 如果字段数不对，尝试截断或跳过
        if len(fields) != field_count:
            # 截断到正确的字段数
            fields = fields[:field_count]
        
        # 检查是否是完全空的记录（前4个关键字段都为空）
        coin = fields[2].strip() if len(fields) > 2 else ''
        direction = fields[3].strip() if len(fields) > 3 else ''
        open_time = fields[0].strip() if len(fields) > 0 else ''
        close_time = fields[1].strip() if len(fields) > 1 else ''
        
        # 如果开仓时间和平仓时间都为空，跳过
        if not open_time and not close_time:
            print(f"删除第 {i} 行: 时间字段都为空")
            removed += 1
            continue
        
        # 重新组合成正确的行
        clean_line = ','.join(fields)
        clean_lines.append(clean_line)
    
    print(f"\n✓ 删除了 {removed} 行")
    print(f"✓ 保留了 {len(clean_lines) - 1} 行数据")
    
    # 写回文件
    with open('$DS_FILE', 'w', encoding='utf-8') as f:
        f.write('\n'.join(clean_lines) + '\n')
    
    print("✓ 文件已保存")
    
except Exception as e:
    print(f"❌ 清理失败: {e}")
    import traceback
    traceback.print_exc()
    exit(1)
PYEOF

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ 清理失败，恢复备份..."
    cp "$BACKUP_FILE" "$DS_FILE"
    exit 1
fi

echo ""

# 4. 检查结果
echo "【步骤4】检查清理结果..."
echo ""
echo "最后5行:"
tail -5 "$DS_FILE"
echo ""
echo "总行数: $(wc -l < "$DS_FILE")"
echo ""

# 5. 验证CSV格式
echo "【步骤5】验证CSV格式..."
python3 << 'PYEOF'
import csv

try:
    with open('/root/10-23-bot/ds/trading_data/deepseek/trades_history.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        
        # 检查字段名
        if None in reader.fieldnames:
            print(f"❌ 仍存在 None 字段名")
            print(f"字段名: {reader.fieldnames}")
            exit(1)
        
        print(f"✓ 字段名正常: {len(reader.fieldnames)} 个字段")
        
        count = 0
        closed = 0
        opening = 0
        
        for i, row in enumerate(reader, start=2):
            if None in row:
                print(f"❌ 第 {i} 行包含 None 字段")
                exit(1)
            
            count += 1
            if row.get('平仓时间', '').strip():
                closed += 1
            elif row.get('开仓时间', '').strip():
                opening += 1
        
        print(f"✓ 总记录: {count}")
        print(f"✓ 已平仓: {closed}")
        print(f"✓ 持仓中: {opening}")
        print(f"\n✅ CSV格式验证通过！")
        
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
echo "✅ 强力清理完成！"
echo "=========================================="
echo ""
echo "📝 下一步："
echo "  cd /root/pythonc程序/my_project"
echo "  pkill -f 'python.*每日壁纸更换.py'"
echo "  nohup python3 每日壁纸更换.py > nohup.out 2>&1 &"
echo "  sleep 3"
echo "  cd /root/10-23-bot/ds && ./test_api.sh"
echo ""

