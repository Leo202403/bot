#!/bin/bash
# 服务器恢复后一键执行脚本

echo "======================================================================"
echo "🚑 服务器恢复流程"
echo "======================================================================"

cd /home/admin/10-23-bot

echo ""
echo "【步骤1】拉取V8.3.16.8代码"
git fetch --all
git reset --hard origin/main
git log -1 --oneline

echo ""
echo "【步骤2】检查服务状态"
sudo supervisorctl status

echo ""
echo "【步骤3】停止所有服务"
sudo supervisorctl stop all

echo ""
echo "【步骤4】清理内存"
sync
sudo sysctl -w vm.drop_caches=3

echo ""
echo "【步骤5】恢复订单数据"
cd ds
source venv/bin/activate
python3 restore_orders_simple.py

echo ""
echo "【步骤6】验证数据格式"
echo ""
echo "DeepSeek数据:"
head -1 trading_data/deepseek/trades_history.csv
tail -n +2 trading_data/deepseek/trades_history.csv | head -1
echo ""
echo "Qwen数据:"
head -1 trading_data/qwen/trades_history.csv
tail -n +2 trading_data/qwen/trades_history.csv | head -1

echo ""
echo "【步骤7】重启服务"
sudo supervisorctl start all
sleep 5
sudo supervisorctl status

echo ""
echo "【步骤8】测试Web访问"
sleep 3
curl -s -o /dev/null -w "Web服务HTTP状态: %{http_code}\n" http://localhost:5001/

echo ""
echo "======================================================================"
echo "✅ 恢复完成！"
echo "======================================================================"
echo ""
echo "💡 下一步："
echo "  1. 浏览器访问前端，按 Ctrl+Shift+R 强制刷新"
echo "  2. 检查交易记录是否正常显示"
echo "  3. 如需回测，运行: bash 快速重启_修复版.sh backtest"
echo ""

