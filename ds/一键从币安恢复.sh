#!/bin/bash
# 一键从币安API恢复数据

echo "=========================================="
echo "🚀 从币安API恢复数据"
echo "=========================================="
echo ""

cd "$(dirname "$0")"

# 检查依赖
echo "检查依赖..."
if ! python3 -c "import ccxt" 2>/dev/null; then
    echo "⚠️  缺少ccxt库，正在安装..."
    pip3 install ccxt python-dotenv
fi

echo ""
echo "=========================================="
echo "📋 操作说明"
echo "=========================================="
echo ""
echo "此工具将："
echo "  1. 从币安统一账户获取实时数据"
echo "  2. 自动备份当前数据"
echo "  3. 恢复总资产、持仓和订单信息"
echo ""
echo "⚠️  请确认："
echo "  - 已配置币安API密钥(.env.deepseek)"
echo "  - 使用的是统一账户模式(Portfolio Margin)"
echo "  - 已停止交易系统(避免冲突)"
echo ""
read -p "确认继续? (y/n): " confirm

if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "❌ 已取消"
    exit 0
fi

# 停止交易系统
echo ""
echo "停止交易系统..."
pkill -f "每日壁纸更换.py" || echo "  (未运行)"
pkill -f "deepseek_多币种智能版.py" || true
pkill -f "qwen_多币种智能版.py" || true
sleep 2

# 运行恢复工具
echo ""
echo "=========================================="
echo "🔧 运行恢复工具"
echo "=========================================="
echo ""

python3 restore_from_binance_papi.py

# 询问是否重启
echo ""
read -p "是否重启交易系统? (y/n): " restart

if [ "$restart" = "y" ] || [ "$restart" = "Y" ]; then
    echo ""
    echo "重启交易系统..."
    cd ..
    nohup python3 每日壁纸更换.py > nohup.out 2>&1 &
    sleep 3
    
    echo ""
    echo "✅ 系统已重启"
    echo ""
    echo "检查日志: tail -f nohup.out"
    tail -20 nohup.out
else
    echo ""
    echo "💡 手动重启命令:"
    echo "   cd /root/10-23-bot"
    echo "   nohup python3 每日壁纸更换.py > nohup.out 2>&1 &"
fi

echo ""
echo "=========================================="
echo "✅ 完成"
echo "=========================================="

