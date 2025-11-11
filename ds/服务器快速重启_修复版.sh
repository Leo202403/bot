#!/bin/bash
# V8.3.21 服务器快速重启脚本（修复backtest模式）

case "$1" in
    qwen)
        echo "ℹ️  🔄 重启通义千问模型..."
        supervisorctl restart qwen
        sleep 2
        supervisorctl status qwen
        echo ""
        echo "💡 查看日志: tail -f /var/log/supervisor/qwen-stdout.log"
        ;;
    
    deepseek)
        echo "ℹ️  🔄 重启DeepSeek模型..."
        supervisorctl restart deepseek
        sleep 2
        supervisorctl status deepseek
        echo ""
        echo "💡 查看日志: tail -f /var/log/supervisor/deepseek-stdout.log"
        ;;
    
    backtest)
        echo "ℹ️  🔬 手动回测所有模型..."
        echo ""
        
        # ==========================================
        # 回测Qwen
        # ==========================================
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "回测模型1: Qwen"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""
        
        cd /root/10-23-bot/ds
        
        # 【关键修复】设置环境变量触发回测模式
        export MANUAL_BACKTEST=true
        
        # 运行Qwen回测
        python3 qwen_多币种智能版.py
        
        QWEN_EXIT=$?
        
        echo ""
        if [ $QWEN_EXIT -eq 0 ]; then
            echo "✅ Qwen回测完成（退出码: 0）"
        else
            echo "⚠️  Qwen回测退出（退出码: $QWEN_EXIT）"
        fi
        
        # ==========================================
        # 回测DeepSeek
        # ==========================================
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "回测模型2: DeepSeek"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""
        
        # 运行DeepSeek回测（环境变量已设置）
        python3 deepseek_多币种智能版.py
        
        DEEPSEEK_EXIT=$?
        
        echo ""
        if [ $DEEPSEEK_EXIT -eq 0 ]; then
            echo "✅ DeepSeek回测完成（退出码: 0）"
        else
            echo "⚠️  DeepSeek回测退出（退出码: $DEEPSEEK_EXIT）"
        fi
        
        # ==========================================
        # 总结
        # ==========================================
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "回测完成总结"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""
        
        if [ $QWEN_EXIT -eq 0 ]; then
            echo "  ✓ Qwen: 成功"
        else
            echo "  ✗ Qwen: 失败（退出码 $QWEN_EXIT）"
        fi
        
        if [ $DEEPSEEK_EXIT -eq 0 ]; then
            echo "  ✓ DeepSeek: 成功"
        else
            echo "  ✗ DeepSeek: 失败（退出码 $DEEPSEEK_EXIT）"
        fi
        
        echo ""
        echo "📧 请检查邮箱查看回测报告"
        echo "📱 请检查手机查看Bark通知"
        echo ""
        echo "💡 查看新参数："
        echo "   cat /root/10-23-bot/ds/trading_data/qwen/config.json | grep -A 5 scalping_params"
        echo "   cat /root/10-23-bot/ds/trading_data/deepseek/config.json | grep -A 5 scalping_params"
        ;;
    
    all)
        echo "ℹ️  🔄 重启所有模型..."
        supervisorctl restart qwen deepseek
        sleep 2
        supervisorctl status qwen deepseek
        echo ""
        echo "💡 查看Qwen日志: tail -f /var/log/supervisor/qwen-stdout.log"
        echo "💡 查看DeepSeek日志: tail -f /var/log/supervisor/deepseek-stdout.log"
        ;;
    
    stop)
        echo "ℹ️  ⏹️  停止所有模型..."
        supervisorctl stop qwen deepseek
        sleep 2
        supervisorctl status qwen deepseek
        ;;
    
    status)
        echo "ℹ️  📊 查看服务状态..."
        supervisorctl status
        echo ""
        echo "Python进程："
        ps aux | grep python | grep -E "qwen|deepseek" | grep -v grep
        ;;
    
    *)
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "V8.3.21 服务器快速重启脚本"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""
        echo "用法: $0 {qwen|deepseek|backtest|all|stop|status}"
        echo ""
        echo "命令说明:"
        echo "  qwen      - 重启通义千问模型"
        echo "  deepseek  - 重启DeepSeek模型"
        echo "  backtest  - 运行两个模型的手动回测"
        echo "  all       - 重启所有模型"
        echo "  stop      - 停止所有模型"
        echo "  status    - 查看服务状态"
        echo ""
        echo "示例:"
        echo "  $0 qwen       # 重启Qwen"
        echo "  $0 backtest   # 运行回测"
        echo "  $0 status     # 查看状态"
        echo ""
        exit 1
        ;;
esac

