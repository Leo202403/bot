#!/bin/bash

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "清理临时文件和文档"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 保留的核心文件列表
KEEP_FILES=(
    "deepseek_多币种智能版.py"
    "qwen_多币种智能版.py"
    "backtest_optimizer_v8321.py"
    "export_historical_data.py"
    "fix_timezone_data.py"
    "requirements.txt"
    "ai_trading_web.py"
    "手动回测.sh"
    "安装所有依赖.sh"
    "trading_data"
    ".env"
    ".env.qwen"
    "__pycache__"
)

echo "📋 将保留以下核心文件："
for file in "${KEEP_FILES[@]}"; do
    echo "  ✓ $file"
done
echo ""

# 待删除的文件类型
echo "🗑️  将删除以下类型的文件："
echo "  • V8.3.21_*.md（文档）"
echo "  • 立即*.txt（临时说明）"
echo "  • 服务器*.sh（临时脚本）"
echo "  • 检查*.sh（临时脚本）"
echo "  • 修复*.sh（临时脚本）"
echo "  • 更新*.sh（临时脚本）"
echo "  • 清理*.txt（临时说明）"
echo "  • 前端*.txt（临时说明）"
echo "  • 时区*.txt（临时说明）"
echo "  • 其他临时文件"
echo ""

read -p "确认删除？[y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]
then
    echo "❌ 取消删除"
    exit 1
fi

echo ""
echo "🗑️  开始删除..."
echo ""

# 删除文档文件
rm -f V8.3.*.md 2>/dev/null && echo "  ✓ 删除文档文件"

# 删除临时说明文件
rm -f 立即*.txt 2>/dev/null && echo "  ✓ 删除立即*说明"
rm -f 前端*.txt 2>/dev/null && echo "  ✓ 删除前端*说明"
rm -f 时区*.txt 2>/dev/null && echo "  ✓ 删除时区*说明"
rm -f 清理*.txt 2>/dev/null && echo "  ✓ 删除清理*说明"
rm -f 快速*.txt 2>/dev/null && echo "  ✓ 删除快速*说明"
rm -f 测试*.txt 2>/dev/null && echo "  ✓ 删除测试*说明"
rm -f 重启*.txt 2>/dev/null && echo "  ✓ 删除重启*说明"

# 删除临时脚本
rm -f 服务器*.sh 2>/dev/null && echo "  ✓ 删除服务器*脚本"
rm -f 检查*.sh 2>/dev/null && echo "  ✓ 删除检查*脚本"
rm -f 修复*.sh 2>/dev/null && echo "  ✓ 删除修复*脚本"
rm -f 更新*.sh 2>/dev/null && echo "  ✓ 删除更新*脚本"
rm -f 查看*.sh 2>/dev/null && echo "  ✓ 删除查看*脚本"
rm -f 完全同步*.sh 2>/dev/null && echo "  ✓ 删除同步*脚本"

# 删除其他临时文件
rm -f *.expect 2>/dev/null && echo "  ✓ 删除expect脚本"
rm -f *.patch 2>/dev/null && echo "  ✓ 删除patch文件"
rm -f check_*.sh 2>/dev/null && echo "  ✓ 删除check_*脚本"
rm -f manual_backtest.sh 2>/dev/null && echo "  ✓ 删除旧版回测脚本"
rm -f 执行*.sh 2>/dev/null && echo "  ✓ 删除执行*脚本"

# 删除测试文件（可选）
# rm -f test_*.py 2>/dev/null && echo "  ✓ 删除测试文件"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 清理完成！"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📋 当前保留的文件："
ls -lh | grep -v "^d" | grep -v "^total" | awk '{print "  " $9}'
echo ""

