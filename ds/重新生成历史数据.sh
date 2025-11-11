#!/bin/bash
# V8.3.21 重新生成历史数据

# ==========================================
# 使用说明
# ==========================================
# 用法1: bash 重新生成历史数据.sh 20251025
#   -> 从2025年10月25日生成到今天
#
# 用法2: bash 重新生成历史数据.sh
#   -> 使用默认开始日期（14天前）
# ==========================================

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "V8.3.21 重新生成历史数据"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ==========================================
# 第1步：确定开始日期
# ==========================================
if [ -z "$1" ]; then
    # 如果没有提供日期参数，默认从14天前开始
    START_DATE=$(date -d "14 days ago" +%Y%m%d 2>/dev/null || date -v-14d +%Y%m%d)
    echo "ℹ️  未提供开始日期，使用默认：$START_DATE（14天前）"
else
    START_DATE=$1
    echo "ℹ️  开始日期：$START_DATE"
fi

echo ""

# ==========================================
# 第2步：备份现有数据
# ==========================================
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第1步：备份现有数据"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

cd /root/10-23-bot/ds

BACKUP_DIR="trading_data/market_snapshots_backup_$(date +%Y%m%d_%H%M%S)"
SNAPSHOT_DIR="trading_data/market_snapshots"

if [ -d "$SNAPSHOT_DIR" ] && [ "$(ls -A $SNAPSHOT_DIR 2>/dev/null)" ]; then
    echo "📦 备份现有快照到: $BACKUP_DIR"
    mkdir -p "$BACKUP_DIR"
    cp -r "$SNAPSHOT_DIR"/* "$BACKUP_DIR/" 2>/dev/null || true
    echo "✅ 备份完成"
    
    # 显示备份文件数量
    BACKUP_COUNT=$(ls -1 "$BACKUP_DIR" 2>/dev/null | wc -l)
    echo "   备份文件数: $BACKUP_COUNT"
else
    echo "ℹ️  无现有快照，跳过备份"
fi

# ==========================================
# 第3步：清理旧数据（可选）
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第2步：清理旧数据"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

read -p "是否清理现有快照后重新生成？(y/n): " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    if [ -d "$SNAPSHOT_DIR" ]; then
        rm -rf "$SNAPSHOT_DIR"/*
        echo "✅ 已清理旧快照"
    fi
else
    echo "⏩ 保留现有快照，仅补充新数据"
fi

# ==========================================
# 第4步：生成历史数据
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第3步：生成历史数据"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "📅 开始日期: $START_DATE"
echo "📅 结束日期: $(date +%Y%m%d)（今天）"
echo ""
echo "⏱️  预计耗时: 根据日期范围，可能需要几分钟到十几分钟"
echo ""

# 检查是否在虚拟环境中
if [ -f "venv/bin/python" ]; then
    PYTHON_CMD="venv/bin/python"
    echo "ℹ️  使用虚拟环境Python"
else
    PYTHON_CMD="python3"
    echo "ℹ️  使用系统Python3"
fi

# 执行生成脚本
echo "🚀 开始生成..."
echo ""

$PYTHON_CMD export_historical_data.py $START_DATE

EXPORT_EXIT=$?

echo ""
if [ $EXPORT_EXIT -eq 0 ]; then
    echo "✅ 历史数据生成完成（退出码: 0）"
else
    echo "⚠️  历史数据生成异常（退出码: $EXPORT_EXIT）"
fi

# ==========================================
# 第5步：验证生成结果
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "第4步：验证生成结果"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

if [ -d "$SNAPSHOT_DIR" ]; then
    SNAPSHOT_COUNT=$(ls -1 "$SNAPSHOT_DIR" 2>/dev/null | wc -l)
    echo "📊 快照文件总数: $SNAPSHOT_COUNT"
    
    if [ $SNAPSHOT_COUNT -gt 0 ]; then
        echo ""
        echo "📅 最早快照: $(ls -1 "$SNAPSHOT_DIR" | head -1)"
        echo "📅 最新快照: $(ls -1 "$SNAPSHOT_DIR" | tail -1)"
        
        echo ""
        echo "💾 最新快照内容预览:"
        LATEST_FILE=$(ls -1 "$SNAPSHOT_DIR" | tail -1)
        if [ -f "$SNAPSHOT_DIR/$LATEST_FILE" ]; then
            # 显示文件大小
            FILE_SIZE=$(du -h "$SNAPSHOT_DIR/$LATEST_FILE" | cut -f1)
            echo "   文件: $LATEST_FILE"
            echo "   大小: $FILE_SIZE"
            
            # 显示行数（如果是CSV）
            if [[ $LATEST_FILE == *.csv ]]; then
                LINE_COUNT=$(wc -l < "$SNAPSHOT_DIR/$LATEST_FILE")
                echo "   记录数: $((LINE_COUNT - 1)) 条（不含表头）"
            fi
        fi
    else
        echo "⚠️  警告：未找到生成的快照文件"
    fi
else
    echo "❌ 错误：快照目录不存在"
fi

# ==========================================
# 总结
# ==========================================
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 完成！"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "⏱️  完成时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

if [ $EXPORT_EXIT -eq 0 ] && [ $SNAPSHOT_COUNT -gt 0 ]; then
    echo "💡 下一步："
    echo "   1. 查看快照目录: ls -lh $SNAPSHOT_DIR"
    echo "   2. 运行回测验证: bash ~/快速重启_修复版.sh backtest"
    echo ""
    echo "📂 快照位置: /root/10-23-bot/ds/$SNAPSHOT_DIR"
    echo "📂 备份位置: /root/10-23-bot/ds/$BACKUP_DIR"
else
    echo "⚠️  请检查错误日志并重试"
fi

echo ""

