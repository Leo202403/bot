#!/bin/bash
# 修复qwen中剩余的deepseek配置

echo "🔧 修复qwen剩余问题..."

# 1. 修复model_dir默认值
echo "  → 1. 修复model_dir默认值..."
sed -i '' 's/MODEL_NAME", "deepseek"/MODEL_NAME", "qwen"/g' qwen_多币种智能版.py

# 2. 修复DATA_DIR路径
echo "  → 2. 修复DATA_DIR路径..."
sed -i '' 's|"trading_data" / "deepseek"|"trading_data" / "qwen"|g' qwen_多币种智能版.py

# 3. 修复注释中的实际配置说明（保留技术说明中的DeepSeek）
echo "  → 3. 更新配置注释..."
sed -i '' 's/# 初始化DeepSeek客户端/# 初始化Qwen客户端/g' qwen_多币种智能版.py
sed -i '' 's/数据存储路径（DeepSeek专用目录）/数据存储路径（Qwen专用目录）/g' qwen_多币种智能版.py
sed -i '' 's/支持多个地址 + DeepSeek分组/支持多个地址 + Qwen分组/g' qwen_多币种智能版.py

# 4. 验证
echo ""
echo "📊 验证修复结果:"
echo "【model_dir默认值】:"
grep "MODEL_NAME.*qwen" qwen_多币种智能版.py | wc -l
echo "【DATA_DIR路径】:"
grep 'trading_data.*qwen' qwen_多币种智能版.py | wc -l
echo "【残留deepseek（注释除外）】:"
grep -i "deepseek" qwen_多币种智能版.py | grep -v "^#" | grep -v "说明\|注释\|Reasoner\|API\|支持DeepSeek\|从AI响应\|跳过DeepSeek" | wc -l

echo ""
echo "✅ 修复完成"
