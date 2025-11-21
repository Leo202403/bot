#!/bin/bash

# 修复后端依赖问题

echo "=========================================="
echo "🔧 修复后端 Python 依赖"
echo "=========================================="
echo ""

BACKEND_DIR="/root/pythonc程序/my_project"
VENV_DIR="$BACKEND_DIR/venv"

# 1. 检查虚拟环境
echo "【步骤1】检查虚拟环境..."

if [ ! -d "$VENV_DIR" ]; then
    echo "❌ 虚拟环境不存在: $VENV_DIR"
    echo "   需要创建新的虚拟环境"
    exit 1
fi

echo "✓ 虚拟环境存在"
echo ""

# 2. 激活虚拟环境并检查 Flask
echo "【步骤2】检查 Flask 模块..."

cd "$BACKEND_DIR"

if $VENV_DIR/bin/python3 -c "import flask" 2>/dev/null; then
    echo "✓ Flask 已安装"
    FLASK_VERSION=$($VENV_DIR/bin/python3 -c "import flask; print(flask.__version__)")
    echo "  版本: $FLASK_VERSION"
else
    echo "❌ Flask 未安装"
    echo ""
    echo "【步骤3】安装依赖包..."
    
    # 检查是否有 requirements.txt
    if [ -f "$BACKEND_DIR/requirements.txt" ]; then
        echo "  找到 requirements.txt，安装依赖..."
        $VENV_DIR/bin/pip3 install -r requirements.txt
    else
        echo "  未找到 requirements.txt，手动安装核心依赖..."
        $VENV_DIR/bin/pip3 install flask gunicorn ccxt python-dotenv requests
    fi
    
    if [ $? -eq 0 ]; then
        echo "✓ 依赖安装成功"
    else
        echo "❌ 依赖安装失败"
        exit 1
    fi
fi

echo ""

# 3. 验证所有必需模块
echo "【步骤4】验证必需模块..."

REQUIRED_MODULES="flask ccxt dotenv requests"
ALL_OK=true

for module in $REQUIRED_MODULES; do
    if $VENV_DIR/bin/python3 -c "import $module" 2>/dev/null; then
        echo "  ✓ $module"
    else
        echo "  ❌ $module (缺失)"
        ALL_OK=false
    fi
done

echo ""

if [ "$ALL_OK" = true ]; then
    echo "=========================================="
    echo "✅ 依赖修复完成"
    echo "=========================================="
    echo ""
    echo "建议操作："
    echo "  1. 重启后端: cd /root/10-23-bot/ds && ./restart_backend.sh"
    echo "  2. 测试API: ./test_api.sh"
else
    echo "=========================================="
    echo "❌ 部分模块缺失"
    echo "=========================================="
    echo ""
    echo "请手动安装："
    echo "  cd $BACKEND_DIR"
    echo "  source venv/bin/activate"
    echo "  pip3 install flask gunicorn ccxt python-dotenv requests"
fi

echo "=========================================="

