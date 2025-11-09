#!/usr/bin/env python3
"""
快速应用V8.3.18修改
精确替换optimize_scalping_params函数
"""

# 读取文件
with open('deepseek_多币种智能版.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 找到关键行号
calc_scalping_line = None
optimize_scalping_line = None
optimize_swing_line = None

for i, line in enumerate(lines):
    if line.startswith('def calculate_scalping_optimization_score'):
        calc_scalping_line = i
    elif line.startswith('def optimize_scalping_params'):
        optimize_scalping_line = i
    elif line.startswith('def optimize_swing_params'):
        optimize_swing_line = i

print(f"✓ calculate_scalping_optimization_score: 行{calc_scalping_line + 1}")
print(f"✓ optimize_scalping_params: 行{optimize_scalping_line + 1}")
print(f"✓ optimize_swing_params: 行{optimize_swing_line + 1}")

# 找到calculate_scalping_optimization_score函数的结束位置（return语句后的空行）
insert_position = calc_scalping_line
for i in range(calc_scalping_line, optimize_scalping_line):
    if lines[i].strip().startswith('return ') and i + 2 < len(lines) and lines[i+1].strip() == '' and lines[i+2].strip() == '':
        insert_position = i + 2
        break

print(f"✓ 辅助函数插入位置: 行{insert_position + 1}")

# 准备3个辅助函数
helper_functions = '''
def generate_round1_combinations():
    """
    【V8.3.18】生成第1轮Grid Search的测试组合
    
    使用V8.3.17的分层采样策略：34组参数
    """
    test_combinations = []
    
    # 【策略1】高质量低数量（信号分85，严格TP/SL）- 4组
    for tp in [0.8, 1.2]:
        for time_h in [1.0, 1.5]:
            test_combinations.append({
                'max_holding_hours': time_h,
                'atr_tp_multiplier': tp,
                'atr_stop_multiplier': 1.0,
                'min_risk_reward': 2.5,
                'min_signal_score': 85
            })
    
    # 【策略2】中等质量中等数量（信号分75，平衡TP/SL）- 18组
    for tp in [0.5, 0.8, 1.2]:
        for sl in [0.8, 1.0]:
            for time_h in [0.5, 1.0, 1.5]:
                test_combinations.append({
                    'max_holding_hours': time_h,
                    'atr_tp_multiplier': tp,
                    'atr_stop_multiplier': sl,
                    'min_risk_reward': 2.0,
                    'min_signal_score': 75
                })
    
    # 【策略3】低质量高数量（信号分65，宽松TP/SL）- 4组
    for tp in [0.5, 0.8]:
        for time_h in [0.5, 1.0]:
            test_combinations.append({
                'max_holding_hours': time_h,
                'atr_tp_multiplier': tp,
                'atr_stop_multiplier': 0.8,
                'min_risk_reward': 1.5,
                'min_signal_score': 65
            })
    
    # 补充边界情况 - 8组
    for rr in [1.5, 2.0]:
        for score in [70, 80]:
            for tp in [0.6, 1.0]:
                test_combinations.append({
                    'max_holding_hours': 1.0,
                    'atr_tp_multiplier': tp,
                    'atr_stop_multiplier': 0.9,
                    'min_risk_reward': rr,
                    'min_signal_score': score
                })
    
    return test_combinations  # 总计34组


def generate_round2_combinations_from_ai(ai_suggestions):
    """
    【V8.3.18】根据AI建议生成第2轮测试组合
    """
    param_ranges = ai_suggestions.get('param_ranges', {})
    
    if not param_ranges:
        param_ranges = {
            'atr_tp_multiplier': [0.3, 0.4, 0.5],
            'max_holding_hours': [1.5, 2.0, 2.5],
            'min_signal_score': [70, 80, 90],
            'atr_stop_multiplier': [0.6, 0.8],
            'min_risk_reward': [1.8, 2.2]
        }
    
    test_combinations = []
    from itertools import product
    
    keys = list(param_ranges.keys())
    values = [param_ranges[k] for k in keys]
    
    for combo_values in product(*values):
        combination = dict(zip(keys, combo_values))
        test_combinations.append(combination)
    
    if len(test_combinations) > 50:
        import random
        random.shuffle(test_combinations)
        test_combinations = test_combinations[:50]
    
    return test_combinations


def call_ai_for_round_decision(round_num, round_results, current_best_params, opportunities_count):
    """
    【V8.3.18】调用AI分析当前轮次结果并决策
    """
    best_result = round_results[0] if round_results else None
    
    prompt = f"""You are a quantitative trading strategy optimization expert.

【Current Status】
- Round: {round_num} of Grid Search
- Opportunities: {opportunities_count} scalping opportunities
- Tested Combinations: {len(round_results)} parameter sets

【Round {round_num} Best Result】
Parameters: {json.dumps(best_result['params'], ensure_ascii=False) if best_result else 'None'}
"""
    
    if best_result:
        result = best_result['result']
        te_rate = result['time_exit_count']/result['captured_count']*100 if result['captured_count'] > 0 else 100
        prompt += f"""Performance: time_exit={te_rate:.0f}%, avg_profit={result['avg_profit']:.1f}%, captured={result['captured_count']}, score={best_result['score']:.4f}

【Top 5 Comparison】
"""
        for i, res in enumerate(round_results[:5], 1):
            p = res['params']
            r = res['result']
            te = r['time_exit_count']/r['captured_count']*100 if r['captured_count'] > 0 else 100
            prompt += f"#{i}. signal{p['min_signal_score']} TP{p['atr_tp_multiplier']}× hold{p['max_holding_hours']}h → te={te:.0f}% profit={r['avg_profit']:.1f}% score={res['score']:.4f}\\n"
    
    if round_num == 1:
        prompt += """
【Task】Should we run Round 2?

Context:
- If Round 1 already found acceptable parameters (time_exit<80% OR avg_profit>0.5%), you can skip Round 2
- If ALL combinations have time_exit=100%, we MUST try more aggressive parameters in Round 2

Respond in JSON format ONLY:
{
  "needs_round2": true/false,
  "reasoning": "Your analysis",
  "round2_suggestions": {
    "strategy": "Brief description",
    "param_ranges": {
      "atr_tp_multiplier": [0.3, 0.4, 0.5],
      "max_holding_hours": [1.5, 2.0, 2.5],
      "min_signal_score": [70, 80, 90],
      "atr_stop_multiplier": [0.6, 0.8],
      "min_risk_reward": [1.8, 2.2]
    }
  },
  "final_decision": {
    "accept_result": true,
    "selected_params": {...},
    "execution_strategy": "apply_immediately"
  }
}"""
    else:
        prompt += """
【Task】Make the FINAL decision

Respond in JSON format ONLY:
{
  "final_decision": {
    "accept_result": true/false,
    "selected_params": {...},
    "reasoning": "Why these parameters?",
    "execution_strategy": "apply_immediately",
    "monitoring_metrics": ["profit_loss_ratio", "time_exit_rate"],
    "rollback_conditions": "7-day P/L ratio <1.2"
  }
}"""
    
    try:
        response = requests.post(
            deepseek_base_url + "/chat/completions",
            headers={"Authorization": f"Bearer {deepseek_api_key}"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 2000
            },
            timeout=60
        )
        
        if response.status_code == 200:
            ai_text = response.json()['choices'][0]['message']['content'].strip()
            if '```json' in ai_text:
                ai_text = ai_text.split('```json')[1].split('```')[0].strip()
            elif '```' in ai_text:
                ai_text = ai_text.split('```')[1].split('```')[0].strip()
            return json.loads(ai_text)
        else:
            print(f"     ⚠️  AI调用失败: {response.status_code}")
            return {"needs_round2": False, "final_decision": {"accept_result": True, "selected_params": current_best_params}}
    except Exception as e:
        print(f"     ⚠️  AI决策异常: {e}")
        return {"needs_round2": False, "final_decision": {"accept_result": True, "selected_params": current_best_params}}


'''

# 插入辅助函数
new_lines = lines[:insert_position] + [helper_functions] + lines[insert_position:]

# 重新定位optimize_scalping_params和optimize_swing_params
optimize_scalping_line = None
optimize_swing_line = None
for i, line in enumerate(new_lines):
    if isinstance(line, str) and line.startswith('def optimize_scalping_params'):
        optimize_scalping_line = i
    elif isinstance(line, str) and line.startswith('def optimize_swing_params'):
        optimize_swing_line = i

print(f"✓ 重新定位 optimize_scalping_params: 行{optimize_scalping_line + 1}")
print(f"✓ 重新定位 optimize_swing_params: 行{optimize_swing_line + 1}")

# 读取新的主逻辑
with open('V8.3.18_new_optimize_scalping_main_logic.py', 'r', encoding='utf-8') as f:
    new_logic_lines = f.readlines()[3:]  # 跳过前3行注释

# 构建新的optimize_scalping_params函数
new_function_lines = []

# 1. 函数签名和docstring（保留到opportunities检查部分）
for i in range(optimize_scalping_line, optimize_scalping_line + 30):
    line = new_lines[i]
    if 'print(f"  🔧 开始超短线参数优化' in line:
        break
    new_function_lines.append(line)

# 2. 新的主逻辑
new_function_lines.extend(new_logic_lines)

# 3. 添加换行
new_function_lines.append('\n\n')

# 组合最终文件
final_lines = (
    new_lines[:optimize_scalping_line] +
    new_function_lines +
    new_lines[optimize_swing_line:]
)

# 写入文件
with open('deepseek_多币种智能版.py', 'w', encoding='utf-8') as f:
    f.writelines(final_lines)

print("\n✅ V8.3.18应用完成！")
print(f"   - 插入了3个辅助函数")
print(f"   - 替换了optimize_scalping_params主逻辑")
print(f"   - optimize_swing_params未被影响")

