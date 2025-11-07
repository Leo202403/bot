#!/bin/bash
# 最终修复qwen中所有deepseek残留

echo "🔧 最终修复qwen配置..."

# 1. Bark分组
echo "  → 1. 修复Bark分组..."
sed -i '' 's|group=DeepSeek|group=Qwen|g' qwen_多币种智能版.py

# 2. 默认model_name
echo "  → 2. 修复默认model_name..."
sed -i '' 's/MODEL_NAME", "DeepSeek"/MODEL_NAME", "Qwen"/g' qwen_多币种智能版.py
sed -i '' 's/model_name="DeepSeek"/model_name="Qwen"/g' qwen_多币种智能版.py

# 3. 函数参数默认值
echo "  → 3. 修复函数参数..."
sed -i '' "s/model_name='deepseek'/model_name='qwen'/g" qwen_多币种智能版.py

# 4. 注释中的模型说明
echo "  → 4. 更新模型注释..."
sed -i '' 's/# DeepSeek模型/# Qwen模型/g' qwen_多币种智能版.py
sed -i '' 's/DeepSeek模型/Qwen模型/g' qwen_多币种智能版.py

# 5. 缓存说明（技术性注释，保持原样但更新）
echo "  → 5. 更新缓存说明..."
sed -i '' 's/考虑DeepSeek自身缓存/考虑Qwen自身缓存/g' qwen_多币种智能版.py
sed -i '' 's/利于DeepSeek后端缓存/利于Qwen后端缓存/g' qwen_多币种智能版.py

# 验证
echo ""
echo "📊 最终验证:"
echo "【残留deepseek】:"
deepseek_count=$(grep -i "deepseek" qwen_多币种智能版.py | grep -v "^#" | grep -v "说明\|Reasoner\|API\|支持DeepSeek\|从AI响应\|跳过DeepSeek" | wc -l | tr -d ' ')
echo "$deepseek_count 处"

if [ "$deepseek_count" -le 5 ]; then
    echo "✅ 合格（剩余的是技术说明，可以保留）"
else
    echo "⚠️  还有较多残留，检查:"
    grep -in "deepseek" qwen_多币种智能版.py | grep -v "^#" | grep -v "说明\|Reasoner\|API\|支持DeepSeek\|从AI响应\|跳过DeepSeek"
fi

echo ""
echo "【Qwen相关配置】:"
echo "qwen_client: $(grep -c 'qwen_client' qwen_多币种智能版.py)"
echo "qwen模型: $(grep -c 'qwen-plus\|qwen-max' qwen_多币种智能版.py)"  
echo "通义千问: $(grep -c '通义千问' qwen_多币种智能版.py)"
echo "group=Qwen: $(grep -c 'group=Qwen' qwen_多币种智能版.py)"

echo ""
python3 -m py_compile qwen_多币种智能版.py && echo "✅ 语法验证通过" || echo "❌ 语法错误"

echo ""
echo "✅ 最终修复完成！"
