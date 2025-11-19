#!/bin/bash
# V8.5.2.4.74 - 服务器修复并回测脚本
# 用途：拉取最新代码（包含V8.5.2.4.62修复）+ 运行回测

set -e  # 遇到错误立即退出

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔧 V8.5.2.4.74: 修复TP/SL None问题"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 1. 停止AI进程
echo "📌 Step 1: 停止AI进程..."
supervisorctl stop deepseek qwen
echo "✅ AI进程已停止"
echo ""

# 2. 拉取最新代码
echo "📌 Step 2: 拉取最新代码..."
cd ~/10-23-bot
git pull origin main
echo "✅ 代码已更新"
echo ""

# 3. 验证修复
echo "📌 Step 3: 验证V8.5.2.4.62修复..."
if grep -q "V8.5.2.4.62.*使用 or 操作符" ds/deepseek_多币种智能版.py; then
    echo "✅ V8.5.2.4.62修复已应用"
    grep -A4 "V8.5.2.4.62.*使用 or 操作符" ds/deepseek_多币种智能版.py | head -5
else
    echo "❌ 警告：V8.5.2.4.62修复未找到，回测可能仍然失败"
fi
echo ""

# 4. 运行回测
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 Step 4: 开始回测..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
cd ~/10-23-bot/ds
MANUAL_BACKTEST=true python3 deepseek_多币种智能版.py backtest-deepseek

# 5. 回测完成后重启
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 回测完成！"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📌 Step 5: 重启AI进程..."
supervisorctl start deepseek qwen
echo "✅ AI进程已重启"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎉 全部完成！"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

