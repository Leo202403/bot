#!/bin/bash
# 检查.env配置文件

echo "========================================================================"
echo "🔍 检查配置文件"
echo "========================================================================"

cd ~/10-23-bot/ds

echo ""
echo "1️⃣ 检查.env.qwen文件..."
if [ -f ".env.qwen" ]; then
    echo "   ✅ .env.qwen 存在"
    ls -lh .env.qwen
else
    echo "   ❌ .env.qwen 不存在 ← 这就是问题！"
    echo ""
    echo "🔧 解决方法："
    echo "   1. 从.env复制："
    echo "      cp .env .env.qwen"
    echo ""
    echo "   2. 或者创建新的.env.qwen："
    echo "      cat > .env.qwen << 'EOF'"
    echo "QWEN_API_KEY=your_qwen_api_key"
    echo "BINANCE_API_KEY=your_binance_api_key"
    echo "BINANCE_SECRET_KEY=your_binance_secret"
    echo "USE_PORTFOLIO_MARGIN=true"
    echo "EOF"
fi

echo ""
echo "2️⃣ 检查.env文件（deepseek用）..."
if [ -f ".env" ]; then
    echo "   ✅ .env 存在"
    ls -lh .env
else
    echo "   ⚠️ .env 不存在"
fi

echo ""
echo "3️⃣ 测试文件读取..."
python3 << 'PYTHON_EOF'
from pathlib import Path
_env_file = Path(__file__).parent / '.env.qwen'
print(f"   查找路径: {_env_file}")
print(f"   文件存在: {_env_file.exists()}")
if not _env_file.exists():
    print(f"   ❌ 这会导致程序crash!")
PYTHON_EOF

echo ""
echo "========================================================================"
echo "🎯 总结"
echo "========================================================================"
if [ ! -f ".env.qwen" ]; then
    echo "❌ 缺少 .env.qwen 文件 - 这就是程序不断重启的原因！"
    echo ""
    echo "🚀 快速修复："
    echo "   cd ~/10-23-bot/ds"
    echo "   cp .env .env.qwen  # 如果.env存在"
    echo "   # 然后重启程序"
else
    echo "✅ 配置文件完整，问题可能在其他地方"
fi

