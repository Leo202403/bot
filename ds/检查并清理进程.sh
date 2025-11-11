#!/bin/bash
# V8.3.21 检查并清理多余进程

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "V8.3.21 服务器进程检查和清理"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ==========================================
# 第1步：Supervisor状态
# ==========================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第1步：Supervisor管理的服务"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

supervisorctl status

# ==========================================
# 第2步：Python进程详情
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第2步：所有Python进程详情"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "格式：USER PID %CPU %MEM START TIME COMMAND"
ps aux | grep python | grep -v grep | awk '{printf "%-10s %-8s %5s%% %5s%% %8s %8s %s\n", $1, $2, $3, $4, $9, $10, substr($0, index($0,$11))}'

# ==========================================
# 第3步：分类统计
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第3步：进程分类统计"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

QWEN_COUNT=$(ps aux | grep "qwen_多币种智能版.py" | grep -v grep | wc -l)
DEEPSEEK_COUNT=$(ps aux | grep "deepseek_多币种智能版.py" | grep -v grep | wc -l)
PYTHON_TOTAL=$(ps aux | grep python | grep -v grep | wc -l)

echo "📊 进程统计："
echo "  • Qwen进程数: $QWEN_COUNT"
echo "  • DeepSeek进程数: $DEEPSEEK_COUNT"
echo "  • Python总进程数: $PYTHON_TOTAL"

# ==========================================
# 第4步：识别问题进程
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第4步：识别潜在问题进程"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 检查Qwen进程
if [ "$QWEN_COUNT" -gt 1 ]; then
    echo "⚠️  发现多个Qwen进程（正常应该1个）："
    ps aux | grep "qwen_多币种智能版.py" | grep -v grep | awk '{print "   PID: " $2 " | 启动时间: " $9 " | 运行时长: " $10 " | CPU: " $3"%"}'
    echo ""
    echo "   建议：保留最新的进程，停止旧的进程"
    echo ""
    
    # 获取所有Qwen进程PID，按启动时间排序
    QWEN_PIDS=($(ps aux | grep "qwen_多币种智能版.py" | grep -v grep | awk '{print $2, $9}' | sort -k2 | awk '{print $1}'))
    
    if [ ${#QWEN_PIDS[@]} -gt 1 ]; then
        echo "   🔍 详细信息："
        for pid in "${QWEN_PIDS[@]}"; do
            ps -p $pid -o pid,lstart,etime,cmd | tail -1 | awk '{print "      PID " $1 " | 启动: " $2" "$3" "$4" "$5" "$6 " | 运行: " $7}'
        done
        echo ""
        
        # 找出最老的进程（要杀掉的）
        OLD_PIDS=("${QWEN_PIDS[@]:0:${#QWEN_PIDS[@]}-1}")
        echo "   💡 建议停止的旧进程："
        for pid in "${OLD_PIDS[@]}"; do
            echo "      kill -9 $pid"
        done
    fi
else
    echo "✅ Qwen进程正常（1个）"
fi

echo ""

# 检查DeepSeek进程
if [ "$DEEPSEEK_COUNT" -gt 1 ]; then
    echo "⚠️  发现多个DeepSeek进程（正常应该1个）："
    ps aux | grep "deepseek_多币种智能版.py" | grep -v grep | awk '{print "   PID: " $2 " | 启动时间: " $9 " | 运行时长: " $10 " | CPU: " $3"%"}'
    echo ""
    echo "   建议：保留最新的进程，停止旧的进程"
    echo ""
    
    # 获取所有DeepSeek进程PID，按启动时间排序
    DEEPSEEK_PIDS=($(ps aux | grep "deepseek_多币种智能版.py" | grep -v grep | awk '{print $2, $9}' | sort -k2 | awk '{print $1}'))
    
    if [ ${#DEEPSEEK_PIDS[@]} -gt 1 ]; then
        echo "   🔍 详细信息："
        for pid in "${DEEPSEEK_PIDS[@]}"; do
            ps -p $pid -o pid,lstart,etime,cmd | tail -1 | awk '{print "      PID " $1 " | 启动: " $2" "$3" "$4" "$5" "$6 " | 运行: " $7}'
        done
        echo ""
        
        # 找出最老的进程（要杀掉的）
        OLD_PIDS=("${DEEPSEEK_PIDS[@]:0:${#DEEPSEEK_PIDS[@]}-1}")
        echo "   💡 建议停止的旧进程："
        for pid in "${OLD_PIDS[@]}"; do
            echo "      kill -9 $pid"
        done
    fi
else
    echo "✅ DeepSeek进程正常（1个）"
fi

echo ""

# 检查是否有回测进程还在运行
BACKTEST_PIDS=$(ps aux | grep "MANUAL_BACKTEST=true" | grep -v grep | awk '{print $2}')
if [ ! -z "$BACKTEST_PIDS" ]; then
    echo "⚠️  发现回测进程还在运行："
    ps aux | grep "MANUAL_BACKTEST=true" | grep -v grep | awk '{print "   PID: " $2 " | 运行时长: " $10 " | CPU: " $3"%"}'
    echo ""
    echo "   如果回测已完成但进程未退出，建议手动停止："
    for pid in $BACKTEST_PIDS; do
        echo "      kill -9 $pid"
    done
    echo ""
else
    echo "✅ 无回测进程运行"
fi

# ==========================================
# 第5步：一键清理建议
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第5步：一键清理多余进程"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

NEED_CLEAN=0

# 收集需要停止的Qwen旧进程
if [ "$QWEN_COUNT" -gt 1 ]; then
    QWEN_PIDS=($(ps aux | grep "qwen_多币种智能版.py" | grep -v grep | awk '{print $2, $9}' | sort -k2 | awk '{print $1}'))
    OLD_QWEN_PIDS=("${QWEN_PIDS[@]:0:${#QWEN_PIDS[@]}-1}")
    NEED_CLEAN=1
fi

# 收集需要停止的DeepSeek旧进程
if [ "$DEEPSEEK_COUNT" -gt 1 ]; then
    DEEPSEEK_PIDS=($(ps aux | grep "deepseek_多币种智能版.py" | grep -v grep | awk '{print $2, $9}' | sort -k2 | awk '{print $1}'))
    OLD_DEEPSEEK_PIDS=("${DEEPSEEK_PIDS[@]:0:${#DEEPSEEK_PIDS[@]}-1}")
    NEED_CLEAN=1
fi

# 收集回测进程
BACKTEST_PIDS=($(ps aux | grep "MANUAL_BACKTEST=true" | grep -v grep | awk '{print $2}'))
if [ ${#BACKTEST_PIDS[@]} -gt 0 ]; then
    NEED_CLEAN=1
fi

if [ $NEED_CLEAN -eq 1 ]; then
    echo "⚠️  发现需要清理的进程"
    echo ""
    read -p "是否立即停止所有多余进程？(y/n): " -n 1 -r
    echo ""
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo ""
        echo "🔧 开始清理..."
        echo ""
        
        # 停止旧的Qwen进程
        if [ ${#OLD_QWEN_PIDS[@]} -gt 0 ]; then
            for pid in "${OLD_QWEN_PIDS[@]}"; do
                echo "  ⏹️  停止旧Qwen进程: $pid"
                kill -9 $pid 2>/dev/null && echo "     ✅ 已停止" || echo "     ⚠️  进程已不存在"
            done
        fi
        
        # 停止旧的DeepSeek进程
        if [ ${#OLD_DEEPSEEK_PIDS[@]} -gt 0 ]; then
            for pid in "${OLD_DEEPSEEK_PIDS[@]}"; do
                echo "  ⏹️  停止旧DeepSeek进程: $pid"
                kill -9 $pid 2>/dev/null && echo "     ✅ 已停止" || echo "     ⚠️  进程已不存在"
            done
        fi
        
        # 停止回测进程
        if [ ${#BACKTEST_PIDS[@]} -gt 0 ]; then
            for pid in "${BACKTEST_PIDS[@]}"; do
                echo "  ⏹️  停止回测进程: $pid"
                kill -9 $pid 2>/dev/null && echo "     ✅ 已停止" || echo "     ⚠️  进程已不存在"
            done
        fi
        
        echo ""
        echo "✅ 清理完成！"
        echo ""
        sleep 2
        
        # 再次检查
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "清理后状态"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""
        
        supervisorctl status
        
        echo ""
        QWEN_COUNT=$(ps aux | grep "qwen_多币种智能版.py" | grep -v grep | wc -l)
        DEEPSEEK_COUNT=$(ps aux | grep "deepseek_多币种智能版.py" | grep -v grep | wc -l)
        echo "📊 当前进程："
        echo "  • Qwen: $QWEN_COUNT 个"
        echo "  • DeepSeek: $DEEPSEEK_COUNT 个"
    else
        echo "⏩ 跳过清理"
    fi
else
    echo "✅ 无需清理，所有进程正常！"
fi

# ==========================================
# 第6步：前端检查
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第6步：前端进程检查"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

FRONTEND_COUNT=$(ps aux | grep -E 'node.*3000|前端' | grep -v grep | wc -l)
if [ $FRONTEND_COUNT -gt 0 ]; then
    echo "✅ 前端进程运行中（$FRONTEND_COUNT 个）："
    ps aux | grep -E 'node.*3000|前端' | grep -v grep | awk '{print "   PID: " $2 " | CPU: " $3"% | MEM: " $4"% | CMD: " substr($0, index($0,$11))}'
else
    echo "⚠️  未发现前端进程"
fi

# ==========================================
# 总结
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 检查完成"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "⏱️  完成时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

