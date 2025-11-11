#!/bin/bash

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "修复 Qwen AI 决策文件"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

QWEN_DIR="/root/10-23-bot/ds/trading_data/qwen"
DECISIONS_FILE="$QWEN_DIR/ai_decisions.json"
BACKUP_FILE="$DECISIONS_FILE.backup_$(date +%Y%m%d_%H%M%S)"

cd "$QWEN_DIR" || exit 1

echo "=== 1. 备份当前文件 ==="
cp "$DECISIONS_FILE" "$BACKUP_FILE"
echo "✅ 已备份到: $BACKUP_FILE"
echo ""

echo "=== 2. 尝试自动修复 JSON ==="
python3 << 'PYEOF'
import json
import sys

input_file = '/root/10-23-bot/ds/trading_data/qwen/ai_decisions.json'
output_file = '/root/10-23-bot/ds/trading_data/qwen/ai_decisions_fixed.json'

try:
    # 读取原始文件内容
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    print(f"📊 原始文件大小: {len(content)} 字符")
    
    # 尝试找到第一个完整的 JSON 数组结束符
    # 从错误位置往前找最后一个正常的 }]
    
    # 方法1: 尝试逐步解析，找到最后一个有效的决策
    valid_decisions = []
    
    # 尝试手动解析
    lines = content.split('\n')
    temp_content = ''
    last_valid_pos = 0
    
    for i, line in enumerate(lines):
        temp_content += line + '\n'
        try:
            data = json.loads(temp_content)
            if isinstance(data, list):
                valid_decisions = data
                last_valid_pos = len(temp_content)
                print(f"✅ 第 {i+1} 行: 有效的 JSON（{len(valid_decisions)} 条决策）")
        except json.JSONDecodeError:
            # 继续尝试
            pass
    
    if valid_decisions:
        print(f"\n✅ 找到 {len(valid_decisions)} 条有效决策")
        print(f"📝 最后有效位置: {last_valid_pos} 字符")
        
        # 保存修复后的文件
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(valid_decisions, f, ensure_ascii=False, indent=2)
        
        print(f"✅ 已保存修复后的文件: {output_file}")
        print(f"📊 修复后文件大小: {last_valid_pos} 字符")
        
        # 显示最后一条决策的时间戳
        if valid_decisions:
            last_decision = valid_decisions[-1]
            print(f"⏰ 最后一条决策时间: {last_decision.get('timestamp', 'N/A')}")
        
        sys.exit(0)
    else:
        print("❌ 无法找到有效的决策数据")
        sys.exit(1)
        
except Exception as e:
    print(f"❌ 修复失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
PYEOF

if [ $? -eq 0 ]; then
    echo ""
    echo "=== 3. 替换原文件 ==="
    mv "$DECISIONS_FILE" "${DECISIONS_FILE}.broken"
    mv "${QWEN_DIR}/ai_decisions_fixed.json" "$DECISIONS_FILE"
    echo "✅ 已替换为修复后的文件"
    echo "🗑️  损坏的文件保存为: ${DECISIONS_FILE}.broken"
    echo ""
    
    echo "=== 4. 验证修复结果 ==="
    python3 << 'PYEOF'
import json

try:
    with open('/root/10-23-bot/ds/trading_data/qwen/ai_decisions.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
        print(f"✅ JSON 格式有效")
        print(f"📊 决策数量: {len(data)} 条")
        if data:
            print(f"⏰ 最新决策时间: {data[-1].get('timestamp', 'N/A')}")
            print(f"📋 最新决策字段: {list(data[-1].keys())}")
except Exception as e:
    print(f"❌ 验证失败: {e}")
PYEOF
    
    echo ""
    echo "=== 5. 重启 Qwen AI ==="
    supervisorctl restart qwen
    echo ""
    sleep 3
    supervisorctl status qwen
    
else
    echo ""
    echo "❌ 自动修复失败，尝试使用时区修复前的备份..."
    echo ""
    
    if [ -f "$QWEN_DIR/ai_decisions.json.bak_before_timezone_fix" ]; then
        echo "=== 使用时区修复前的备份 ==="
        cp "$QWEN_DIR/ai_decisions.json.bak_before_timezone_fix" "$DECISIONS_FILE"
        echo "✅ 已恢复备份文件"
        echo ""
        
        echo "=== 验证备份文件 ==="
        python3 << 'PYEOF'
import json

try:
    with open('/root/10-23-bot/ds/trading_data/qwen/ai_decisions.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
        print(f"✅ JSON 格式有效")
        print(f"📊 决策数量: {len(data)} 条")
        if data:
            print(f"⏰ 最新决策时间: {data[-1].get('timestamp', 'N/A')}")
except Exception as e:
    print(f"❌ 备份文件也损坏: {e}")
PYEOF
        
        echo ""
        echo "=== 重启 Qwen AI ==="
        supervisorctl restart qwen
        sleep 3
        supervisorctl status qwen
    else
        echo "❌ 未找到备份文件，需要手动修复或重新生成"
    fi
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 修复完成！"
echo ""
echo "📝 备份文件保存在:"
echo "   - $BACKUP_FILE"
echo "   - ${DECISIONS_FILE}.broken (如果修复成功)"
echo ""
echo "🌐 请刷新浏览器，检查 Qwen 决策是否正常显示"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
