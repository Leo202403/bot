#!/bin/bash
# 批量删除所有包含None字段的问题行

echo "=========================================="
echo "🔧 批量清理所有包含None字段的行"
echo "=========================================="
echo ""

DS_FILE="/root/10-23-bot/ds/trading_data/deepseek/trades_history.csv"

# 1. 备份
BACKUP_FILE="${DS_FILE}.before_batch_clean_$(date +%Y%m%d_%H%M%S)"
echo "【步骤1】备份原文件..."
cp "$DS_FILE" "$BACKUP_FILE"
echo "✓ 已备份到: $BACKUP_FILE"
echo ""

# 2. 找出所有问题行
echo "【步骤2】扫描所有问题行..."
python3 << 'PYEOF'
import csv

problem_lines = []

with open('/root/10-23-bot/ds/trading_data/deepseek/trades_history.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    
    # 检查表头
    if None in reader.fieldnames:
        print(f"❌ 表头本身有None字段，文件可能严重损坏")
        exit(1)
    
    for i, row in enumerate(reader, start=2):
        if None in row:
            problem_lines.append(i)
            print(f"  第 {i} 行有None字段")

if problem_lines:
    print(f"\n✓ 共发现 {len(problem_lines)} 行问题数据")
    print(f"  问题行号: {problem_lines[:20]}")  # 只显示前20个
    if len(problem_lines) > 20:
        print(f"  ... 还有 {len(problem_lines) - 20} 行")
else:
    print(f"\n✓ 没有发现问题行")

# 保存问题行号到文件
with open('/tmp/problem_lines.txt', 'w') as f:
    f.write('\n'.join(map(str, problem_lines)))
PYEOF

if [ $? -ne 0 ]; then
    echo "❌ 扫描失败"
    exit 1
fi

if [ ! -s /tmp/problem_lines.txt ]; then
    echo ""
    echo "✅ 没有问题行，文件已正常！"
    exit 0
fi

echo ""

# 3. 删除所有问题行
echo "【步骤3】删除所有问题行..."
python3 << 'PYEOF'
import csv

# 读取问题行号
with open('/tmp/problem_lines.txt', 'r') as f:
    problem_lines = set(int(line.strip()) for line in f if line.strip())

print(f"准备删除 {len(problem_lines)} 行数据...")

# 读取所有行
with open('/root/10-23-bot/ds/trading_data/deepseek/trades_history.csv', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 保留表头和非问题行
clean_lines = [lines[0]]  # 表头
removed_count = 0

for i, line in enumerate(lines[1:], start=2):
    if i not in problem_lines:
        clean_lines.append(line)
    else:
        removed_count += 1
        if removed_count <= 5:  # 只显示前5行
            print(f"  删除第 {i} 行: {line[:100]}...")

print(f"\n✓ 删除了 {removed_count} 行")
print(f"✓ 保留了 {len(clean_lines) - 1} 行数据")

# 写回文件
with open('/root/10-23-bot/ds/trading_data/deepseek/trades_history.csv', 'w', encoding='utf-8') as f:
    f.writelines(clean_lines)

print("✓ 文件已保存")
PYEOF

if [ $? -ne 0 ]; then
    echo "❌ 删除失败，恢复备份..."
    cp "$BACKUP_FILE" "$DS_FILE"
    exit 1
fi

echo ""

# 4. 最终验证
echo "【步骤4】最终验证..."
python3 << 'PYEOF'
import csv

try:
    with open('/root/10-23-bot/ds/trading_data/deepseek/trades_history.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        
        if None in reader.fieldnames:
            print(f"❌ 表头仍有None字段")
            exit(1)
        
        count = 0
        closed = 0
        opening = 0
        
        for i, row in enumerate(reader, start=2):
            if None in row:
                print(f"❌ 第 {i} 行仍有None字段！")
                exit(1)
            
            count += 1
            if row.get('平仓时间', '').strip():
                closed += 1
            elif row.get('开仓时间', '').strip():
                opening += 1
        
        print(f"✅ CSV格式完全正常！")
        print(f"✓ 总记录数: {count}")
        print(f"✓ 已平仓交易: {closed}")
        print(f"✓ 持仓中交易: {opening}")
        
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
echo "✅ 批量清理完成！"
echo "=========================================="
echo ""
echo "📝 下一步："
echo "  cd /root/pythonc程序/my_project"
echo "  pkill -f 'python.*每日壁纸更换.py'"
echo "  nohup python3 每日壁纸更换.py > nohup.out 2>&1 &"
echo "  sleep 3"
echo "  cd /root/10-23-bot/ds && ./test_api.sh"
echo ""

