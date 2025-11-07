#!/bin/bash
echo "🔍 诊断JSON错误 - V8.3.10.2"
echo "========================================================================"
echo ""

# 检查最近修改的JSON文件
echo "📊 最近修改的JSON文件（最可能的问题源）："
find ~/10-23-bot/ds/trading_data -name "*.json*" -mtime -1 -type f -exec ls -lh {} \; 2>/dev/null

echo ""
echo "========================================================================"
echo "🔍 验证每个JSON文件的完整性："
echo ""

for model in deepseek qwen; do
    echo "📁 检查 $model 模型的文件..."
    config_file="$HOME/10-23-bot/ds/trading_data/$model/learning_config.json"
    history_file="$HOME/10-23-bot/ds/trading_data/$model/iterative_optimization_history.jsonl"
    
    # 检查 learning_config.json
    if [ -f "$config_file" ]; then
        echo "  📄 $config_file"
        lines=$(wc -l < "$config_file" 2>/dev/null || echo "0")
        size=$(du -h "$config_file" 2>/dev/null | cut -f1 || echo "0")
        echo "     大小: $size | 行数: $lines"
        
        # 尝试解析JSON
        result=$(python3 -c "import json; json.load(open('$config_file'))" 2>&1)
        if [ $? -eq 0 ]; then
            echo "     ✅ JSON格式正确"
        else
            echo "     ❌ JSON格式错误:"
            echo "$result" | head -n 5
            echo ""
            echo "     🔧 损坏位置预览:"
            # 找出错误附近的内容
            error_line=$(echo "$result" | grep -oP "line \K\d+" | head -1)
            if [ ! -z "$error_line" ]; then
                start=$((error_line - 5))
                end=$((error_line + 5))
                echo "     第 $start-$end 行:"
                sed -n "${start},${end}p" "$config_file" 2>/dev/null | cat -n
            fi
        fi
        echo ""
    else
        echo "  ⚠️  $config_file 不存在"
    fi
    
    # 检查 iterative_optimization_history.jsonl
    if [ -f "$history_file" ]; then
        echo "  📄 $history_file"
        lines=$(wc -l < "$history_file" 2>/dev/null || echo "0")
        size=$(du -h "$history_file" 2>/dev/null | cut -f1 || echo "0")
        echo "     大小: $size | 行数: $lines"
        
        # 检查JSONL的每一行（只检查前10行和最后10行）
        echo "     检查前10行..."
        head -n 10 "$history_file" 2>/dev/null | while read line; do
            echo "$line" | python3 -c "import sys, json; json.loads(sys.stdin.read())" 2>&1 >/dev/null
            if [ $? -ne 0 ]; then
                echo "     ❌ 发现损坏行"
                break
            fi
        done
        
        echo "     检查最后10行..."
        tail -n 10 "$history_file" 2>/dev/null | while read line; do
            echo "$line" | python3 -c "import sys, json; json.loads(sys.stdin.read())" 2>&1 >/dev/null
            if [ $? -ne 0 ]; then
                echo "     ❌ 发现损坏行"
                break
            fi
        done
        
        echo "     ✅ JSONL基本检查完成"
        echo ""
    else
        echo "  ⚠️  $history_file 不存在"
    fi
    
    echo ""
done

echo "========================================================================"
echo "🔧 快速修复建议："
echo ""
echo "如果 learning_config.json 损坏："
echo "  1. 备份: mv learning_config.json learning_config.json.broken"
echo "  2. 重置: cp learning_config.json.backup learning_config.json (如果有备份)"
echo "  3. 或删除: rm learning_config.json (程序会重新生成)"
echo ""
echo "如果 iterative_optimization_history.jsonl 损坏："
echo "  1. 备份: mv iterative_optimization_history.jsonl iterative_optimization_history.jsonl.broken"
echo "  2. 删除: rm iterative_optimization_history.jsonl (可选，会重新开始记录)"
echo ""
echo "========================================================================"

