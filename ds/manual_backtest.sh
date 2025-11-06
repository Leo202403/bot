#!/bin/bash

# V7.6.3.6 手动回测脚本
# 功能：立即触发参数优化，无需等待2小时周期

set -e

echo ""
echo "========================================================================"
echo "🔬 手动回测与参数优化工具 V7.6.3.6"
echo "========================================================================"
echo ""

# 检查是否在正确目录
if [ ! -f "deepseek_多币种智能版.py" ]; then
    echo "❌ 错误: 请在 ~/10-23-bot/ds 目录下运行"
    echo "   cd ~/10-23-bot/ds"
    echo "   bash manual_backtest.sh [deepseek|qwen|all]"
    exit 1
fi

# 检查并激活虚拟环境
if [ ! -d "venv" ]; then
    echo "❌ 错误: 虚拟环境不存在"
    echo "   请先创建虚拟环境: python3 -m venv venv"
    exit 1
fi

echo "🔧 激活虚拟环境..."
source venv/bin/activate

# 验证虚拟环境
if [ -z "$VIRTUAL_ENV" ]; then
    echo "❌ 错误: 虚拟环境激活失败"
    exit 1
fi

echo "✓ 虚拟环境已激活: $VIRTUAL_ENV"
echo ""

# 获取参数
TARGET="${1:-all}"

echo "📊 目标模型: $TARGET"
echo "⏰ 时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# DeepSeek回测
if [ "$TARGET" = "deepseek" ] || [ "$TARGET" = "all" ]; then
    echo "========================================================================"
    echo "🤖 DeepSeek 回测开始"
    echo "========================================================================"
    echo ""
    
    # 显示当前配置
    echo "【当前参数配置】"
    if [ -f "trading_data/deepseek/learning_config.json" ]; then
        python3 -c "
import json
with open('trading_data/deepseek/learning_config.json', 'r') as f:
    config = json.load(f)
    print(f\"  • 最小盈亏比: {config['global']['min_risk_reward']}\")
    print(f\"  • 指标共识要求: {config['global']['min_indicator_consensus']}\")
    print(f\"  • ATR止损倍数: {config['global']['atr_stop_multiplier']}\")
    print(f\"  • 基础仓位: {config['global'].get('base_position_pct', 15)}%\")
"
    fi
    echo ""
    
    # 运行回测
    MANUAL_BACKTEST=true python3 deepseek_多币种智能版.py
    
    echo ""
    echo "【优化后参数配置】"
    if [ -f "trading_data/deepseek/learning_config.json" ]; then
        python3 -c "
import json
with open('trading_data/deepseek/learning_config.json', 'r') as f:
    config = json.load(f)
    print(f\"  • 最小盈亏比: {config['global']['min_risk_reward']}\")
    print(f\"  • 指标共识要求: {config['global']['min_indicator_consensus']}\")
    print(f\"  • ATR止损倍数: {config['global']['atr_stop_multiplier']}\")
    print(f\"  • 基础仓位: {config['global'].get('base_position_pct', 15)}%\")
"
    fi
    echo ""
    
    # 显示迭代历史（最近1次）
    echo "【最近迭代历史】"
    if [ -f "trading_data/deepseek/iterative_optimization_history.jsonl" ]; then
        python3 -c "
import json
with open('trading_data/deepseek/iterative_optimization_history.jsonl', 'r') as f:
    lines = f.readlines()
    if lines:
        record = json.loads(lines[-1])
        print(f\"  时间: {record['timestamp']}\")
        print(f\"  • 总轮次: {record['total_rounds']}\")
        print(f\"  • 最优轮次: {record['best_round_num']}\")
        print(f\"  • 基准指标: {record['baseline_metric']:.4f}\")
        print(f\"  • 最优指标: {record['best_metric']:.4f}\")
        print(f\"  • 提升幅度: {record['improvement_pct']:+.1f}%\")
        print(f\"\\n  轮次详情:\")
        for r in record['rounds_summary']:
            status = '✅' if r['improved'] else '❌'
            print(f\"    {status} 第{r['round']}轮: {r['metric']:.4f}\")
" 2>/dev/null || echo "  暂无历史记录"
    else
        echo "  暂无历史记录"
    fi
    echo ""
    
    echo "✅ DeepSeek回测完成！"
    echo ""
fi

# Qwen回测
if [ "$TARGET" = "qwen" ] || [ "$TARGET" = "all" ]; then
    echo "========================================================================"
    echo "🤖 Qwen 回测开始"
    echo "========================================================================"
    echo ""
    
    # 显示当前配置
    echo "【当前参数配置】"
    if [ -f "trading_data/qwen/learning_config.json" ]; then
        python3 -c "
import json
with open('trading_data/qwen/learning_config.json', 'r') as f:
    config = json.load(f)
    print(f\"  • 最小盈亏比: {config['global']['min_risk_reward']}\")
    print(f\"  • 指标共识要求: {config['global']['min_indicator_consensus']}\")
    print(f\"  • ATR止损倍数: {config['global']['atr_stop_multiplier']}\")
    print(f\"  • 基础仓位: {config['global'].get('base_position_pct', 15)}%\")
"
    fi
    echo ""
    
    # 运行回测
    MANUAL_BACKTEST=true python3 qwen_多币种智能版.py
    
    echo ""
    echo "【优化后参数配置】"
    if [ -f "trading_data/qwen/learning_config.json" ]; then
        python3 -c "
import json
with open('trading_data/qwen/learning_config.json', 'r') as f:
    config = json.load(f)
    print(f\"  • 最小盈亏比: {config['global']['min_risk_reward']}\")
    print(f\"  • 指标共识要求: {config['global']['min_indicator_consensus']}\")
    print(f\"  • ATR止损倍数: {config['global']['atr_stop_multiplier']}\")
    print(f\"  • 基础仓位: {config['global'].get('base_position_pct', 15)}%\")
"
    fi
    echo ""
    
    # 显示迭代历史（最近1次）
    echo "【最近迭代历史】"
    if [ -f "trading_data/qwen/iterative_optimization_history.jsonl" ]; then
        python3 -c "
import json
with open('trading_data/qwen/iterative_optimization_history.jsonl', 'r') as f:
    lines = f.readlines()
    if lines:
        record = json.loads(lines[-1])
        print(f\"  时间: {record['timestamp']}\")
        print(f\"  • 总轮次: {record['total_rounds']}\")
        print(f\"  • 最优轮次: {record['best_round_num']}\")
        print(f\"  • 基准指标: {record['baseline_metric']:.4f}\")
        print(f\"  • 最优指标: {record['best_metric']:.4f}\")
        print(f\"  • 提升幅度: {record['improvement_pct']:+.1f}%\")
        print(f\"\\n  轮次详情:\")
        for r in record['rounds_summary']:
            status = '✅' if r['improved'] else '❌'
            print(f\"    {status} 第{r['round']}轮: {r['metric']:.4f}\")
" 2>/dev/null || echo "  暂无历史记录"
    else
        echo "  暂无历史记录"
    fi
    echo ""
    
    echo "✅ Qwen回测完成！"
    echo ""
fi

echo "========================================================================"
echo "✅ 回测优化完成"
echo "========================================================================"
echo ""
echo "💡 提示:"
echo "  • 参数已自动更新到配置文件"
echo "  • 正在运行的机器人将在下个周期使用新参数"
echo "  • 或者重启机器人立即生效:"
echo ""
echo "    # 停止当前进程"
echo "    ps aux | grep '多币种智能版.py' | grep -v grep | awk '{print \$2}' | xargs kill"
echo ""
echo "    # 重新启动"
echo "    nohup python3 deepseek_多币种智能版.py > logs/deepseek_trading.log 2>&1 &"
echo "    nohup python3 qwen_多币种智能版.py > logs/qwen_trading.log 2>&1 &"
echo ""
echo "========================================================================"

