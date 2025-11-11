#!/bin/bash
# V8.3.21 检查前端状态和AI决策显示问题

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "V8.3.21 前端状态检查"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ==========================================
# 第1步：前端进程状态
# ==========================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第1步：前端进程状态"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "📊 Supervisor状态："
supervisorctl status | grep -i frontend || echo "⚠️  Supervisor中未找到frontend服务"

echo ""
echo "🔍 前端进程："
FRONTEND_PROCS=$(ps aux | grep -E 'node.*3000|前端|frontend' | grep -v grep)
if [ ! -z "$FRONTEND_PROCS" ]; then
    echo "$FRONTEND_PROCS"
else
    echo "⚠️  未找到前端进程"
fi

echo ""
echo "🌐 端口监听："
netstat -tlnp 2>/dev/null | grep 3000 || ss -tlnp 2>/dev/null | grep 3000 || echo "⚠️  端口3000未监听"

# ==========================================
# 第2步：AI决策文件检查
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第2步：AI决策文件检查"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

QWEN_DECISION="/root/10-23-bot/ds/trading_data/qwen/ai_decisions.json"
DEEPSEEK_DECISION="/root/10-23-bot/ds/trading_data/deepseek/ai_decisions.json"

echo "📄 Qwen AI决策文件："
if [ -f "$QWEN_DECISION" ]; then
    ls -lh "$QWEN_DECISION"
    echo "   文件大小: $(du -h "$QWEN_DECISION" | cut -f1)"
    echo "   最后修改: $(stat -c '%y' "$QWEN_DECISION" 2>/dev/null || stat -f '%Sm' "$QWEN_DECISION")"
    echo "   记录数量: $(cat "$QWEN_DECISION" | grep -o '"timestamp"' | wc -l) 条"
else
    echo "   ❌ 文件不存在"
fi

echo ""
echo "📄 DeepSeek AI决策文件："
if [ -f "$DEEPSEEK_DECISION" ]; then
    ls -lh "$DEEPSEEK_DECISION"
    echo "   文件大小: $(du -h "$DEEPSEEK_DECISION" | cut -f1)"
    echo "   最后修改: $(stat -c '%y' "$DEEPSEEK_DECISION" 2>/dev/null || stat -f '%Sm' "$DEEPSEEK_DECISION")"
    echo "   记录数量: $(cat "$DEEPSEEK_DECISION" | grep -o '"timestamp"' | wc -l) 条"
else
    echo "   ❌ 文件不存在"
fi

# ==========================================
# 第3步：检查最新AI决策内容
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第3步：检查最新AI决策内容"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "🔍 Qwen最新决策："
if [ -f "$QWEN_DECISION" ]; then
    cat "$QWEN_DECISION" | jq -r '.[-1] | "时间: \(.timestamp) | 动作: \(.action) | 币种: \(.symbol)"' 2>/dev/null || tail -3 "$QWEN_DECISION"
else
    echo "   ❌ 文件不存在"
fi

echo ""
echo "🔍 DeepSeek最新决策："
if [ -f "$DEEPSEEK_DECISION" ]; then
    cat "$DEEPSEEK_DECISION" | jq -r '.[-1] | "时间: \(.timestamp) | 动作: \(.action) | 币种: \(.symbol)"' 2>/dev/null || tail -3 "$DEEPSEEK_DECISION"
else
    echo "   ❌ 文件不存在"
fi

# ==========================================
# 第4步：前端日志检查
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第4步：前端日志检查（最后30行）"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

FRONTEND_LOG="/var/log/supervisor/frontend-stdout.log"
FRONTEND_ERR="/var/log/supervisor/frontend-stderr.log"

if [ -f "$FRONTEND_LOG" ]; then
    echo "📋 标准输出日志（最后30行）："
    tail -30 "$FRONTEND_LOG"
elif [ -f "$FRONTEND_ERR" ]; then
    echo "📋 错误日志（最后30行）："
    tail -30 "$FRONTEND_ERR"
else
    echo "⚠️  前端日志文件未找到"
fi

# ==========================================
# 第5步：前端代码检查（API路由）
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第5步：前端API路由检查"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

FRONTEND_DIR="/root/10-23-bot/frontend"
if [ ! -d "$FRONTEND_DIR" ]; then
    FRONTEND_DIR="/root/10-23-bot/前端"
fi

if [ -d "$FRONTEND_DIR" ]; then
    echo "📂 前端目录: $FRONTEND_DIR"
    echo ""
    
    # 查找综合页面相关文件
    echo "🔍 查找综合页面文件："
    find "$FRONTEND_DIR" -name "*综合*" -o -name "*overview*" -o -name "*dashboard*" 2>/dev/null | head -5
    
    echo ""
    echo "🔍 查找AI决策API路由："
    grep -r "ai_decisions" "$FRONTEND_DIR" --include="*.js" --include="*.jsx" --include="*.ts" --include="*.tsx" 2>/dev/null | head -10
else
    echo "❌ 前端目录未找到"
fi

# ==========================================
# 第6步：问题诊断
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第6步：问题诊断"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

ISSUES=0

# 检查1：Qwen决策文件是否存在且有数据
if [ ! -f "$QWEN_DECISION" ]; then
    echo "❌ 问题1：Qwen AI决策文件不存在"
    echo "   可能原因：Qwen AI未运行或未生成决策"
    echo "   解决方案：检查Qwen进程状态"
    ISSUES=$((ISSUES+1))
elif [ $(stat -c%s "$QWEN_DECISION" 2>/dev/null || stat -f%z "$QWEN_DECISION") -lt 100 ]; then
    echo "❌ 问题2：Qwen AI决策文件太小（可能为空）"
    echo "   可能原因：Qwen AI刚启动或长时间无决策"
    ISSUES=$((ISSUES+1))
fi

# 检查2：前端是否正常运行
if ! ps aux | grep -E 'node.*3000|前端' | grep -v grep > /dev/null; then
    echo "❌ 问题3：前端进程未运行"
    echo "   可能原因：前端服务崩溃或未启动"
    echo "   解决方案：supervisorctl restart frontend"
    ISSUES=$((ISSUES+1))
fi

# 检查3：端口是否监听
if ! (netstat -tlnp 2>/dev/null | grep 3000 > /dev/null || ss -tlnp 2>/dev/null | grep 3000 > /dev/null); then
    echo "❌ 问题4：端口3000未监听"
    echo "   可能原因：前端启动失败"
    ISSUES=$((ISSUES+1))
fi

if [ $ISSUES -eq 0 ]; then
    echo "✅ 未发现明显问题"
    echo ""
    echo "💡 如果综合页面不显示Qwen决策，可能是前端代码问题："
    echo "   1. 前端缓存问题（Ctrl+F5强制刷新）"
    echo "   2. API路由配置错误（检查前端代码）"
    echo "   3. 浏览器控制台可能有错误信息"
fi

# ==========================================
# 总结
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 检查完成"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "⏱️  完成时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

if [ $ISSUES -gt 0 ]; then
    echo "⚠️  发现 $ISSUES 个问题，请查看上方诊断结果"
else
    echo "💡 建议："
    echo "   1. 浏览器打开开发者工具（F12）"
    echo "   2. 切换到Console标签查看错误"
    echo "   3. 切换到Network标签查看API请求"
    echo "   4. 强制刷新页面（Ctrl+F5）"
fi
echo ""

