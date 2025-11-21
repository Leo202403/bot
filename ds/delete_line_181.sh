#!/bin/bash
# 删除第181行问题数据

echo "=========================================="
echo "🔧 删除第181行问题数据"
echo "=========================================="
echo ""

DS_FILE="/root/10-23-bot/ds/trading_data/deepseek/trades_history.csv"

# 1. 备份
BACKUP_FILE="${DS_FILE}.before_delete_181_$(date +%Y%m%d_%H%M%S)"
echo "【步骤1】备份原文件..."
cp "$DS_FILE" "$BACKUP_FILE"
echo "✓ 已备份到: $BACKUP_FILE"
echo ""

# 2. 显示第181行
echo "【步骤2】显示要删除的第181行..."
sed -n '181p' "$DS_FILE"
echo ""

# 3. 删除第181行
echo "【步骤3】删除第181行..."
sed -i '181d' "$DS_FILE"
echo "✓ 已删除第181行"
echo ""

# 4. 验证
echo "【步骤4】验证修复..."
python3 << 'PYEOF'
import csv

try:
    with open('/root/10-23-bot/ds/trading_data/deepseek/trades_history.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        
        if None in reader.fieldnames:
            print(f"❌ 表头仍有None字段")
            exit(1)
        
        count = 0
        for i, row in enumerate(reader, start=2):
            if None in row:
                print(f"❌ 第 {i} 行仍有None字段")
                exit(1)
            count += 1
        
        closed = sum(1 for row in csv.DictReader(open('/root/10-23-bot/ds/trading_data/deepseek/trades_history.csv', 'r', encoding='utf-8')) if row.get('平仓时间', '').strip())
        
        print(f"✅ CSV格式验证通过！")
        print(f"✓ 总记录数: {count}")
        print(f"✓ 已平仓交易: {closed}")
        
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
echo "✅ 修复完成！CSV文件已正常"
echo "=========================================="
echo ""
echo "📝 下一步："
echo "  cd /root/pythonc程序/my_project"
echo "  pkill -f 'python.*每日壁纸更换.py'"
echo "  nohup python3 每日壁纸更换.py > nohup.out 2>&1 &"
echo "  sleep 3"
echo "  cd /root/10-23-bot/ds && ./test_api.sh"
echo ""

