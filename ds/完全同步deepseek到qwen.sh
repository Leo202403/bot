#!/bin/bash
# 完全同步deepseek到qwen，只保留必要的配置差异

set -e  # 遇到错误立即退出

echo "🔄 开始完全同步 deepseek → qwen"
echo ""

# 1. 备份qwen
echo "📦 Step 1: 备份qwen..."
cp qwen_多币种智能版.py qwen_backup_full_sync_$(date +%Y%m%d_%H%M%S).py
echo "✅ 已备份"
echo ""

# 2. 复制deepseek到qwen
echo "📋 Step 2: 复制deepseek完整内容到qwen..."
cp deepseek_多币种智能版.py qwen_多币种智能版.py
echo "✅ 已复制"
echo ""

# 3. 替换配置（按顺序，从最具体到最通用）
echo "🔧 Step 3: 替换qwen专属配置..."

# 3.1 API Client初始化（最关键，需要精确替换）
echo "  → 3.1 替换API初始化..."
sed -i '' 's/deepseek_api_key = os\.getenv("DEEPSEEK_API_KEY")/qwen_api_key = os.getenv("QWEN_API_KEY")/g' qwen_多币种智能版.py
sed -i '' 's/DEEPSEEK_API_KEY/QWEN_API_KEY/g' qwen_多币种智能版.py
sed -i '' 's/deepseek_api_key/qwen_api_key/g' qwen_多币种智能版.py

# 替换base_url
sed -i '' 's|https://api\.deepseek\.com|https://dashscope.aliyuncs.com/compatible-mode/v1|g' qwen_多币种智能版.py

# 3.2 Client变量名
echo "  → 3.2 替换client变量名..."
sed -i '' 's/deepseek_client/qwen_client/g' qwen_多币种智能版.py

# 3.3 模型名称
echo "  → 3.3 替换模型名称..."
sed -i '' 's/"deepseek-chat"/"qwen-plus"/g' qwen_多币种智能版.py
sed -i '' 's/"deepseek-reasoner"/"qwen-max"/g' qwen_多币种智能版.py
sed -i '' "s/'deepseek-chat'/'qwen-plus'/g" qwen_多币种智能版.py
sed -i '' "s/'deepseek-reasoner'/'qwen-max'/g" qwen_多币种智能版.py

# 3.4 配置文件路径
echo "  → 3.4 替换配置路径..."
sed -i '' 's|trading_data/deepseek/|trading_data/qwen/|g' qwen_多币种智能版.py
sed -i '' 's|trading_data/deepseek|trading_data/qwen|g' qwen_多币种智能版.py

# 3.5 邮件标识
echo "  → 3.5 替换邮件标识..."
sed -i '' 's/\[DeepSeek\]/[通义千问]/g' qwen_多币种智能版.py
sed -i '' 's/\[深度求索\]/[通义千问]/g' qwen_多币种智能版.py
sed -i '' 's/DeepSeek智能交易系统/通义千问智能交易系统/g' qwen_多币种智能版.py
sed -i '' 's/deepseek 智能交易系统/qwen 智能交易系统/g' qwen_多币种智能版.py

# 3.6 Bark推送标识（保留一些DeepSeek在注释中）
echo "  → 3.6 替换Bark标识..."
# 只替换实际推送内容，不替换注释
sed -i '' 's/title.*=.*"\[DeepSeek\]/title = "[通义千问]/g' qwen_多币种智能版.py
sed -i '' 's/title.*=.*"\[深度求索\]/title = "[通义千问]/g' qwen_多币种智能版.py

# 3.7 打印输出标识
echo "  → 3.7 替换打印标识..."
# 替换实际输出，保留代码注释中的说明
sed -i '' 's/print.*"DeepSeek/print("Qwen/g' qwen_多币种智能版.py
sed -i '' 's/print.*".*深度求索/print("通义千问/g' qwen_多币种智能版.py

# 3.8 替换.env文件路径（qwen专用）
echo "  → 3.8 替换.env文件路径..."
sed -i '' "s|'.env'|'.env.qwen'|g" qwen_多币种智能版.py
sed -i '' 's|"\.env"|".env.qwen"|g' qwen_多币种智能版.py
sed -i '' 's|找不到 \.env 文件|找不到 .env.qwen 文件|g' qwen_多币种智能版.py
sed -i '' 's|明确指定 \.env 文件路径|明确指定 .env.qwen 文件路径|g' qwen_多币种智能版.py
sed -i '' 's|请检查 \.env 文件|请检查 .env.qwen 文件|g' qwen_多币种智能版.py

# 3.9 替换qwen-max为qwen3-max（qwen专用）
echo "  → 3.9 替换模型为qwen3-max..."
sed -i '' 's/"qwen-max"/"qwen3-max"/g' qwen_多币种智能版.py
sed -i '' "s/'qwen-max'/'qwen3-max'/g" qwen_多币种智能版.py

echo "✅ 配置替换完成"
echo ""

# 4. 验证
echo "📊 Step 4: 验证替换结果..."
echo ""

echo "【验证1】qwen_client数量:"
grep -c "qwen_client" qwen_多币种智能版.py || echo "0"

echo "【验证2】qwen-plus/qwen3-max数量:"
echo "  qwen-plus: $(grep -c 'qwen-plus' qwen_多币种智能版.py || echo '0')"
echo "  qwen3-max: $(grep -c 'qwen3-max' qwen_多币种智能版.py || echo '0')"

echo "【验证3】trading_data/qwen路径:"
grep -c "trading_data/qwen" qwen_多币种智能版.py || echo "0"

echo "【验证4】通义千问标识:"
grep -c "通义千问" qwen_多币种智能版.py || echo "0"

echo "【验证5】.env.qwen配置:"
grep -c "\.env\.qwen" qwen_多币种智能版.py || echo "0"

echo ""
echo "【验证6】检查残留的deepseek（应为0或很少）:"
grep -i "deepseek" qwen_多币种智能版.py | grep -v "^#" | grep -v "# " | grep -v "说明" | grep -v "注释" | wc -l

echo ""

# 5. 语法验证
echo "🔍 Step 5: Python语法验证..."
if python3 -m py_compile qwen_多币种智能版.py 2>&1; then
    echo "✅ 语法验证通过"
else
    echo "❌ 语法验证失败，请检查"
    exit 1
fi

echo ""
echo "📏 Step 6: 文件行数对比..."
echo "deepseek: $(wc -l < deepseek_多币种智能版.py) 行"
echo "qwen:     $(wc -l < qwen_多币种智能版.py) 行"
echo ""

echo "✅ 完全同步完成！"
echo ""
echo "📝 后续步骤:"
echo "1. 检查 qwen_多币种智能版.py 确认配置正确"
echo "2. 运行: git diff qwen_多币种智能版.py | head -100"
echo "3. 如果满意，提交: git add qwen_多币种智能版.py && git commit -m '🔄 完全同步deepseek到qwen'"
echo ""

