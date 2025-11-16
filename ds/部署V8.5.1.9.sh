#!/bin/bash

echo "========================================"
echo "V8.5.1.9 最小名义价值自动调整修复 - 部署脚本"
echo "========================================"
echo ""

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 工作目录
WORK_DIR=~/10-23-bot/ds

echo "1. 检查工作目录..."
if [ ! -d "$WORK_DIR" ]; then
    echo -e "${RED}❌ 目录不存在: $WORK_DIR${NC}"
    exit 1
fi
cd "$WORK_DIR" || exit 1
echo -e "${GREEN}✓ 工作目录: $WORK_DIR${NC}"
echo ""

echo "2. 备份现有文件..."
if [ -f "deepseek_多币种智能版.py" ]; then
    cp deepseek_多币种智能版.py deepseek_多币种智能版.py.bak_v8519
    echo -e "${GREEN}✓ 已备份 deepseek_多币种智能版.py${NC}"
else
    echo -e "${YELLOW}⚠️ deepseek_多币种智能版.py 不存在${NC}"
fi

if [ -f "qwen_多币种智能版.py" ]; then
    cp qwen_多币种智能版.py qwen_多币种智能版.py.bak_v8519
    echo -e "${GREEN}✓ 已备份 qwen_多币种智能版.py${NC}"
else
    echo -e "${YELLOW}⚠️ qwen_多币种智能版.py 不存在${NC}"
fi
echo ""

echo "3. 验证修改..."
if grep -q "V8.5.1.9" deepseek_多币种智能版.py; then
    echo -e "${GREEN}✓ deepseek_多币种智能版.py 包含 V8.5.1.9 修复${NC}"
else
    echo -e "${RED}❌ deepseek_多币种智能版.py 不包含 V8.5.1.9 修复${NC}"
    exit 1
fi

if grep -q "V8.5.1.9" qwen_多币种智能版.py; then
    echo -e "${GREEN}✓ qwen_多币种智能版.py 包含 V8.5.1.9 修复${NC}"
else
    echo -e "${RED}❌ qwen_多币种智能版.py 不包含 V8.5.1.9 修复${NC}"
    exit 1
fi
echo ""

echo "4. 停止现有进程..."
DEEPSEEK_PID=$(pgrep -f "deepseek_多币种智能版.py")
if [ -n "$DEEPSEEK_PID" ]; then
    pkill -f deepseek_多币种智能版.py
    sleep 2
    echo -e "${GREEN}✓ 已停止 deepseek 进程 (PID: $DEEPSEEK_PID)${NC}"
else
    echo -e "${YELLOW}⚠️ 未找到运行中的 deepseek 进程${NC}"
fi

QWEN_PID=$(pgrep -f "qwen_多币种智能版.py")
if [ -n "$QWEN_PID" ]; then
    pkill -f qwen_多币种智能版.py
    sleep 2
    echo -e "${GREEN}✓ 已停止 qwen 进程 (PID: $QWEN_PID)${NC}"
else
    echo -e "${YELLOW}⚠️ 未找到运行中的 qwen 进程${NC}"
fi
echo ""

echo "5. 启动服务..."
echo -e "${YELLOW}   正在启动 deepseek...${NC}"
nohup python3 "$WORK_DIR/deepseek_多币种智能版.py" > ~/deepseek.log 2>&1 &
DEEPSEEK_NEW_PID=$!
sleep 3

if ps -p $DEEPSEEK_NEW_PID > /dev/null; then
    echo -e "${GREEN}✓ deepseek 启动成功 (PID: $DEEPSEEK_NEW_PID)${NC}"
else
    echo -e "${RED}❌ deepseek 启动失败，请检查日志: ~/deepseek.log${NC}"
fi
echo ""

echo "6. 验证运行状态..."
sleep 5
echo "最近的日志输出："
tail -n 20 ~/deepseek.log
echo ""

echo "========================================"
echo -e "${GREEN}✅ 部署完成！${NC}"
echo "========================================"
echo ""
echo "监控命令："
echo "  查看实时日志: tail -f ~/deepseek.log"
echo "  查看调整记录: grep '仓位自动调整' ~/deepseek.log"
echo "  查看资金不足: grep '账户资金不足' ~/deepseek.log"
echo ""
echo "下一次开仓时，系统将自动调整仓位以满足最小名义价值要求。"
echo ""

