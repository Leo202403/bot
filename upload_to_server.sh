#!/bin/bash
# V8.5.2.4.89.2 快速上传脚本

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查参数
if [ -z "$1" ]; then
    echo -e "${RED}❌ 错误: 请提供服务器IP地址${NC}"
    echo "用法: ./upload_to_server.sh <服务器IP>"
    echo "示例: ./upload_to_server.sh 47.76.123.45"
    exit 1
fi

SERVER_IP=$1

echo -e "${GREEN}======================================================================${NC}"
echo -e "${GREEN}📤 开始上传文件到服务器: $SERVER_IP${NC}"
echo -e "${GREEN}======================================================================${NC}\n"

# 文件列表
FILES=(
    "ds/deepseek_多币种智能版.py"
    "ds/qwen_多币种智能版.py"
    "ds/restore_data_volume.py"
    "ds/email_bark_formatter.py"
    "ds/phase3_enhanced_optimizer.py"
    "ds/phase4_validator.py"
    "ds/服务器操作_V8.5.2.4.89.2_Bug修复与数据恢复.txt"
)

# 上传每个文件
for file in "${FILES[@]}"; do
    echo -e "${YELLOW}📦 上传: $file${NC}"
    scp "$file" "root@$SERVER_IP:/root/10-23-bot/$file"
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ 成功${NC}\n"
    else
        echo -e "${RED}❌ 失败${NC}\n"
        exit 1
    fi
done

echo -e "${GREEN}======================================================================${NC}"
echo -e "${GREEN}✅ 所有文件上传完成！${NC}"
echo -e "${GREEN}======================================================================${NC}\n"

echo -e "${YELLOW}📝 下一步操作：${NC}"
echo -e "   1. SSH到服务器: ${GREEN}ssh root@$SERVER_IP${NC}"
echo -e "   2. 进入目录: ${GREEN}cd /root/10-23-bot/ds${NC}"
echo -e "   3. 开始阶段1: ${GREEN}python3 restore_data_volume.py stage1${NC}"
echo -e "   4. 运行回测: ${GREEN}MANUAL_BACKTEST=true python3 run_with_memory_monitor.py > /tmp/backtest_stage1.txt 2>&1 &${NC}"
echo -e "   5. 查看输出: ${GREEN}tail -f /tmp/backtest_stage1.txt${NC}\n"

echo -e "${YELLOW}📊 内存监控：${NC}"
echo -e "   ${GREEN}cat memory_monitor_simple.log | awk -F',' '{print \$2,\$3}' | sort -n | tail -5${NC}\n"

