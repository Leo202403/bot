#!/bin/bash

echo "🚀 【V8.3.25.4】一键部署和验证脚本"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 部署到服务器
echo "📦 Step 1: 部署到服务器..."
ssh root@47.76.148.150 << 'ENDSSH'
cd /root/10-23-bot
git pull
supervisorctl restart ai-bot:*
echo "✅ 服务已重启"
ENDSSH

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 部署完成！"
echo ""
echo "🔍 接下来可以验证修复："
echo ""
echo "1️⃣ 运行完整回测（测试AI分析）："
echo "   ssh root@47.76.148.150"
echo "   bash ~/快速重启_修复版.sh backtest"
echo ""
echo "2️⃣ 预期结果："
echo "   ✅ Qwen显示：[AI Entry/Exit Analysis] 使用Qwen API进行深度分析..."
echo "   ✅ DeepSeek显示：[AI Entry/Exit Analysis] 使用DeepSeek API进行深度分析..."
echo "   ✅ 不再出现API密钥错误"
echo "   ✅ 不再出现KeyError: 'entry_details'"
echo "   ✅ 不再出现类型错误"
echo ""
echo "3️⃣ 检查邮件报告："
echo "   📧 应该收到2封邮件（DeepSeek + Qwen）"
echo "   📊 邮件包含："
echo "      - 昨日每笔交易详细分析（系统规则判断）"
echo "      - AI学习洞察（AI深度分析，英文）"
echo "      - 开仓时机分析"
echo "      - 平仓时机分析"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📝 关于邮件分析的说明："
echo ""
echo "Q: 邮件里的\"改进建议\"是谁的判断？"
echo "A: 表格里的建议（如\"TP扩大1.2倍\"）是【系统规则】自动生成"
echo "   - ⚠️ 早平：系统比较实际平仓价和后续最高/最低价"
echo "   - TP扩大1.2倍：系统基于错过的利润百分比计算"
echo ""
echo "Q: 平仓分析是AI做的吗？"
echo "A: 【两层分析】"
echo "   1. 规则分析：系统基于历史数据判断（显示在表格里）"
echo "   2. AI深度分析：AI分析规则结果并生成洞察（显示在另一部分）"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

