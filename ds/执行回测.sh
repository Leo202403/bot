#!/bin/bash
# V8.3.21 执行回测（两个模型）

cd /root/10-23-bot/ds

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "开始回测（Qwen + DeepSeek）"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 设置回测模式
export MANUAL_BACKTEST=true

# 回测 Qwen
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "回测模型1: Qwen"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

timeout 600 python3 qwen_多币种智能版.py 2>&1 | tee /tmp/qwen_backtest.log

QWEN_EXIT=${PIPESTATUS[0]}

echo ""
if [ $QWEN_EXIT -eq 0 ]; then
    echo "✅ Qwen回测完成"
else
    echo "❌ Qwen回测异常（退出码: $QWEN_EXIT）"
    if [ $QWEN_EXIT -eq 124 ]; then
        echo "   超时（10分钟）"
    fi
    echo ""
    echo "📄 最后100行日志："
    tail -100 /tmp/qwen_backtest.log
fi

# 等待1秒
sleep 1

# 回测 DeepSeek
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "回测模型2: DeepSeek"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

timeout 600 python3 deepseek_多币种智能版.py 2>&1 | tee /tmp/deepseek_backtest.log

DEEPSEEK_EXIT=${PIPESTATUS[0]}

echo ""
if [ $DEEPSEEK_EXIT -eq 0 ]; then
    echo "✅ DeepSeek回测完成"
else
    echo "❌ DeepSeek回测异常（退出码: $DEEPSEEK_EXIT）"
    if [ $DEEPSEEK_EXIT -eq 124 ]; then
        echo "   超时（10分钟）"
    fi
    echo ""
    echo "📄 最后100行日志："
    tail -100 /tmp/deepseek_backtest.log
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "回测完成！检查服务状态..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

supervisorctl status

echo ""
echo "📊 回测结果："
echo "  Qwen: $([ $QWEN_EXIT -eq 0 ] && echo '✓ 成功' || echo "✗ 异常(退出码$QWEN_EXIT)")"
echo "  DeepSeek: $([ $DEEPSEEK_EXIT -eq 0 ] && echo '✓ 成功' || echo "✗ 异常(退出码$DEEPSEEK_EXIT)")"
echo ""
echo "📧 请检查邮箱查看回测报告"
echo "📱 请检查手机查看Bark通知"
echo ""
echo "💡 查看新参数："
echo "   cat /root/10-23-bot/ds/trading_data/qwen/config.json | grep -A 15 scalping_params"
echo "   cat /root/10-23-bot/ds/trading_data/deepseek/config.json | grep -A 15 scalping_params"
echo ""

