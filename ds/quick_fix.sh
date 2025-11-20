#!/bin/bash
# 快速数据修正脚本

set -e

echo "=================================="
echo "🔧 快速数据修正"
echo "=================================="
echo ""

# 切换到脚本目录
cd "$(dirname "$0")"

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo "❌ 未找到 python3，请先安装"
    exit 1
fi

# 显示菜单
echo "请选择操作:"
echo "  1) 仅检查数据（不修正）"
echo "  2) 检查并修正数据"
echo "  3) 查看帮助"
echo "  4) 退出"
echo ""
read -p "请输入选项 [1-4]: " choice

case $choice in
    1)
        echo ""
        echo "执行检查..."
        python3 fix_data_integrity.py --check-only
        ;;
    2)
        echo ""
        echo "⚠️  警告: 即将修正数据，建议先停止交易系统"
        read -p "是否继续? (y/n): " confirm
        if [[ $confirm == "y" || $confirm == "Y" ]]; then
            echo ""
            echo "执行修正..."
            python3 fix_data_integrity.py
        else
            echo "已取消"
            exit 0
        fi
        ;;
    3)
        python3 fix_data_integrity.py --help
        ;;
    4)
        echo "退出"
        exit 0
        ;;
    *)
        echo "❌ 无效选项"
        exit 1
        ;;
esac

echo ""
echo "=================================="
echo "✅ 完成"
echo "=================================="

