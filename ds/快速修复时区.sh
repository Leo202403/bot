#!/bin/bash
# V8.3.21 时区快速修复脚本

echo "========================================"
echo "V8.3.21 时区修复"
echo "========================================"
echo ""

# 进入正确目录
cd "$(dirname "$0")"

# 先检查
echo "🔍 步骤1: 检查数据（不会修改文件）"
echo "----------------------------------------"
python3 fix_timezone_data.py --dry-run
echo ""

# 询问是否继续
echo ""
read -p "❓ 是否继续修复？(yes/no): " answer

if [ "$answer" != "yes" ]; then
    echo "❌ 已取消"
    exit 0
fi

# 修复
echo ""
echo "🔧 步骤2: 修复数据"
echo "----------------------------------------"
python3 fix_timezone_data.py

# 验证
echo ""
echo "✅ 步骤3: 验证修复结果"
echo "----------------------------------------"
python3 fix_timezone_data.py --dry-run

echo ""
echo "========================================"
echo "✅ 修复完成！"
echo "========================================"
echo ""
echo "💡 备份文件位置："
echo "   trading_data/*/*.bak_before_timezone_fix"
echo ""
echo "💡 如需回滚，运行："
echo "   cp trading_data/qwen/*.bak_before_timezone_fix trading_data/qwen/"
echo ""

