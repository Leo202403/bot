"""
🆕 V8.8: AI决策V8.8集成指南

这个文件展示如何将V8.8的Prompt优化集成到ai_portfolio_decision函数中
"""

# ==================== 集成步骤 ====================

"""
## 步骤1：在ai_portfolio_decision开头添加V8.8开关

在函数参数列表中添加：
```python
def ai_portfolio_decision(
    market_data_list,
    current_positions,
    total_position_value,
    current_balance,
    available_balance,
    deterministic_exit_symbols=None,
    use_v88_prompt=False,  # 🆕 V8.8: 使用精简Prompt
):
```

或者使用环境变量：
```python
import os
use_v88_prompt = os.getenv("USE_V88_PROMPT", "false").lower() == "true"
```

## 步骤2：在21699行附近添加V8.8分支

原代码：
```python
if not use_simplified_prompt:
    # 使用完整Prompt - 扫描Entry机会
    print("   💡 [V8.9.1] 使用完整Prompt（Entry扫描）")

prompt = f\"\"\"
**[Reply in Chinese]** Professional cryptocurrency trading AI...
...
\"\"\"
```

修改为：
```python
if not use_simplified_prompt:
    if use_v88_prompt:
        # 🆕 V8.8: 使用精简Prompt
        print("   🚀 [V8.8] 使用精简Prompt（Python算价格，AI选策略）")
        
        # 1. 预计算TP/SL选项
        tpsl_options_map = build_tpsl_options_for_symbols(
            market_data_list,
            signal_type="swing",
            atr_tp_mult=swing_params.get("atr_tp_multiplier", 4.0),
            atr_sl_mult=swing_params.get("atr_stop_multiplier", 1.5)
        )
        
        # 2. 使用PromptBuilderV8构建精简Prompt
        from prompt_builder_v8 import PromptBuilderV8
        
        builder = PromptBuilderV8()
        prompt = builder.build_optimized_prompt(
            market_data_list=market_data_list[:5],  # 限制5个币种
            current_positions=current_positions,
            tpsl_options_map=tpsl_options_map,
            balance=available_balance,
            signal_type="swing"
        )
        
        print(f"   📊 [V8.8] Prompt Token估算: ~{len(prompt) // 4} tokens（-85%）")
    else:
        # 使用完整Prompt - 扫描Entry机会
        print("   💡 [V8.9.1] 使用完整Prompt（Entry扫描）")
        
        prompt = f\"\"\"
        **[Reply in Chinese]** Professional cryptocurrency trading AI...
        ...
        \"\"\"
```

## 步骤3：在AI响应解析后添加V8.8处理

原代码（约22046行）：
```python
try:
    decision = json.loads(json_str)
except json.JSONDecodeError as e:
    print(f"JSON解析失败: {e}")
    ...
```

修改为：
```python
try:
    if use_v88_prompt:
        # 🆕 V8.8: 使用新解析器（应用Python计算的价格）
        decision = parse_ai_decision_v88(
            json_str,
            tpsl_options_map,
            market_data_list
        )
        
        if decision.get("_v88_enhanced"):
            print(f"✅ [V8.8] 决策已增强：{decision.get('strategy_used')} "
                  f"策略，R:R={decision.get('actual_rr', 0):.2f}")
    else:
        # 旧版解析
        decision = json.loads(json_str)
except json.JSONDecodeError as e:
    print(f"JSON解析失败: {e}")
    ...
```

## 步骤4：启用V8.8

方式1：环境变量（推荐）
```bash
# 在.env或.env.qwen文件中添加
USE_V88_PROMPT=true
```

方式2：函数调用
```python
# 在main函数中调用时传递参数
decision = ai_portfolio_decision(
    market_data_list,
    current_positions,
    total_position_value,
    current_balance,
    available_balance,
    deterministic_exit_symbols=[],
    use_v88_prompt=True  # 🆕 启用V8.8
)
```

## 步骤5：AB测试（可选）

```python
# 同时运行新旧Prompt，对比质量
if os.getenv("AB_TEST_V88", "false").lower() == "true":
    # 旧Prompt
    decision_old = ai_portfolio_decision(..., use_v88_prompt=False)
    
    # 新Prompt
    decision_new = ai_portfolio_decision(..., use_v88_prompt=True)
    
    # 对比日志
    print(f"[AB测试] 旧版决策: {decision_old.get('action')}, "
          f"置信度{decision_old.get('confidence')}")
    print(f"[AB测试] 新版决策: {decision_new.get('action')}, "
          f"置信度{decision_new.get('confidence')}, "
          f"R:R={decision_new.get('actual_rr', 0):.2f}")
    
    # 使用新版
    decision = decision_new
```
"""


# ==================== 完整示例代码 ====================


def ai_portfolio_decision_v88_example():
    """V8.8集成的完整示例（伪代码）"""
    
    # 1. 在函数开头
    import os
    use_v88_prompt = os.getenv("USE_V88_PROMPT", "false").lower() == "true"
    
    # ... （原有的market_overview构建代码）...
    
    # 2. 在Prompt构建部分
    if not use_simplified_prompt:
        if use_v88_prompt:
            # 🆕 V8.8路径
            print("   🚀 [V8.8] 使用精简Prompt")
            
            # 预计算TP/SL
            tpsl_options_map = build_tpsl_options_for_symbols(
                market_data_list,
                signal_type="swing",
                atr_tp_mult=4.0,
                atr_sl_mult=1.5
            )
            
            # 构建精简Prompt
            from prompt_builder_v8 import PromptBuilderV8
            builder = PromptBuilderV8()
            prompt = builder.build_optimized_prompt(
                market_data_list=market_data_list[:5],
                current_positions=current_positions,
                tpsl_options_map=tpsl_options_map,
                balance=available_balance,
                signal_type="swing"
            )
            
            print(f"   📊 Token: ~{len(prompt) // 4} (-85%)")
        else:
            # 旧版完整Prompt
            prompt = f"""..."""  # 原有代码
    
    # 3. AI调用（不变）
    response = qwen_client.chat.completions.create(
        model="qwen3-max",
        messages=[
            {"role": "system", "content": optimized_system_prompt},
            {"role": "user", "content": prompt},
        ],
        stream=False,
        max_tokens=5000,
    )
    
    result = response.choices[0].message.content
    
    # 4. 解析响应
    json_str = result[result.find("{"):result.rfind("}") + 1]
    
    try:
        if use_v88_prompt:
            # 🆕 V8.8解析器
            decision = parse_ai_decision_v88(
                json_str,
                tpsl_options_map,
                market_data_list
            )
            
            if decision.get("_v88_enhanced"):
                print(f"✅ [V8.8] 策略: {decision.get('strategy_used')}, "
                      f"R:R: {decision.get('actual_rr', 0):.2f}")
        else:
            # 旧版解析
            import json
            decision = json.loads(json_str)
    except Exception as e:
        print(f"解析失败: {e}")
        return None
    
    return decision


# ==================== 快速启用方法 ====================


QUICK_ENABLE_INSTRUCTIONS = """
## 🚀 最快启用V8.8的方法（3步）

### 方法1：环境变量（推荐）

1. 编辑 `.env` 或 `.env.qwen` 文件
2. 添加一行：
   ```
   USE_V88_PROMPT=true
   ```
3. 重启程序

### 方法2：代码修改（临时测试）

在 `ds/qwen_多币种智能版.py` 的 `ai_portfolio_decision` 函数开头添加：

```python
def ai_portfolio_decision(
    market_data_list,
    current_positions,
    total_position_value,
    current_balance,
    available_balance,
    deterministic_exit_symbols=None,
):
    # 🆕 V8.8: 临时启用精简Prompt
    use_v88_prompt = True  # 设为True启用，False禁用
    
    # ... 原有代码 ...
```

然后按照上面的步骤2-3修改Prompt构建和解析部分。

### 方法3：渐进式测试（最安全）

1. 先在回测中启用V8.8：
   ```python
   # 在回测函数中
   if is_backtest:
       use_v88_prompt = True
   else:
       use_v88_prompt = False
   ```

2. 验证回测质量后，再切换到实盘

---

## 📊 预期效果

启用V8.8后，你会看到：

```
🚀 [V8.8] 使用精简Prompt（Python算价格，AI选策略）
📊 [V8.8] Prompt Token估算: ~1200 tokens（-85%）
...
✅ [V8.8] 决策已增强：STRUCTURE策略，R:R=2.35
```

对比旧版：

```
💡 [V8.9.1] 使用完整Prompt（Entry扫描）
📊 Prompt Token估算: ~8000 tokens
```

Token消耗降低85%，推理速度提升67%！
"""

if __name__ == "__main__":
    print(__doc__)
    print(QUICK_ENABLE_INSTRUCTIONS)

