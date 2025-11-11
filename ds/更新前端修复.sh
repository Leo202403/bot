#!/bin/bash
# V8.3.21 更新前端修复 - 综合页面显示Qwen决策

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "V8.3.21 更新前端修复"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ==========================================
# 第1步：拉取最新代码
# ==========================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第1步：拉取最新代码"
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
# 第2步：复制修复后的前端文件
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第2步：复制修复后的前端文件"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

SOURCE_FILE="/root/10-23-bot/每日壁纸更换.py"
TARGET_FILE="/root/pythonc程序/my_project/每日壁纸更换.py"

if [ -f "$SOURCE_FILE" ]; then
    # 备份旧文件
    if [ -f "$TARGET_FILE" ]; then
        cp "$TARGET_FILE" "${TARGET_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
        echo "✅ 已备份旧文件"
    fi
    
    # 复制新文件
    cp "$SOURCE_FILE" "$TARGET_FILE"
    echo "✅ 已复制修复后的前端文件"
    
    # 验证修复
    if grep -q "V8.3.21修复.*ai_decisions" "$TARGET_FILE"; then
        echo "✅ 修复验证成功（包含V8.3.21修复标记）"
    else
        echo "⚠️  警告：未发现V8.3.21修复标记"
    fi
else
    echo "❌ 源文件不存在: $SOURCE_FILE"
    exit 1
fi

# ==========================================
# 第3步：重启web服务
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第3步：重启web服务"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "🔄 停止web服务..."
supervisorctl stop web
sleep 2

echo ""
echo "🚀 启动web服务..."
supervisorctl start web
sleep 3

echo ""
echo "📊 web服务状态："
supervisorctl status web

# ==========================================
# 第4步：验证服务
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第4步：验证服务"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 等待服务启动
sleep 5

echo "🔍 检查进程："
ps aux | grep gunicorn | grep -v grep | head -2

echo ""
echo "🌐 检查端口监听："
netstat -tlnp 2>/dev/null | grep LISTEN || ss -tlnp 2>/dev/null | grep LISTEN

echo ""
echo "📋 查看最新日志："
tail -20 /root/pythonc程序/my_project/logs/web.log 2>/dev/null || tail -20 /root/pythonc程序/my_project/logs/web_err.log 2>/dev/null || echo "日志文件未找到"

# ==========================================
# 总结
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 更新完成！"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "⏱️  完成时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

echo "🔧 修复内容："
echo "  • 在get_model_summary函数中添加ai_decisions读取"
echo "  • trading-combined API现在会返回两个模型的AI决策历史"
echo "  • 综合页面可以正常显示Qwen的实时决策"
echo ""

echo "💡 测试步骤："
echo "  1. 打开浏览器，访问综合页面"
echo "  2. 强制刷新（Ctrl+F5 或 Cmd+Shift+R）"
echo "  3. 查看AI决策部分，应该能看到Qwen和DeepSeek的决策"
echo "  4. 如果还是不显示，打开F12开发者工具查看Console错误"
echo ""

