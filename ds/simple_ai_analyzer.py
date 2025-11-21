"""
【V8.5.2.4.87】简化版AI自我反思分析模块

核心功能：
1. 整理AI的3类决策（开仓、平仓、错过机会）
2. 发送给AI进行自我反思
3. 生成简洁的教训和改进建议
"""

import json
import os
from datetime import datetime
from openai import OpenAI


def generate_simple_ai_reflection(entry_analysis, exit_analysis, ai_decisions):
    """
    【V8.5.2.4.87】生成简化的AI自我反思分析
    
    Args:
        entry_analysis: dict, 开仓分析结果（来自analyze_entry_timing_v2）
        exit_analysis: dict, 平仓分析结果（来自analyze_exit_timing）
        ai_decisions: list, AI历史决策记录（包含开仓、平仓、跳过的决策）
    
    Returns:
        {
            'entry_lessons': ['教训1', '教训2'],
            'exit_lessons': ['教训1', '教训2'],
            'missed_lessons': ['教训1', '教训2'],
            'improvements': ['改进1', '改进2', '改进3'],
            'generated_at': str,
            'tokens_used': int,
            'cost_usd': float
        }
    """
    try:
        # 检测API配置
        # 【修复】兼容多种环境变量命名（服务器可能使用不同名称）
        deepseek_key = os.getenv('DEEPSEEK_API_KEY')
        qwen_key = os.getenv('QWEN_API_KEY') or os.getenv('DASHSCOPE_API_KEY')  # 兼容旧命名
        
        print(f"[调试] DEEPSEEK_API_KEY: {'✓ 存在' if deepseek_key else '✗ 不存在'}")
        print(f"[调试] QWEN_API_KEY: {'✓ 存在' if os.getenv('QWEN_API_KEY') else '✗ 不存在'}")
        print(f"[调试] DASHSCOPE_API_KEY: {'✓ 存在' if os.getenv('DASHSCOPE_API_KEY') else '✗ 不存在'}")
        
        if deepseek_key:
            api_key = deepseek_key.strip()
            base_url = "https://api.deepseek.com"
            model_name = "deepseek-chat"  # 修复：使用deepseek-chat（成本更低，效果足够，与entry_timing_analyzer保持一致）
            model_type = "DeepSeek"
        elif qwen_key:
            api_key = qwen_key.strip()
            base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
            model_name = "qwen-max"
            model_type = "Qwen"
        else:
            raise ValueError("未找到API密钥：请设置 DEEPSEEK_API_KEY 或 QWEN_API_KEY 环境变量")
        
        print(f"[AI Self-Reflection] 使用{model_type} API ({model_name})进行自我反思...")
        
        # 准备数据（限制数量避免超token）
        analysis_data = prepare_reflection_data(entry_analysis, exit_analysis, ai_decisions)
        
        # 【修复】控制prompt长度（deepseek-chat限制8k，需留足够response空间）
        # 限制每类决策数量
        analysis_data['open_decisions'] = analysis_data['open_decisions'][:5]  # 15→5
        analysis_data['close_decisions'] = analysis_data['close_decisions'][:5]  # 15→5
        analysis_data['skip_decisions'] = analysis_data['skip_decisions'][:5]  # 15→5
        
        # 构建prompt
        prompt = build_reflection_prompt(analysis_data)
        
        # 【调试】打印prompt长度
        prompt_chars = len(prompt)
        est_tokens = prompt_chars // 3  # 粗略估算
        print(f"[调试] Prompt长度: {prompt_chars}字符 (约{est_tokens} tokens)")
        
        # 调用AI
        client = OpenAI(api_key=api_key, base_url=base_url)
        
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {
                    "role": "system",
                    "content": "You are a trading AI performing self-reflection. Be honest, self-critical, and constructive. Output valid JSON only."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.3,
            max_tokens=2000  # 【修复】增加到2000（prompt已缩减，留足够输出空间）
        )
        
        # 解析结果
        # 【兼容】处理deepseek-reasoner的特殊格式（如果未来切回）
        message = response.choices[0].message
        result_text = ""
        
        # 优先使用reasoning_content（deepseek-reasoner）
        if hasattr(message, 'reasoning_content') and message.reasoning_content:
            result_text = message.reasoning_content.strip()
            print(f"[调试] 使用reasoning_content: {len(result_text)}字符")
        
        # 否则使用普通content（deepseek-chat, qwen）
        if not result_text and message.content:
            result_text = message.content.strip()
        
        # 【修复】检查是否为空
        if not result_text:
            print(f"[调试] response类型: {type(response)}")
            print(f"[调试] message字段: {dir(message)}")
            raise ValueError("AI返回空内容，可能是模型限制或网络问题")
        
        # 打印调试信息（前200字符）
        if len(result_text) < 50:  # 如果内容太短，打印完整内容
            print(f"[调试] AI响应: {result_text}")
        
        # 提取JSON
        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0].strip()
        elif "```" in result_text:
            result_text = result_text.split("```")[1].split("```")[0].strip()
        
        # 再次检查提取后的内容
        if not result_text:
            raise ValueError("提取JSON后为空，AI可能未返回有效JSON")
        
        ai_insights = json.loads(result_text)
        
        # 添加元数据
        ai_insights['generated_at'] = datetime.now().isoformat()
        ai_insights['tokens_used'] = response.usage.total_tokens
        ai_insights['cost_usd'] = response.usage.total_tokens * 0.001 / 1000  # DeepSeek定价
        
        print("[AI Self-Reflection] ✓ 生成完成")
        print(f"  Entry Lessons: {len(ai_insights.get('entry_lessons', []))}")
        print(f"  Exit Lessons: {len(ai_insights.get('exit_lessons', []))}")
        print(f"  Missed Lessons: {len(ai_insights.get('missed_lessons', []))}")
        print(f"  Improvements: {len(ai_insights.get('improvements', []))}")
        print(f"  Tokens: {ai_insights['tokens_used']}, Cost: ${ai_insights['cost_usd']:.6f}")
        
        return ai_insights
        
    except Exception as e:
        print(f"[AI Self-Reflection] ⚠️ 失败: {e}")
        import traceback
        traceback.print_exc()
        
        return {
            'entry_lessons': [],
            'exit_lessons': [],
            'missed_lessons': [],
            'improvements': [],
            'generated_at': datetime.now().isoformat(),
            'error': str(e)
        }


def prepare_reflection_data(entry_analysis, exit_analysis, ai_decisions):
    """
    准备AI自我反思所需的数据
    
    Returns:
        {
            'entry_summary': {...},
            'exit_summary': {...},
            'open_decisions': [...],  # 开仓决策
            'close_decisions': [...],  # 平仓决策
            'skip_decisions': [...]  # 错过的机会
        }
    """
    # 开仓总结
    entry_stats = entry_analysis.get('entry_stats', {}) if entry_analysis else {}
    entry_summary = {
        'total': entry_stats.get('ai_opened', 0),
        'correct': entry_stats.get('correct_entries', 0),
        'timing_issue': entry_stats.get('timing_issues', 0),
        'false_signal': entry_stats.get('false_entries', 0)
    }
    
    # 平仓总结
    exit_stats = exit_analysis.get('exit_stats', {}) if exit_analysis else {}
    exit_summary = {
        'total': exit_stats.get('total_exits', 0),
        'premature': len(exit_analysis.get('premature_exits', [])) if exit_analysis else 0,
        'delayed': len(exit_analysis.get('delayed_exits', [])) if exit_analysis else 0,
        'optimal': len(exit_analysis.get('optimal_exits', [])) if exit_analysis else 0
    }
    
    # 分类AI决策
    open_decisions = []
    close_decisions = []
    skip_decisions = []
    
    for decision in ai_decisions:
        action = decision.get('action', '')
        
        if action in ['open_long', 'open_short']:
            # 开仓决策：从entry_analysis中找结果
            result = find_trade_result_in_entry(decision, entry_analysis)
            open_decisions.append({
                'time': decision.get('timestamp', ''),
                'coin': decision.get('coin', ''),
                'action': action,
                'reason': decision.get('reason', '')[:200],  # 限制长度
                'result': result.get('classification', 'unknown'),
                'pnl': result.get('pnl', 0)
            })
            
        elif action in ['close_long', 'close_short']:
            # 平仓决策：从exit_analysis中找结果
            result = find_trade_result_in_exit(decision, exit_analysis)
            close_decisions.append({
                'time': decision.get('timestamp', ''),
                'coin': decision.get('coin', ''),
                'action': action,
                'reason': decision.get('reason', '')[:200],
                'result': result.get('classification', 'unknown'),
                'profit_left': result.get('profit_left', 0)
            })
            
        elif action == 'skip':
            # 跳过决策：从missed_opportunities中找
            opp = find_opportunity_in_missed(decision, entry_analysis)
            if opp:
                skip_decisions.append({
                    'time': decision.get('timestamp', ''),
                    'coin': decision.get('coin', ''),
                    'reason': decision.get('reason', '')[:200],
                    'potential_profit': opp.get('potential_profit', 0),
                    'signal_score': opp.get('signal_score', 0),
                    'consensus': opp.get('consensus', 0)
                })
    
    return {
        'entry_summary': entry_summary,
        'exit_summary': exit_summary,
        'open_decisions': open_decisions[:15],  # 限制数量
        'close_decisions': close_decisions[:15],
        'skip_decisions': skip_decisions[:15]
    }


def find_trade_result_in_entry(decision, entry_analysis):
    """从entry_analysis中找到对应交易的结果"""
    if not entry_analysis:
        return {'classification': 'unknown', 'pnl': 0}
    
    coin = decision.get('coin', '')
    _timestamp = decision.get('timestamp', '')  # 预留用于未来的时间窗口匹配
    
    # 在各个分类列表中查找
    for category in ['correct_entries', 'timing_issues', 'false_entries']:
        entries = entry_analysis.get(category, [])
        for entry in entries:
            if entry.get('coin') == coin:
                # 简单匹配（可以优化为时间窗口匹配）
                return {
                    'classification': category.replace('_entries', '').replace('_issues', '_issue').replace('_', '_'),
                    'pnl': entry.get('pnl', 0)
                }
    
    return {'classification': 'unknown', 'pnl': 0}


def find_trade_result_in_exit(decision, exit_analysis):
    """从exit_analysis中找到对应交易的结果"""
    if not exit_analysis:
        return {'classification': 'unknown', 'profit_left': 0}
    
    coin = decision.get('coin', '')
    
    # 在各个分类列表中查找
    for category in ['premature_exits', 'delayed_exits', 'optimal_exits']:
        exits = exit_analysis.get(category, [])
        for exit_trade in exits:
            if exit_trade.get('coin') == coin:
                return {
                    'classification': category.replace('_exits', '').replace('_', ' '),
                    'profit_left': exit_trade.get('profit_left_on_table', 0)
                }
    
    return {'classification': 'unknown', 'profit_left': 0}


def find_opportunity_in_missed(decision, entry_analysis):
    """从missed_opportunities中找到对应的错过机会"""
    if not entry_analysis:
        return None
    
    coin = decision.get('coin', '')
    _timestamp = decision.get('timestamp', '')  # 预留用于未来的时间窗口匹配
    
    missed_opps = entry_analysis.get('missed_opportunities', [])
    for opp in missed_opps:
        if opp.get('coin') == coin:
            # 简单匹配
            return {
                'potential_profit': opp.get('potential_profit', 0),
                'signal_score': opp.get('signal_score', 0),
                'consensus': opp.get('consensus', 0)
            }
    
    return None


def build_reflection_prompt(analysis_data):
    """构建AI自我反思的prompt"""
    
    entry_sum = analysis_data['entry_summary']
    exit_sum = analysis_data['exit_summary']
    
    prompt = f"""You are a trading AI performing self-reflection on yesterday's decisions.

# Performance Summary

## Entry Performance
- Total: {entry_sum['total']} trades
- ✅ Correct: {entry_sum['correct']} ({entry_sum['correct']/max(entry_sum['total'],1)*100:.0f}%)
- ⚠️ Timing Issue: {entry_sum['timing_issue']} ({entry_sum['timing_issue']/max(entry_sum['total'],1)*100:.0f}%)
- ❌ False Signal: {entry_sum['false_signal']} ({entry_sum['false_signal']/max(entry_sum['total'],1)*100:.0f}%)

## Exit Performance
- Total: {exit_sum['total']} exits
- ⏰ Premature: {exit_sum['premature']} ({exit_sum['premature']/max(exit_sum['total'],1)*100:.0f}%)
- ⏱️ Delayed: {exit_sum['delayed']} ({exit_sum['delayed']/max(exit_sum['total'],1)*100:.0f}%)
- ✅ Optimal: {exit_sum['optimal']} ({exit_sum['optimal']/max(exit_sum['total'],1)*100:.0f}%)

# Your Decisions (with results)

## 1. Open Decisions (showing up to 10)
```json
{json.dumps(analysis_data['open_decisions'][:10], indent=2, ensure_ascii=False)}
```

## 2. Close Decisions (showing up to 10)
```json
{json.dumps(analysis_data['close_decisions'][:10], indent=2, ensure_ascii=False)}
```

## 3. Skip Decisions (missed opportunities, showing up to 10)
```json
{json.dumps(analysis_data['skip_decisions'][:10], indent=2, ensure_ascii=False)}
```

# Your Task

Review your decisions and their outcomes. Generate concise, actionable insights:

1. **Entry Lessons** (2-3 key learnings)
   - What patterns led to timing issues or false signals?
   - What did you do right in correct entries?

2. **Exit Lessons** (2-3 key learnings)
   - Why did you exit too early or too late?
   - What exit signals should you trust more?

3. **Missed Opportunity Lessons** (2-3 key learnings)
   - Why did you skip these profitable opportunities?
   - What filters were too strict or signals misinterpreted?

4. **Improvements** (3-5 specific actions for tomorrow)
   - Concrete threshold adjustments (with numbers)
   - Decision logic changes
   - Signal interpretation refinements

# Output Format (JSON)
{{
  "entry_lessons": [
    "Lesson 1: Brief insight (1-2 sentences)...",
    "Lesson 2: Brief insight (1-2 sentences)..."
  ],
  "exit_lessons": [
    "Lesson 1: Brief insight (1-2 sentences)...",
    "Lesson 2: Brief insight (1-2 sentences)..."
  ],
  "missed_lessons": [
    "Lesson 1: Brief insight (1-2 sentences)...",
    "Lesson 2: Brief insight (1-2 sentences)..."
  ],
  "improvements": [
    "Action 1: Specific change with numbers...",
    "Action 2: Specific change with numbers...",
    "Action 3: Specific change with numbers..."
  ]
}}

# Important
- Be self-critical but constructive
- Focus on patterns, not individual cases
- Keep each item to 1-2 sentences
- Be specific with numbers when possible
- Output valid JSON only (no markdown, no extra text)
"""
    
    return prompt

