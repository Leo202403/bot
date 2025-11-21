#!/bin/bash
# 智能合并币安订单数据 - 快捷运行脚本

cd "$(dirname "$0")"

echo "=========================================="
echo "🔄 智能合并币安订单数据"
echo "=========================================="
echo ""
echo "功能："
echo "  ✓ 补充缺失的开仓时间"
echo "  ✓ 修正错误的时间信息"
echo "  ✓ 保留本地特有字段（开仓理由等）"
echo "  ✓ 自动备份原文件"
echo ""

python3 merge_binance_trades.py

echo ""
echo "提示："
echo "  - 修改完成后记得重启后端服务"
echo "  - 使用硬刷新 (Ctrl+Shift+R) 查看更新"
echo ""

