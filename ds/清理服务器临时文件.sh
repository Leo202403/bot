#!/bin/bash

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "清理服务器临时文件和文档"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

cd /root/10-23-bot/ds

# 保留的核心文件列表
echo "📋 将保留核心文件：deepseek/qwen主程序、优化器、数据导出等"
echo ""

echo "🗑️  将删除以下类型的文件："
echo "  • V8.3.21_*.md（文档）"
echo "  • 立即*.txt（临时说明）"
echo "  • 服务器*.sh（临时脚本）"
echo "  • 检查*.sh（临时脚本）"
echo "  • 修复*.sh（临时脚本）"
echo "  • 其他临时文件"
echo ""

# 不需要确认，直接删除（服务器上）
echo "🗑️  开始删除..."
echo ""

# 删除文档文件
find . -maxdepth 1 -name "V8.3.*.md" -type f -delete 2>/dev/null && echo "  ✓ 删除文档文件"

# 删除临时说明文件
find . -maxdepth 1 -name "立即*.txt" -type f -delete 2>/dev/null && echo "  ✓ 删除立即*说明"
find . -maxdepth 1 -name "前端*.txt" -type f -delete 2>/dev/null && echo "  ✓ 删除前端*说明"
find . -maxdepth 1 -name "时区*.txt" -type f -delete 2>/dev/null && echo "  ✓ 删除时区*说明"
find . -maxdepth 1 -name "清理*.txt" -type f -delete 2>/dev/null && echo "  ✓ 删除清理*说明"
find . -maxdepth 1 -name "快速*.txt" -type f -delete 2>/dev/null && echo "  ✓ 删除快速*说明"
find . -maxdepth 1 -name "测试*.txt" -type f -delete 2>/dev/null && echo "  ✓ 删除测试*说明"
find . -maxdepth 1 -name "重启*.txt" -type f -delete 2>/dev/null && echo "  ✓ 删除重启*说明"

# 删除临时脚本（保留 手动回测.sh 和 安装所有依赖.sh）
find . -maxdepth 1 -name "服务器*.sh" -type f -delete 2>/dev/null && echo "  ✓ 删除服务器*脚本"
find . -maxdepth 1 -name "检查*.sh" -type f -delete 2>/dev/null && echo "  ✓ 删除检查*脚本"
find . -maxdepth 1 -name "修复*.sh" -type f -delete 2>/dev/null && echo "  ✓ 删除修复*脚本"
find . -maxdepth 1 -name "更新*.sh" -type f -delete 2>/dev/null && echo "  ✓ 删除更新*脚本"
find . -maxdepth 1 -name "查看*.sh" -type f -delete 2>/dev/null && echo "  ✓ 删除查看*脚本"
find . -maxdepth 1 -name "完全同步*.sh" -type f -delete 2>/dev/null && echo "  ✓ 删除同步*脚本"
find . -maxdepth 1 -name "执行*.sh" -type f -delete 2>/dev/null && echo "  ✓ 删除执行*脚本"

# 删除其他临时文件
find . -maxdepth 1 -name "*.expect" -type f -delete 2>/dev/null && echo "  ✓ 删除expect脚本"
find . -maxdepth 1 -name "*.patch" -type f -delete 2>/dev/null && echo "  ✓ 删除patch文件"
find . -maxdepth 1 -name "check_*.sh" -type f -delete 2>/dev/null && echo "  ✓ 删除check_*脚本"
find . -maxdepth 1 -name "manual_backtest.sh" -type f -delete 2>/dev/null && echo "  ✓ 删除旧版回测脚本"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 清理完成！"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📋 当前保留的核心文件："
ls -lh | grep -v "^d" | grep -v "^total" | awk '{print "  " $9}'
echo ""

