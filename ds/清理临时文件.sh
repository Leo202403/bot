#!/bin/bash
# 清理本地临时文件

cd "$(dirname "$0")"

echo "🗑️ 开始清理本地临时文件..."

# 要删除的文件列表
files_to_delete=(
    "立即更新并继续回测.txt"
)

deleted_count=0
for file in "${files_to_delete[@]}"; do
    if [ -f "$file" ]; then
        rm -f "$file"
        echo "  ✓ 已删除: $file"
        ((deleted_count++))
    fi
done

echo ""
echo "✅ 本地清理完成: 删除了 $deleted_count 个文件"
echo ""
echo "📝 保留的重要文件:"
echo "  - 回测内存优化说明.txt"
echo "  - 立即部署内存优化版.txt"
echo "  - qwen_多币种智能版.py"
echo "  - deepseek_多币种智能版.py"
