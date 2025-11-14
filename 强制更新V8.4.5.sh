#!/bin/bash

# V8.4.5 强制更新脚本（带验证）

echo "========================================="
echo "V8.4.5 强制更新脚本"
echo "========================================="
echo ""

# 服务器IP
read -p "请输入服务器IP: " SERVER_IP

if [ -z "$SERVER_IP" ]; then
    echo "❌ 错误：服务器IP不能为空"
    exit 1
fi

echo ""
echo "📦 Step 1/6: 压缩文件..."
cd /Users/mac-bauyu/Downloads/10-23-bot

# 删除旧的压缩包
rm -f v8.4.5_update.tar.gz

tar -czf v8.4.5_update.tar.gz \
    ds/backtest_optimizer_v8321.py \
    ds/qwen_多币种智能版.py \
    ds/deepseek_多币种智能版.py

if [ $? -eq 0 ]; then
    echo "✅ 压缩成功"
    ls -lh v8.4.5_update.tar.gz
else
    echo "❌ 压缩失败"
    exit 1
fi

echo ""
echo "📤 Step 2/6: 上传到服务器..."
scp v8.4.5_update.tar.gz root@$SERVER_IP:~/

if [ $? -eq 0 ]; then
    echo "✅ 上传成功"
else
    echo "❌ 上传失败"
    exit 1
fi

echo ""
echo "🛑 Step 3/6: 停止正在运行的进程..."
ssh root@$SERVER_IP << 'ENDSSH'
echo "检查并停止qwen和deepseek进程..."
pkill -f "qwen_多币种智能版.py" || echo "  qwen进程未运行"
pkill -f "deepseek_多币种智能版.py" || echo "  deepseek进程未运行"
sleep 2
echo "✅ 进程已停止"
ENDSSH

echo ""
echo "💾 Step 4/6: 备份旧版本..."
ssh root@$SERVER_IP << 'ENDSSH'
cd ~/10-23-bot
BACKUP_TIME=$(date +%Y%m%d_%H%M%S)
if [ -f ds/backtest_optimizer_v8321.py ]; then
    cp ds/backtest_optimizer_v8321.py ds/backtest_optimizer_v8321.py.backup_$BACKUP_TIME
    echo "✅ 备份: backtest_optimizer_v8321.py"
fi
if [ -f ds/qwen_多币种智能版.py ]; then
    cp ds/qwen_多币种智能版.py ds/qwen_多币种智能版.py.backup_$BACKUP_TIME
    echo "✅ 备份: qwen_多币种智能版.py"
fi
if [ -f ds/deepseek_多币种智能版.py ]; then
    cp ds/deepseek_多币种智能版.py ds/deepseek_多币种智能版.py.backup_$BACKUP_TIME
    echo "✅ 备份: deepseek_多币种智能版.py"
fi
ENDSSH

echo ""
echo "📂 Step 5/6: 解压并覆盖文件..."
ssh root@$SERVER_IP << 'ENDSSH'
cd ~/10-23-bot
tar -xzf ~/v8.4.5_update.tar.gz
if [ $? -eq 0 ]; then
    echo "✅ 解压成功"
    rm ~/v8.4.5_update.tar.gz
    echo "✅ 清理压缩包"
else
    echo "❌ 解压失败"
    exit 1
fi
ENDSSH

echo ""
echo "🔍 Step 6/6: 验证更新..."
ssh root@$SERVER_IP << 'ENDSSH'
cd ~/10-23-bot
echo ""
echo "检查文件大小和修改时间："
ls -lh ds/backtest_optimizer_v8321.py
ls -lh ds/qwen_多币种智能版.py
ls -lh ds/deepseek_多币种智能版.py
echo ""
echo "验证V8.4.5标记："
if grep -q "V8.4.5" ds/qwen_多币种智能版.py; then
    echo "✅ qwen文件包含V8.4.5标记"
else
    echo "❌ qwen文件不包含V8.4.5标记（可能更新失败）"
fi
if grep -q "V8.4.5" ds/deepseek_多币种智能版.py; then
    echo "✅ deepseek文件包含V8.4.5标记"
else
    echo "❌ deepseek文件不包含V8.4.5标记（可能更新失败）"
fi
if grep -q "test_params_on_opportunities" ds/backtest_optimizer_v8321.py; then
    echo "✅ backtest_optimizer包含test_params_on_opportunities函数"
else
    echo "❌ backtest_optimizer不包含test_params_on_opportunities函数（可能更新失败）"
fi
ENDSSH

echo ""
echo "========================================="
echo "✅ V8.4.5 强制更新完成！"
echo "========================================="
echo ""
echo "🚀 现在可以运行回测："
echo ""
echo "ssh root@$SERVER_IP"
echo "cd ~/10-23-bot"
echo "bash ~/快速重启_修复版.sh backtest"
echo ""
echo "========================================="
echo "📋 观察以下日志确认V8.4.5正常运行："
echo ""
echo "1. 标题应显示：【第4.6步：分离策略优化（V8.3.12→V8.4.5）】"
echo "2. 应看到：【V8.4.5前向验证】"
echo "3. 应看到：📊 智能采样统计"
echo "4. 应看到：🔍 【V8.4.5前向验证】在验证期测试..."
echo ""
echo "========================================="

# 清理本地压缩包
rm -f /Users/mac-bauyu/Downloads/10-23-bot/v8.4.5_update.tar.gz
echo "✅ 已清理本地压缩包"
echo ""

