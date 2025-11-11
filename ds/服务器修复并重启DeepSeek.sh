#!/bin/bash
# V8.3.21 修复DeepSeek并重启

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "V8.3.21 修复DeepSeek并重启"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ==========================================
# 第1步：检查当前状态
# ==========================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第1步：检查当前状态"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "📊 Supervisor状态："
supervisorctl status

echo ""
echo "🔍 Python进程："
ps aux | grep python | grep -E "qwen|deepseek" | grep -v grep | head -10

# ==========================================
# 第2步：拉取最新代码
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第2步：拉取最新代码"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

cd /root/10-23-bot

echo "📍 当前版本："
git log --oneline -1

echo ""
echo "🔄 拉取修复..."
git pull origin main

echo ""
echo "📍 更新后版本："
git log --oneline -1

# ==========================================
# 第3步：验证修复
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第3步：验证修复"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

cd /root/10-23-bot/ds

echo "✅ 检查DeepSeek客户端初始化："
grep -A 3 "初始化DeepSeek客户端" deepseek_多币种智能版.py | head -4

echo ""
echo "✅ 检查是否还有Qwen引用："
QWEN_COUNT=$(grep -i "qwen\|通义千问" deepseek_多币种智能版.py | wc -l)
if [ "$QWEN_COUNT" -eq "0" ]; then
    echo "   ✓ 已清理所有Qwen引用"
else
    echo "   ⚠️  还有 $QWEN_COUNT 处Qwen引用"
    grep -in "qwen\|通义千问" deepseek_多币种智能版.py | head -10
fi

echo ""
echo "✅ 检查NaN修复："
if grep -q "V8.3.21修复.*清理NaN" deepseek_多币种智能版.py; then
    echo "   ✓ DeepSeek已包含NaN修复"
else
    echo "   ❌ DeepSeek缺少NaN修复"
fi

# ==========================================
# 第4步：重启DeepSeek
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第4步：重启DeepSeek"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "🔄 停止DeepSeek..."
supervisorctl stop deepseek
sleep 2

echo ""
echo "🚀 启动DeepSeek..."
supervisorctl start deepseek
sleep 3

echo ""
echo "📊 DeepSeek状态："
supervisorctl status deepseek

# ==========================================
# 第5步：检查启动日志
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第5步：检查启动日志（最近20行）"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ -f "/var/log/supervisor/deepseek-stderr.log" ]; then
    echo "📋 错误日志："
    tail -20 /var/log/supervisor/deepseek-stderr.log
else
    echo "⚠️  未找到错误日志文件"
fi

echo ""
if [ -f "/var/log/supervisor/deepseek-stdout.log" ]; then
    echo "📋 输出日志："
    tail -20 /var/log/supervisor/deepseek-stdout.log
else
    echo "⚠️  未找到输出日志文件"
fi

# ==========================================
# 第6步：运行回测（可选）
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第6步：是否运行回测？"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

read -p "是否立即运行回测？(y/n): " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "运行回测：Qwen + DeepSeek"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    
    bash 服务器回测_不停AI.sh
else
    echo "⏩ 跳过回测"
fi

# ==========================================
# 总结
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 完成！"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "⏱️  完成时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

echo "📊 最终状态："
supervisorctl status qwen deepseek

echo ""
echo "💡 如需手动回测："
echo "   cd /root/10-23-bot/ds && bash 服务器回测_不停AI.sh"
echo ""
echo "💡 如需查看DeepSeek日志："
echo "   tail -f /var/log/supervisor/deepseek-stdout.log"
echo ""

