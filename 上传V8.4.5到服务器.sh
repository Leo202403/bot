#!/bin/bash

# V8.4.5 上传到服务器脚本

echo "========================================="
echo "V8.4.5 文件上传脚本"
echo "========================================="
echo ""

# 服务器IP（请修改为你的服务器IP）
SERVER_IP="YOUR_SERVER_IP"

# 检查服务器IP是否已设置
if [ "$SERVER_IP" = "YOUR_SERVER_IP" ]; then
    echo "❌ 错误：请先修改脚本中的SERVER_IP为实际服务器IP"
    echo ""
    echo "编辑命令："
    echo "nano ~/Downloads/10-23-bot/上传V8.4.5到服务器.sh"
    echo ""
    exit 1
fi

echo "📦 Step 1/5: 压缩文件..."
cd /Users/mac-bauyu/Downloads/10-23-bot
tar -czf v8.4.5_update.tar.gz \
    ds/backtest_optimizer_v8321.py \
    ds/qwen_多币种智能版.py \
    ds/deepseek_多币种智能版.py

if [ $? -eq 0 ]; then
    echo "✅ 压缩成功: v8.4.5_update.tar.gz"
    ls -lh v8.4.5_update.tar.gz
else
    echo "❌ 压缩失败"
    exit 1
fi

echo ""
echo "📤 Step 2/5: 上传到服务器..."
scp v8.4.5_update.tar.gz root@$SERVER_IP:~/10-23-bot/

if [ $? -eq 0 ]; then
    echo "✅ 上传成功"
else
    echo "❌ 上传失败"
    exit 1
fi

echo ""
echo "🔧 Step 3/5: 备份旧版本..."
ssh root@$SERVER_IP << 'ENDSSH'
cd ~/10-23-bot
if [ -f ds/backtest_optimizer_v8321.py ]; then
    cp ds/backtest_optimizer_v8321.py ds/backtest_optimizer_v8321.py.backup_$(date +%Y%m%d_%H%M%S)
    echo "✅ 备份: backtest_optimizer_v8321.py"
fi
if [ -f ds/qwen_多币种智能版.py ]; then
    cp ds/qwen_多币种智能版.py ds/qwen_多币种智能版.py.backup_$(date +%Y%m%d_%H%M%S)
    echo "✅ 备份: qwen_多币种智能版.py"
fi
if [ -f ds/deepseek_多币种智能版.py ]; then
    cp ds/deepseek_多币种智能版.py ds/deepseek_多币种智能版.py.backup_$(date +%Y%m%d_%H%M%S)
    echo "✅ 备份: deepseek_多币种智能版.py"
fi
ENDSSH

echo ""
echo "📂 Step 4/5: 解压文件..."
ssh root@$SERVER_IP << 'ENDSSH'
cd ~/10-23-bot
tar -xzf v8.4.5_update.tar.gz
if [ $? -eq 0 ]; then
    echo "✅ 解压成功"
    rm v8.4.5_update.tar.gz
    echo "✅ 清理压缩包"
else
    echo "❌ 解压失败"
    exit 1
fi
ENDSSH

echo ""
echo "🔍 Step 5/5: 验证文件..."
ssh root@$SERVER_IP << 'ENDSSH'
cd ~/10-23-bot
echo "检查文件大小："
ls -lh ds/backtest_optimizer_v8321.py
ls -lh ds/qwen_多币种智能版.py
ls -lh ds/deepseek_多币种智能版.py
ENDSSH

echo ""
echo "========================================="
echo "✅ V8.4.5 上传完成！"
echo "========================================="
echo ""
echo "🚀 现在可以运行回测："
echo ""
echo "ssh root@$SERVER_IP"
echo "cd ~/10-23-bot"
echo "bash ~/快速重启_修复版.sh backtest"
echo ""
echo "========================================="
echo "📋 观察以下日志确认正常运行："
echo ""
echo "1. 智能采样统计（边界+中心+随机）"
echo "2. 前向验证（训练期+验证期）"
echo "3. 验证期测试结果"
echo "4. 优化结果（捕获率+平均利润+time_exit率）"
echo ""
echo "========================================="

# 清理本地压缩包
rm -f /Users/mac-bauyu/Downloads/10-23-bot/v8.4.5_update.tar.gz
echo "✅ 已清理本地压缩包"
echo ""

