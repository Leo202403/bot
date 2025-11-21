#!/bin/bash
# 修复后端 leverage 字段类型转换错误

echo "=========================================="
echo "🔧 修复后端杠杆率类型转换错误"
echo "=========================================="
echo ""

BACKEND_FILE="/root/pythonc程序/my_project/每日壁纸更换.py"

if [ ! -f "$BACKEND_FILE" ]; then
    echo "❌ 文件不存在: $BACKEND_FILE"
    exit 1
fi

# 1. 备份原文件
BACKUP_FILE="${BACKEND_FILE}.backup_$(date +%Y%m%d_%H%M%S)"
echo "【步骤1】备份原文件..."
cp "$BACKEND_FILE" "$BACKUP_FILE"
echo "✓ 已备份到: $BACKUP_FILE"
echo ""

# 2. 修复 leverage 转换错误
echo "【步骤2】修复 leverage 类型转换..."
echo ""

# 使用 sed 替换所有 int(trade.get('杠杆率', 1) or 1) 为 int(float(trade.get('杠杆率', 1) or 1))
sed -i "s/int(trade\.get('杠杆率', 1) or 1)/int(float(trade.get('杠杆率', 1) or 1))/g" "$BACKEND_FILE"

echo "✓ 已修复 leverage 类型转换"
echo ""

# 3. 验证修改
echo "【步骤3】验证修改..."
echo ""

if grep -q "int(float(trade.get('杠杆率'" "$BACKEND_FILE"; then
    echo "✓ 修复成功！"
    echo ""
    echo "修改后的代码："
    grep -n "int(float(trade.get('杠杆率'" "$BACKEND_FILE" | head -5
else
    echo "❌ 修复失败，恢复备份..."
    cp "$BACKUP_FILE" "$BACKEND_FILE"
    exit 1
fi

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
echo "  cp $BACKUP_FILE $BACKEND_FILE"
echo ""

