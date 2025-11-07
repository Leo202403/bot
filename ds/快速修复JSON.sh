#!/bin/bash
echo "🔧 快速修复JSON文件"
echo "========================================================================"
echo ""

MODEL=${1:-deepseek}  # 默认修复deepseek，可以传参数 qwen

CONFIG_DIR="$HOME/10-23-bot/ds/trading_data/$MODEL"
CONFIG_FILE="$CONFIG_DIR/learning_config.json"
HISTORY_FILE="$CONFIG_DIR/iterative_optimization_history.jsonl"

echo "🎯 目标模型: $MODEL"
echo "📁 配置目录: $CONFIG_DIR"
echo ""

# 确保目录存在
mkdir -p "$CONFIG_DIR"

# 备份损坏的文件
echo "📦 备份现有文件..."
if [ -f "$CONFIG_FILE" ]; then
    mv "$CONFIG_FILE" "$CONFIG_FILE.broken.$(date +%Y%m%d_%H%M%S)"
    echo "  ✅ 已备份: $CONFIG_FILE"
fi

if [ -f "$HISTORY_FILE" ]; then
    mv "$HISTORY_FILE" "$HISTORY_FILE.broken.$(date +%Y%m%d_%H%M%S)"
    echo "  ✅ 已备份: $HISTORY_FILE"
fi

echo ""
echo "✨ 创建全新的 learning_config.json..."

# 创建干净的配置文件
cat > "$CONFIG_FILE" << 'EOFCONFIG'
{
  "version": "8.3.10.2",
  "last_updated": "2025-11-07",
  "global": {
    "min_risk_reward": 1.4,
    "min_indicator_consensus": 2,
    "atr_stop_multiplier": 1.35,
    "min_signal_score": 55
  },
  "scalping_params": {
    "min_signal_score": 50,
    "min_risk_reward": 1.3,
    "min_indicator_consensus": 2,
    "atr_stop_multiplier": 1.0,
    "atr_tp_multiplier": 1.5,
    "max_holding_hours": 2.0
  },
  "swing_params": {
    "min_signal_score": 60,
    "min_risk_reward": 2.0,
    "min_indicator_consensus": 3,
    "atr_stop_multiplier": 2.0,
    "atr_tp_multiplier": 6.0,
    "max_holding_hours": 24.0,
    "use_htf_levels": true
  },
  "compressed_insights": {
    "date": "20251107",
    "lessons": [
      "System initialized"
    ],
    "focus": "准备开始学习",
    "updated_at": "2025-11-07 18:00"
  },
  "scalping_insights": [],
  "swing_insights": [],
  "iterative_history": []
}
EOFCONFIG

echo "  ✅ 已创建: $CONFIG_FILE"

# 验证JSON格式
python3 -c "import json; json.load(open('$CONFIG_FILE'))" 2>&1
if [ $? -eq 0 ]; then
    echo "  ✅ JSON格式验证通过"
else
    echo "  ❌ JSON格式验证失败"
fi

echo ""
echo "✨ 创建空的历史记录文件..."
touch "$HISTORY_FILE"
echo "  ✅ 已创建: $HISTORY_FILE"

echo ""
echo "========================================================================"
echo "✅ 修复完成！"
echo ""
echo "📊 文件状态:"
ls -lh "$CONFIG_FILE" "$HISTORY_FILE" 2>/dev/null
echo ""
echo "🚀 现在可以重新运行回测:"
echo "  bash 快速重启_修复版.sh backtest-$MODEL"
echo "========================================================================"

