#!/bin/bash
# V8.3.21 服务器依赖完整安装脚本

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "V8.3.21 安装所有依赖"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 检查 requirements.txt
cd /root/10-23-bot/ds

if [ ! -f "requirements.txt" ]; then
    echo "❌ requirements.txt 不存在"
    exit 1
fi

echo "📦 安装 Python 依赖包..."
echo "----------------------------------------"

# 方式1: 使用 pip3（添加 --break-system-packages）
echo "尝试方式1: pip3 install"
pip3 install -r requirements.txt --break-system-packages

if [ $? -eq 0 ]; then
    echo "✅ 依赖安装成功（pip3）"
else
    echo "⚠️  pip3 安装失败，尝试系统包管理器"
    
    # 方式2: 安装关键的系统包
    echo ""
    echo "尝试方式2: apt install"
    
    apt-get update -qq
    
    # 安装主要依赖
    apt-get install -y \
        python3-openai \
        python3-schedule \
        python3-requests \
        python3-ccxt \
        python3-pandas \
        python3-numpy \
        2>/dev/null
    
    # 有些包可能没有系统版本，用 pip3 单独安装
    echo ""
    echo "补充安装缺失的包..."
    
    # OpenAI (必须)
    python3 -c "import openai" 2>/dev/null || \
        pip3 install openai --break-system-packages -q
    
    # Schedule (必须)
    python3 -c "import schedule" 2>/dev/null || \
        pip3 install schedule --break-system-packages -q
    
    # CCXT (必须)
    python3 -c "import ccxt" 2>/dev/null || \
        pip3 install ccxt --break-system-packages -q
    
    echo "✅ 依赖安装完成（混合方式）"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "验证关键依赖"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 验证关键包
MISSING=""

python3 -c "import openai" 2>/dev/null || MISSING="$MISSING openai"
python3 -c "import schedule" 2>/dev/null || MISSING="$MISSING schedule"
python3 -c "import ccxt" 2>/dev/null || MISSING="$MISSING ccxt"
python3 -c "import pandas" 2>/dev/null || MISSING="$MISSING pandas"
python3 -c "import numpy" 2>/dev/null || MISSING="$MISSING numpy"
python3 -c "import requests" 2>/dev/null || MISSING="$MISSING requests"

if [ -z "$MISSING" ]; then
    echo "✅ 所有关键依赖已安装"
    echo ""
    echo "已安装的包："
    echo "  ✓ openai"
    echo "  ✓ schedule"
    echo "  ✓ ccxt"
    echo "  ✓ pandas"
    echo "  ✓ numpy"
    echo "  ✓ requests"
else
    echo "❌ 以下包安装失败：$MISSING"
    echo ""
    echo "请手动安装："
    for pkg in $MISSING; do
        echo "  pip3 install $pkg --break-system-packages"
    done
    exit 1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 依赖安装完成！"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "💡 现在可以运行："
echo "   bash ~/快速重启_修复版.sh backtest"
echo ""

