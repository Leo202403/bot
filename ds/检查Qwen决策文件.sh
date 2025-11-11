#!/bin/bash

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "检查 Qwen AI 决策文件"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

QWEN_DECISIONS="/root/10-23-bot/ds/trading_data/qwen/ai_decisions.json"
DS_DECISIONS="/root/10-23-bot/ds/trading_data/deepseek/ai_decisions.json"

echo "=== 1. 检查文件是否存在 ==="
echo "Qwen 决策文件:"
ls -lh "$QWEN_DECISIONS" 2>/dev/null || echo "❌ 文件不存在"

echo ""
echo "DeepSeek 决策文件:"
ls -lh "$DS_DECISIONS" 2>/dev/null || echo "❌ 文件不存在"

echo ""
echo "=== 2. 检查 Qwen 文件格式和结构 ==="
if [ -f "$QWEN_DECISIONS" ]; then
    echo "文件大小: $(wc -c < "$QWEN_DECISIONS") 字节"
    echo "行数: $(wc -l < "$QWEN_DECISIONS") 行"
    echo ""
    
    echo "--- 文件开头 (前 30 行) ---"
    head -30 "$QWEN_DECISIONS"
    echo ""
    
    echo "--- 文件结尾 (后 30 行) ---"
    tail -30 "$QWEN_DECISIONS"
    echo ""
    
    echo "=== 3. 检查 JSON 格式是否有效 ==="
    python3 << 'PYEOF'
import json
import sys

try:
    with open('/root/10-23-bot/ds/trading_data/qwen/ai_decisions.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
        print(f"✅ JSON 格式有效")
        print(f"数据类型: {type(data)}")
        
        if isinstance(data, list):
            print(f"决策数量: {len(data)} 条")
            if len(data) > 0:
                print(f"\n最新一条决策的字段:")
                latest = data[-1]
                for key in latest.keys():
                    print(f"  - {key}")
                    
                print(f"\n最新决策内容预览:")
                print(f"  时间: {latest.get('时间', 'N/A')}")
                print(f"  决策: {latest.get('决策', 'N/A')[:100]}...")
        elif isinstance(data, dict):
            print(f"⚠️  数据是字典，不是列表！")
            print(f"字典的键: {list(data.keys())}")
        else:
            print(f"⚠️  数据类型异常: {type(data)}")
            
except json.JSONDecodeError as e:
    print(f"❌ JSON 格式错误: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ 读取失败: {e}")
    sys.exit(1)
PYEOF

else
    echo "❌ Qwen 决策文件不存在，无法检查"
fi

echo ""
echo "=== 4. 对比 DeepSeek 文件格式 ==="
if [ -f "$DS_DECISIONS" ]; then
    echo "DeepSeek 文件大小: $(wc -c < "$DS_DECISIONS") 字节"
    echo "DeepSeek 行数: $(wc -l < "$DS_DECISIONS") 行"
    echo ""
    
    echo "--- DeepSeek 文件结尾 (后 20 行) ---"
    tail -20 "$DS_DECISIONS"
    echo ""
    
    python3 << 'PYEOF'
import json

try:
    with open('/root/10-23-bot/ds/trading_data/deepseek/ai_decisions.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
        print(f"✅ DeepSeek JSON 格式有效")
        print(f"数据类型: {type(data)}")
        
        if isinstance(data, list):
            print(f"决策数量: {len(data)} 条")
            if len(data) > 0:
                latest = data[-1]
                print(f"\nDeepSeek 最新决策字段:")
                for key in latest.keys():
                    print(f"  - {key}")
except Exception as e:
    print(f"❌ DeepSeek 读取失败: {e}")
PYEOF
else
    echo "❌ DeepSeek 决策文件不存在"
fi

echo ""
echo "=== 5. 检查文件权限 ==="
ls -la /root/10-23-bot/ds/trading_data/qwen/ 2>/dev/null | grep -E "ai_decisions|system_status"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
