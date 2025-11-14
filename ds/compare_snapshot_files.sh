#!/bin/bash

echo "============================================================"
echo "对比手动生成和自动运行的快照文件差异"
echo "============================================================"

echo -e "\n【1. 检查文件是否存在】"
today=$(date +%Y%m%d)
yesterday=$(date -d "yesterday" +%Y%m%d 2>/dev/null || date -v-1d +%Y%m%d)

for model in qwen deepseek; do
    dir="/root/10-23-bot/ds/trading_data/${model}/market_snapshots"
    echo -e "\n${model}:"
    
    if [ -d "$dir" ]; then
        echo "  ✅ 目录存在"
        
        # 列出最近3天的文件
        echo "  📁 最近3天的文件:"
        ls -lh "$dir"/*.csv 2>/dev/null | tail -3 | while read line; do
            echo "    $line"
        done
        
        # 检查今天的文件
        today_file="$dir/${today}.csv"
        if [ -f "$today_file" ]; then
            echo -e "\n  ✅ 今天的文件存在: ${today}.csv"
            size=$(du -h "$today_file" | cut -f1)
            lines=$(wc -l < "$today_file")
            echo "     大小: $size"
            echo "     行数: $lines"
            
            # 检查文件内容
            echo "     前3行:"
            head -3 "$today_file" | while IFS= read -r line; do
                echo "       $line"
            done
        else
            echo -e "\n  ❌ 今天的文件不存在: ${today}.csv"
        fi
        
        # 检查昨天的文件
        yesterday_file="$dir/${yesterday}.csv"
        if [ -f "$yesterday_file" ]; then
            echo -e "\n  ✅ 昨天的文件存在: ${yesterday}.csv"
            size=$(du -h "$yesterday_file" | cut -f1)
            lines=$(wc -l < "$yesterday_file")
            echo "     大小: $size"
            echo "     行数: $lines"
        else
            echo -e "\n  ⚠️ 昨天的文件不存在: ${yesterday}.csv"
        fi
    else
        echo "  ❌ 目录不存在: $dir"
    fi
done

echo -e "\n============================================================"
echo "【2. 检查文件完整性】"
echo "============================================================"

for model in qwen deepseek; do
    today_file="/root/10-23-bot/ds/trading_data/${model}/market_snapshots/${today}.csv"
    
    if [ -f "$today_file" ]; then
        echo -e "\n${model} - ${today}.csv:"
        
        # 检查字段数量
        header=$(head -1 "$today_file")
        field_count=$(echo "$header" | tr ',' '\n' | wc -l)
        echo "  字段数量: $field_count"
        
        # 检查是否有数据行
        data_lines=$(($(wc -l < "$today_file") - 1))
        echo "  数据行数: $data_lines"
        
        # 检查币种
        if [ $data_lines -gt 0 ]; then
            echo "  币种列表:"
            tail -n +2 "$today_file" | cut -d',' -f2 | sort -u | while read coin; do
                count=$(tail -n +2 "$today_file" | cut -d',' -f2 | grep -c "^${coin}$")
                echo "    - $coin: $count 条记录"
            done
        fi
        
        # 检查时间范围
        if [ $data_lines -gt 0 ]; then
            first_time=$(tail -n +2 "$today_file" | head -1 | cut -d',' -f1)
            last_time=$(tail -n +2 "$today_file" | tail -1 | cut -d',' -f1)
            echo "  时间范围: $first_time ~ $last_time"
        fi
    fi
done

echo -e "\n============================================================"
echo "【3. 检查文件权限】"
echo "============================================================"

for model in qwen deepseek; do
    dir="/root/10-23-bot/ds/trading_data/${model}/market_snapshots"
    echo -e "\n${model}:"
    
    if [ -d "$dir" ]; then
        ls -ld "$dir"
        
        today_file="$dir/${today}.csv"
        if [ -f "$today_file" ]; then
            ls -l "$today_file"
        fi
    fi
done

echo -e "\n============================================================"
echo "【4. 对比手动生成和自动运行的差异】"
echo "============================================================"

echo "检查最近修改的文件："
for model in qwen deepseek; do
    dir="/root/10-23-bot/ds/trading_data/${model}/market_snapshots"
    echo -e "\n${model}:"
    
    if [ -d "$dir" ]; then
        # 找出最近修改的文件
        latest_file=$(ls -t "$dir"/*.csv 2>/dev/null | head -1)
        if [ -n "$latest_file" ]; then
            echo "  最新文件: $(basename $latest_file)"
            stat "$latest_file" | grep -E "Modify|Access|Change"
            
            # 检查是否是今天创建的
            file_date=$(stat -c %y "$latest_file" 2>/dev/null | cut -d' ' -f1 | tr -d '-' || stat -f %Sm -t %Y%m%d "$latest_file")
            if [ "$file_date" == "$today" ]; then
                echo "  ✅ 今天创建/修改"
            else
                echo "  ⚠️ 不是今天创建/修改 (文件日期: $file_date)"
            fi
        fi
    fi
done

echo -e "\n============================================================"
echo "【5. 诊断结论】"
echo "============================================================"

# 检查是否有数据
qwen_today="/root/10-23-bot/ds/trading_data/qwen/market_snapshots/${today}.csv"
deepseek_today="/root/10-23-bot/ds/trading_data/deepseek/market_snapshots/${today}.csv"

qwen_lines=0
deepseek_lines=0

if [ -f "$qwen_today" ]; then
    qwen_lines=$(wc -l < "$qwen_today")
fi

if [ -f "$deepseek_today" ]; then
    deepseek_lines=$(wc -l < "$deepseek_today")
fi

echo "Qwen 今天的数据: $qwen_lines 行"
echo "DeepSeek 今天的数据: $deepseek_lines 行"

if [ $qwen_lines -gt 1 ] && [ $deepseek_lines -gt 1 ]; then
    echo -e "\n✅ 两个模型都有今天的数据"
    echo ""
    echo "📝 可能的问题："
    echo "  1. 前端读取的是旧数据（缓存问题）"
    echo "  2. 前端API路径配置错误"
    echo "  3. 数据格式不符合前端预期"
    echo "  4. 文件权限问题导致前端无法读取"
else
    echo -e "\n❌ 数据不完整"
    echo ""
    echo "📝 可能的问题："
    echo "  1. 系统没有正常运行"
    echo "  2. 数据保存逻辑有问题"
    echo "  3. 文件被删除或覆盖"
fi

