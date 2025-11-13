#!/bin/bash
# 【V8.3.25.10】参数应用逻辑修复 - 服务器部署脚本

echo "=========================================="
echo "部署V8.3.25.10参数应用逻辑修复"
echo "=========================================="
echo ""
echo "📋 修复内容："
echo "  1. V8.3.21优化结果正确保存到learning_config"
echo "  2. AI洞察参数被提取并加入V8.3.21测试候选集"
echo "  3. 邮件显示的参数 = 实际应用的参数"
echo ""
echo "🔧 修改文件："
echo "  - qwen_多币种智能版.py"
echo "  - deepseek_多币种智能版.py"
echo "  - backtest_optimizer_v8321.py"
echo ""
echo "=========================================="
echo ""

# 进入项目目录
cd /root/10-23-bot

# 拉取最新代码
echo "📥 拉取最新代码..."
git pull

if [ $? -ne 0 ]; then
    echo "❌ 代码拉取失败"
    exit 1
fi

echo "✅ 代码拉取成功"
echo ""

# 重启AI进程
echo "🔄 重启AI进程..."
bash ~/快速重启_修复版.sh bots

echo ""
echo "=========================================="
echo "✅ 部署完成！"
echo "=========================================="
echo ""
echo "📊 验证步骤："
echo ""
echo "1. 检查AI进程状态："
echo "   supervisorctl status deepseek qwen"
echo ""
echo "2. 查看实时日志（验证修复）："
echo "   tail -f ds/trading_data/qwen/ai_trading.log"
echo ""
echo "3. 验证关键日志（应该出现）："
echo "   grep '第4.55步：提取AI洞察的参数建议' ds/trading_data/qwen/ai_trading.log"
echo "   grep 'AI建议参数已加入' ds/trading_data/qwen/ai_trading.log"
echo ""
echo "4. 手动触发回测（测试修复）："
echo "   bash ~/快速重启_修复版.sh backtest"
echo ""
echo "5. 检查learning_config.json（验证参数保存）："
echo "   cat ds/trading_data/qwen/learning_config.json | grep -A 10 'scalping_params'"
echo ""
echo "=========================================="

