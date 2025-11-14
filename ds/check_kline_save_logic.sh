#!/bin/bash

echo "============================================================"
echo "检查K线数据保存逻辑"
echo "============================================================"

echo -e "\n【1. 检查是否有kline_data目录】"
for model in qwen deepseek; do
    dir="/root/10-23-bot/ds/trading_data/${model}/kline_data"
    echo -e "\n${model}:"
    if [ -d "$dir" ]; then
        echo "  ✅ 目录存在: $dir"
        file_count=$(ls -1 "$dir" 2>/dev/null | wc -l)
        echo "  📊 文件数量: $file_count"
        if [ $file_count -gt 0 ]; then
            echo "  📁 文件列表（前5个）:"
            ls -lh "$dir" | tail -n +2 | head -5 | while read line; do
                echo "    $line"
            done
        fi
    else
        echo "  ❌ 目录不存在: $dir"
    fi
done

echo -e "\n============================================================"
echo "【2. 检查代码中的K线数据保存逻辑】"
echo "============================================================"

echo -e "\n🔍 搜索 'kline_data' 关键词:"
grep -n "kline_data" /root/10-23-bot/ds/qwen_多币种智能版.py /root/10-23-bot/ds/deepseek_多币种智能版.py 2>/dev/null | head -20

echo -e "\n🔍 搜索 'save.*kline' 关键词:"
grep -n "save.*kline" /root/10-23-bot/ds/qwen_多币种智能版.py /root/10-23-bot/ds/deepseek_多币种智能版.py 2>/dev/null | head -20

echo -e "\n============================================================"
echo "【3. 检查市场快照文件】"
echo "============================================================"

for model in qwen deepseek; do
    snapshot_dir="/root/10-23-bot/ds/trading_data/${model}/kline_snapshots"
    echo -e "\n${model}:"
    if [ -d "$snapshot_dir" ]; then
        latest_file=$(ls -t "$snapshot_dir"/*.json 2>/dev/null | head -1)
        if [ -n "$latest_file" ]; then
            echo "  ✅ 最新快照: $(basename $latest_file)"
            size=$(du -h "$latest_file" | cut -f1)
            echo "  📊 文件大小: $size"
            
            # 检查第一条记录的字段
            echo "  📋 数据字段（前10个）:"
            python3 << EOF
import json
with open('$latest_file', 'r') as f:
    data = json.load(f)
    if data:
        fields = list(data[0].keys())[:10]
        for field in fields:
            print(f"    - {field}")
        print(f"    ... 共 {len(data[0].keys())} 个字段")
        print(f"  📊 记录数量: {len(data)}")
EOF
        else
            echo "  ⚠️ 没有找到快照文件"
        fi
    else
        echo "  ❌ 目录不存在: $snapshot_dir"
    fi
done

echo -e "\n============================================================"
echo "【4. 检查前端API】"
echo "============================================================"

if [ -d "/root/10-23-bot/frontend" ]; then
    echo "🔍 搜索前端K线数据API:"
    grep -rn "kline" /root/10-23-bot/frontend/ 2>/dev/null | grep -E "\.(js|jsx|ts|tsx|vue):" | head -10
else
    echo "⚠️ 前端目录不存在"
fi

if [ -d "/root/10-23-bot/backend" ]; then
    echo -e "\n🔍 搜索后端K线数据API:"
    grep -rn "kline" /root/10-23-bot/backend/ 2>/dev/null | grep -E "\.(py|js):" | head -10
else
    echo "⚠️ 后端目录不存在"
fi

echo -e "\n============================================================"
echo "【5. 诊断结论】"
echo "============================================================"

# 检查kline_data目录是否存在且有文件
qwen_kline_count=$(ls -1 /root/10-23-bot/ds/trading_data/qwen/kline_data 2>/dev/null | wc -l)
deepseek_kline_count=$(ls -1 /root/10-23-bot/ds/trading_data/deepseek/kline_data 2>/dev/null | wc -l)

if [ $qwen_kline_count -eq 0 ] && [ $deepseek_kline_count -eq 0 ]; then
    echo "❌ 问题确认：系统没有保存K线数据文件"
    echo ""
    echo "📝 建议："
    echo "  1. 从市场快照中提取K线数据（临时方案）"
    echo "  2. 修改AI脚本，添加K线数据保存逻辑（永久方案）"
    echo "  3. 或修改前端，让它能从市场快照中提取K线数据"
else
    echo "✅ K线数据文件存在"
    echo "  Qwen: $qwen_kline_count 个文件"
    echo "  DeepSeek: $deepseek_kline_count 个文件"
    echo ""
    echo "⚠️ 但诊断脚本报告文件不存在，可能是文件名格式问题"
fi

