#!/bin/bash
# 提取qwen和deepseek的配置差异

echo "📊 分析qwen vs deepseek配置差异..."
echo ""

echo "=== 1. 模型调用相关 ==="
echo "【qwen】:"
grep -n "qwen\|Qwen\|通义" qwen_多币种智能版.py | grep -i "client\|model\|api" | head -10
echo ""
echo "【deepseek】:"
grep -n "deepseek\|DeepSeek" deepseek_多币种智能版.py | grep -i "client\|model\|api" | head -10
echo ""

echo "=== 2. 配置文件路径 ==="
echo "【qwen】:"
grep -n "trading_data/\|learning_config\|market_snapshots" qwen_多币种智能版.py | grep "qwen\|deepseek" | head -10
echo ""

echo "=== 3. 邮件标识 ==="
echo "【qwen】:"
grep -n "邮件\|Email\|subject" qwen_多币种智能版.py | grep -i "qwen\|通义\|deepseek" | head -10
echo ""

echo "=== 4. Bark推送标识 ==="
echo "【qwen】:"
grep -n "Bark.*qwen\|Bark.*通义\|Bark.*deepseek" qwen_多币种智能版.py | head -10
echo ""

echo "=== 5. 日志文件路径 ==="
echo "【qwen】:"
grep -n "\.log\|logging" qwen_多币种智能版.py | grep "qwen\|deepseek" | head -10
echo ""

echo "=== 6. 变量名/函数名差异 ==="
echo "【qwen中的deepseek_client】:"
grep -n "deepseek_client\|qwen_client" qwen_多币种智能版.py | head -10
echo ""

echo "✅ 分析完成"
