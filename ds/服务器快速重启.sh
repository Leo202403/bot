#!/bin/bash
# V8.3.21 服务器快速重启脚本

# 获取命令参数
ACTION=${1:-restart}

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "V8.3.21 服务器管理"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "操作: $ACTION"
echo ""

case "$ACTION" in
    restart)
        echo "🔄 重启所有AI服务..."
        supervisorctl restart qwen deepseek
        echo "✅ 重启完成！"
        ;;
        
    stop)
        echo "⏸️  停止所有AI服务..."
        supervisorctl stop qwen deepseek
        echo "✅ 已停止！"
        ;;
        
    start)
        echo "▶️  启动所有AI服务..."
        supervisorctl start qwen deepseek
        echo "✅ 已启动！"
        ;;
        
    status)
        echo "📊 服务状态:"
        supervisorctl status qwen deepseek
        ;;
        
    backtest)
        echo "🔬 手动回测所有模型..."
        
        # 停止AI服务（避免冲突）
        echo "⏸️  暂停AI服务..."
        supervisorctl stop qwen deepseek
        
        # 运行回测
        cd /root/10-23-bot/ds
        export MANUAL_BACKTEST=true
        
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "回测 Qwen"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        python3 qwen_多币种智能版.py
        
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "回测 DeepSeek"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        python3 deepseek_多币种智能版.py
        
        echo ""
        echo "✅ 回测完成！"
        
        # 恢复AI服务
        echo ""
        echo "▶️  恢复AI服务..."
        supervisorctl start qwen deepseek
        echo "✅ AI服务已恢复运行"
        ;;
        
    logs)
        MODEL=${2:-all}
        if [ "$MODEL" = "all" ]; then
            echo "📋 所有日志:"
            supervisorctl tail -f qwen deepseek
        else
            echo "📋 $MODEL 日志:"
            supervisorctl tail -f $MODEL
        fi
        ;;
        
    *)
        echo "❌ 未知操作: $ACTION"
        echo ""
        echo "用法:"
        echo "  bash $0 restart     # 重启所有服务"
        echo "  bash $0 stop        # 停止所有服务"
        echo "  bash $0 start       # 启动所有服务"
        echo "  bash $0 status      # 查看服务状态"
        echo "  bash $0 backtest    # 手动回测"
        echo "  bash $0 logs [qwen|deepseek|all]  # 查看日志"
        exit 1
        ;;
esac

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 操作完成！"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

