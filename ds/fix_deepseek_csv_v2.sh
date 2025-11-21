#!/bin/bash
# 修复 DeepSeek CSV 文件格式错误（处理字段数不匹配）

echo "=========================================="
echo "🔧 修复 DeepSeek CSV 字段数不匹配问题"
echo "=========================================="
echo ""

DS_FILE="/root/10-23-bot/ds/trading_data/deepseek/trades_history.csv"

if [ ! -f "$DS_FILE" ]; then
    echo "❌ 文件不存在: $DS_FILE"
    exit 1
fi

# 1. 备份原文件
BACKUP_FILE="${DS_FILE}.before_fix_v2_$(date +%Y%m%d_%H%M%S)"
echo "【步骤1】备份原文件..."
cp "$DS_FILE" "$BACKUP_FILE"
echo "✓ 已备份到: $BACKUP_FILE"
echo ""

# 2. 检查字段数
echo "【步骤2】检查字段数..."
echo ""
HEADER_FIELDS=$(head -1 "$DS_FILE" | awk -F',' '{print NF}')
echo "表头字段数: $HEADER_FIELDS"
echo ""

# 3. 使用 Python 修复字段数不匹配问题
echo "【步骤3】使用 Python 修复字段数问题..."
python3 << PYEOF
import csv
import sys

try:
    input_file = '$DS_FILE'
    
    # 读取表头
    with open(input_file, 'r', encoding='utf-8') as f:
        header_line = f.readline().strip()
        fieldnames = [field.strip() for field in header_line.split(',')]
    
    print(f"✓ 表头字段数: {len(fieldnames)}")
    print(f"✓ 字段名: {fieldnames[:5]}...")
    
    # 读取所有行，修复字段数
    clean_lines = [header_line]
    removed_count = 0
    fixed_count = 0
    
    with open(input_file, 'r', encoding='utf-8') as f:
        f.readline()  # 跳过表头
        
        for line_num, line in enumerate(f, start=2):
            line = line.rstrip('\n')
            if not line.strip():
                continue
            
            fields = line.split(',')
            
            # 如果字段数不匹配
            if len(fields) != len(fieldnames):
                print(f"⚠️  第 {line_num} 行字段数不匹配: 期望 {len(fieldnames)}, 实际 {len(fields)}")
                
                # 如果字段太多，截断
                if len(fields) > len(fieldnames):
                    print(f"   → 截断多余字段: {fields[len(fieldnames):]}")
                    fields = fields[:len(fieldnames)]
                    fixed_count += 1
                # 如果字段太少，补齐空字段
                elif len(fields) < len(fieldnames):
                    print(f"   → 补齐缺失字段")
                    fields.extend([''] * (len(fieldnames) - len(fields)))
                    fixed_count += 1
            
            # 检查关键字段
            coin = fields[2].strip() if len(fields) > 2 else ''
            direction = fields[3].strip() if len(fields) > 3 else ''
            open_time = fields[0].strip() if len(fields) > 0 else ''
            close_time = fields[1].strip() if len(fields) > 1 else ''
            
            # 如果是完全空的记录，跳过
            if not coin and not direction and not open_time and not close_time:
                print(f"   → 删除空记录")
                removed_count += 1
                continue
            
            # 重新组合行
            clean_line = ','.join(fields)
            clean_lines.append(clean_line)
    
    print(f"\n✓ 修复字段数: {fixed_count}")
    print(f"✓ 删除空记录: {removed_count}")
    print(f"✓ 保留记录数: {len(clean_lines) - 1}")
    
    # 写回文件
    with open(input_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(clean_lines))
        if clean_lines[-1]:  # 如果最后一行不为空，添加换行符
            f.write('\n')
    
    print(f"✓ 文件已修复并保存")
    
except Exception as e:
    print(f"❌ 修复失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
PYEOF

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Python 修复失败，恢复备份..."
    cp "$BACKUP_FILE" "$DS_FILE"
    exit 1
fi

echo ""

# 4. 验证修复结果
echo "【步骤4】验证修复结果..."
echo ""
echo "最后5行:"
tail -5 "$DS_FILE"
echo ""
echo "总行数: $(wc -l < "$DS_FILE") (包含表头)"
echo "数据行数: $(($(wc -l < "$DS_FILE") - 1))"
echo ""

# 5. 最终验证
echo "【步骤5】验证数据完整性..."
python3 << 'PYEOF'
import csv

try:
    with open('/root/10-23-bot/ds/trading_data/deepseek/trades_history.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        
        # 检查字段名中是否有 None
        if None in reader.fieldnames:
            print(f"❌ 仍然存在 None 字段名！")
            print(f"字段名: {reader.fieldnames}")
            exit(1)
        
        all_trades = []
        for i, trade in enumerate(reader):
            # 检查字段名
            if None in trade:
                print(f"❌ 第 {i+2} 行存在 None 字段！")
                exit(1)
            all_trades.append(trade)
        
        print(f"✓ 总记录数: {len(all_trades)}")
        
        # 统计已平仓交易
        closed_trades = [t for t in all_trades if t.get('平仓时间', '').strip()]
        print(f"✓ 已平仓交易: {len(closed_trades)}")
        
        # 统计持仓中交易
        open_trades = [t for t in all_trades if t.get('开仓时间', '').strip() and not t.get('平仓时间', '').strip()]
        print(f"✓ 持仓中交易: {len(open_trades)}")
        
        print(f"\n✅ CSV 文件格式正常，无 None 字段！")
        
except Exception as e:
    print(f"❌ 验证失败: {e}")
    import traceback
    traceback.print_exc()
PYEOF

echo ""
echo "=========================================="
echo "✅ 修复完成！"
echo "=========================================="
echo ""
echo "📝 后续步骤："
echo "  1. 重启后端服务"
echo "     cd /root/pythonc程序/my_project"
echo "     pkill -f 'python.*每日壁纸更换.py'"
echo "     nohup python3 每日壁纸更换.py > nohup.out 2>&1 &"
echo ""
echo "  2. 等待3秒后测试"
echo "     sleep 3"
echo "     cd /root/10-23-bot/ds"
echo "     ./test_api.sh"
echo ""
echo "如果还有问题，可以从备份恢复："
echo "  cp $BACKUP_FILE $DS_FILE"
echo ""

