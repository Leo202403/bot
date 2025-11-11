#!/bin/bash
# V8.3.21 服务器回测（不停止AI服务）

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "V8.3.21 服务器检查和回测（AI服务保持运行）"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ==========================================
# 第1步：检查进程状态
# ==========================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第1步：检查进程状态"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "📊 Supervisor管理的服务："
supervisorctl status

echo ""
echo "🔍 Python进程："
ps aux | grep python | grep -E "qwen|deepseek" | grep -v grep

echo ""
echo "💡 前端进程："
ps aux | grep -E "前端|frontend|3000" | grep -v grep

# ==========================================
# 第2步：更新代码
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第2步：更新代码"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

cd /root/10-23-bot

echo "📍 当前版本："
git log --oneline -1

echo ""
echo "🔄 拉取最新修复..."
git pull origin main

echo ""
echo "📍 更新后版本："
git log --oneline -1

# ==========================================
# 第3步：验证修复
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第3步：验证修复已应用"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

cd /root/10-23-bot/ds

echo "✅ Qwen修复验证："
if grep -q "V8.3.21修复.*清理NaN" qwen_多币种智能版.py; then
    echo "   ✓ Qwen已包含NaN修复"
else
    echo "   ❌ Qwen缺少NaN修复"
fi

echo ""
echo "✅ DeepSeek修复验证："
if grep -q "V8.3.21修复.*清理NaN" deepseek_多币种智能版.py; then
    echo "   ✓ DeepSeek已包含NaN修复"
else
    echo "   ❌ DeepSeek缺少NaN修复"
fi

# ==========================================
# 第4步：运行回测（Qwen）
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第4步：回测 Qwen（AI服务保持运行）"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

cd /root/10-23-bot/ds

echo "⏱️  开始时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# 使用环境变量触发回测模式
MANUAL_BACKTEST=true python3 qwen_多币种智能版.py

QWEN_EXIT=$?

echo ""
if [ $QWEN_EXIT -eq 0 ]; then
    echo "✅ Qwen回测完成（退出码: 0）"
else
    echo "⚠️  Qwen回测退出（退出码: $QWEN_EXIT）"
fi

# ==========================================
# 第5步：运行回测（DeepSeek）
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第5步：回测 DeepSeek（AI服务保持运行）"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "⏱️  开始时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# 使用环境变量触发回测模式
MANUAL_BACKTEST=true python3 deepseek_多币种智能版.py

DEEPSEEK_EXIT=$?

echo ""
if [ $DEEPSEEK_EXIT -eq 0 ]; then
    echo "✅ DeepSeek回测完成（退出码: 0）"
else
    echo "⚠️  DeepSeek回测退出（退出码: $DEEPSEEK_EXIT）"
fi

# ==========================================
# 第6步：检查AI进程（确认还在运行）
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第6步：确认AI进程仍在运行"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "📊 Supervisor状态："
supervisorctl status

echo ""
echo "🔍 Python进程："
ps aux | grep python | grep -E "qwen|deepseek" | grep -v grep

# ==========================================
# 第7步：查看回测结果
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第7步：查看回测结果"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "📊 Qwen新参数："
if [ -f "/root/10-23-bot/ds/trading_data/qwen/config.json" ]; then
    echo "超短线参数："
    cat /root/10-23-bot/ds/trading_data/qwen/config.json | grep -A 5 '"scalping_params"'
    echo ""
    echo "波段参数："
    cat /root/10-23-bot/ds/trading_data/qwen/config.json | grep -A 5 '"swing_params"'
else
    echo "⚠️  配置文件不存在"
fi

echo ""
echo "📊 DeepSeek新参数："
if [ -f "/root/10-23-bot/ds/trading_data/deepseek/config.json" ]; then
    echo "超短线参数："
    cat /root/10-23-bot/ds/trading_data/deepseek/config.json | grep -A 5 '"scalping_params"'
    echo ""
    echo "波段参数："
    cat /root/10-23-bot/ds/trading_data/deepseek/config.json | grep -A 5 '"swing_params"'
else
    echo "⚠️  配置文件不存在"
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

echo "📊 回测结果总结："
if [ $QWEN_EXIT -eq 0 ]; then
    echo "  ✓ Qwen: 成功"
else
    echo "  ✗ Qwen: 退出码 $QWEN_EXIT"
fi

if [ $DEEPSEEK_EXIT -eq 0 ]; then
    echo "  ✓ DeepSeek: 成功"
else
    echo "  ✗ DeepSeek: 退出码 $DEEPSEEK_EXIT"
fi

echo ""
echo "📧 请检查邮箱查看详细回测报告"
echo "📱 请检查手机查看Bark通知"
echo ""

# 如果有错误，显示最近的日志
if [ $QWEN_EXIT -ne 0 ] || [ $DEEPSEEK_EXIT -ne 0 ]; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "⚠️  检测到错误，查看最近日志"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    
    if [ $QWEN_EXIT -ne 0 ]; then
        echo "Qwen最近错误（如果有日志文件）："
        if [ -f "/root/10-23-bot/ds/logs/qwen_error.log" ]; then
            tail -20 /root/10-23-bot/ds/logs/qwen_error.log
        fi
    fi
    
    if [ $DEEPSEEK_EXIT -ne 0 ]; then
        echo ""
        echo "DeepSeek最近错误（如果有日志文件）："
        if [ -f "/root/10-23-bot/ds/logs/deepseek_error.log" ]; then
            tail -20 /root/10-23-bot/ds/logs/deepseek_error.log
        fi
    fi
fi

echo ""

