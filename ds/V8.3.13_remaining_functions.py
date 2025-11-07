"""
V8.3.13剩余函数代码

包含:
- Per-Symbol优化 (V8.3.13.3)
- 多时间框架分析 (V8.3.13.4)  
- 实时策略切换增强 (V8.3.13.6)
"""

# ==================================================
# V8.3.13.3: Per-Symbol优化
# ==================================================

def analyze_per_symbol_opportunities(market_snapshots, old_config, symbols=None):
    """
    【V8.3.13.3】分析每个币种的分离机会
    
    返回:
    {
        'BTC': {
            'scalping': {...},
            'swing': {...}
        },
        'ETH': {...},
        ...
    }
    """
    try:
        import pandas as pd
        
        if symbols is None:
            symbols = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'DOGE', 'LTC']
        
        per_symbol_data = {}
        
        for symbol in symbols:
            symbol_data = market_snapshots[market_snapshots['coin'] == symbol]
            
            if len(symbol_data) < 100:
                print(f"  ⚠️  {symbol}: 数据不足（{len(symbol_data)}条），跳过")
                continue
            
            # 分析该币种的scalping和swing机会
            from深入分析 import analyze_separated_opportunities  # 复用V8.3.12的函数
            
            separated = analyze_separated_opportunities(symbol_data, old_config)
            
            per_symbol_data[symbol] = separated
            
            print(f"  📊 {symbol}: ⚡{separated['scalping']['total_opportunities']}个scalping, 🌊{separated['swing']['total_opportunities']}个swing")
        
        return per_symbol_data
        
    except Exception as e:
        print(f"⚠️ Per-symbol分析失败: {e}")
        import traceback
        traceback.print_exc()
        return {}


def optimize_per_symbol_params(per_symbol_data, global_config):
    """
    【V8.3.13.3】为每个币种优化参数
    
    返回:
    {
        'BTC': {
            'scalping_params': {...},
            'swing_params': {...},
            'improvement': {...}
        },
        ...
    }
    """
    try:
        from 深入优化 import optimize_scalping_params, optimize_swing_params  # 复用V8.3.12函数
        
        optimized_params = {}
        
        for symbol, data in per_symbol_data.items():
            print(f"\n  🔧 优化{symbol}参数...")
            
            symbol_result = {
                'scalping_params': {},
                'swing_params': {},
                'improvement': {}
            }
            
            # 优化scalping
            if data['scalping']['total_opportunities'] >= 20:
                scalping_opt = optimize_scalping_params(
                    scalping_data=data['scalping'],
                    current_params=global_config.get('scalping_params', {})
                )
                symbol_result['scalping_params'] = scalping_opt['optimized_params']
                symbol_result['improvement']['scalping'] = scalping_opt.get('improvement')
                print(f"    ⚡ Scalping: time_exit {scalping_opt['old_time_exit_rate']*100:.0f}% → {scalping_opt['new_time_exit_rate']*100:.0f}%")
            
            # 优化swing
            if data['swing']['total_opportunities'] >= 20:
                swing_opt = optimize_swing_params(
                    swing_data=data['swing'],
                    current_params=global_config.get('swing_params', {})
                )
                symbol_result['swing_params'] = swing_opt['optimized_params']
                symbol_result['improvement']['swing'] = swing_opt.get('improvement')
                print(f"    🌊 Swing: 利润 {swing_opt['old_avg_profit']:.1f}% → {swing_opt['new_avg_profit']:.1f}%")
            
            optimized_params[symbol] = symbol_result
        
        return optimized_params
        
    except Exception as e:
        print(f"⚠️ Per-symbol优化失败: {e}")
        import traceback
        traceback.print_exc()
        return {}


def get_per_symbol_params(symbol, signal_type, learning_config):
    """
    【V8.3.13.3】获取币种专属参数
    
    优先级:
    1. per_symbol_params[symbol][signal_type]
    2. signal_type_params (scalping_params/swing_params)
    3. global params
    """
    try:
        # 优先级1: Per-symbol
        per_symbol = learning_config.get('per_symbol_params', {}).get(symbol, {})
        if signal_type == 'scalping':
            params = per_symbol.get('scalping_params', {})
        else:
            params = per_symbol.get('swing_params', {})
        
        if params:
            return params
        
        # 优先级2: Signal type
        if signal_type == 'scalping':
            return learning_config.get('scalping_params', {})
        else:
            return learning_config.get('swing_params', {})
            
    except:
        return learning_config.get('global', {})


# ==================================================
# V8.3.13.4: 多时间框架分析
# ==================================================

def analyze_multi_timeframe_exits(exit_details, timeframes=['1H', '4H']):
    """
    【V8.3.13.4】分析不同时间框架的exit patterns
    
    参数:
        exit_details: list of exit detail dicts
        timeframes: 要分析的时间框架
    
    返回:
    {
        '1H': {
            'time_exit_rate': 0.85,
            'avg_missed_profit': 3.2,
            'avg_holding_time': 1.5,
            'tp_触发时间': 0.8  # 小时
        },
        '4H': {...}
    }
    """
    try:
        if not exit_details:
            return None
        
        analysis = {}
        
        for tf in timeframes:
            # 根据时间框架过滤数据
            if tf == '1H':
                # 持仓时间 < 2小时的
                filtered = [d for d in exit_details if d.get('holding_hours', 0) < 2]
            elif tf == '4H':
                # 持仓时间 >= 2小时的
                filtered = [d for d in exit_details if d.get('holding_hours', 0) >= 2]
            else:
                filtered = exit_details
            
            if not filtered:
                continue
            
            # 统计
            time_exits = [d for d in filtered if d['exit_type'] == 'time_exit']
            take_profits = [d for d in filtered if d['exit_type'] == 'take_profit']
            
            analysis[tf] = {
                'total_count': len(filtered),
                'time_exit_rate': len(time_exits) / len(filtered) if filtered else 0,
                'avg_missed_profit': sum(d.get('missed_profit', 0) for d in time_exits) / len(time_exits) if time_exits else 0,
                'avg_holding_time': sum(d.get('holding_hours', 0) for d in filtered) / len(filtered) if filtered else 0,
                'tp_avg_time': sum(d.get('holding_hours', 0) for d in take_profits) / len(take_profits) if take_profits else 0
            }
        
        return analysis
        
    except Exception as e:
        print(f"⚠️ 多时间框架分析失败: {e}")
        return None


def generate_timeframe_recommendations(timeframe_analysis, signal_type):
    """
    【V8.3.13.4】生成时间框架优化建议
    
    返回:
    {
        'recommended_timeframe': '1H' or '4H',
        'recommended_holding_hours': 1.5,
        'reason': '...',
        'expected_improvement': '...'
    }
    """
    try:
        if not timeframe_analysis:
            return None
        
        recommendations = {
            'recommended_timeframe': None,
            'recommended_holding_hours': None,
            'reason': '',
            'expected_improvement': ''
        }
        
        # 超短线：选择Time Exit率低的时间框架
        if signal_type == 'scalping':
            tf_1h = timeframe_analysis.get('1H', {})
            tf_4h = timeframe_analysis.get('4H', {})
            
            if tf_1h and tf_4h:
                if tf_1h['time_exit_rate'] < tf_4h['time_exit_rate']:
                    recommendations['recommended_timeframe'] = '1H'
                    recommendations['recommended_holding_hours'] = tf_1h['tp_avg_time']
                    recommendations['reason'] = f"1H时间框架Time Exit率更低（{tf_1h['time_exit_rate']*100:.0f}% vs {tf_4h['time_exit_rate']*100:.0f}%）"
                else:
                    recommendations['recommended_timeframe'] = '4H'
                    recommendations['recommended_holding_hours'] = tf_4h['tp_avg_time']
                    recommendations['reason'] = f"4H时间框架Time Exit率更低（{tf_4h['time_exit_rate']*100:.0f}% vs {tf_1h['time_exit_rate']*100:.0f}%）"
        
        # 波段：选择平均利润高的时间框架
        else:  # swing
            tf_1h = timeframe_analysis.get('1H', {})
            tf_4h = timeframe_analysis.get('4H', {})
            
            if tf_4h:
                recommendations['recommended_timeframe'] = '4H'
                recommendations['recommended_holding_hours'] = tf_4h.get('avg_holding_time', 24)
                recommendations['reason'] = "波段交易适合4H时间框架，更大的利润空间"
        
        recommendations['expected_improvement'] = f"预计Time Exit率降低5-10%，持仓时间优化到{recommendations['recommended_holding_hours']:.1f}小时"
        
        return recommendations
        
    except Exception as e:
        print(f"⚠️ 时间框架建议生成失败: {e}")
        return None


# ==================================================
# V8.3.13.6: 实时策略切换增强（基于V8.3.9）
# ==================================================

def select_strategy_by_market_state(atr_pct, signal_type, current_params):
    """
    【V8.3.13.6】根据市场状态动态选择策略
    
    参数:
        atr_pct: ATR百分比（波动率）
        signal_type: 'scalping' or 'swing'
        current_params: 当前参数
    
    返回:
        adjusted_params: 调整后的参数
        strategy_note: 策略说明
    """
    try:
        adjusted_params = current_params.copy()
        
        # 高波动 (atr_pct > 2.5%)
        if atr_pct > 2.5:
            if signal_type == 'scalping':
                # 超短线高波动：扩大SL，缩短持仓
                adjusted_params['atr_stop_multiplier'] = current_params.get('atr_stop_multiplier', 1.0) * 1.3
                adjusted_params['max_holding_hours'] = current_params.get('max_holding_hours', 1.5) * 0.8
                strategy_note = "高波动：扩大止损30%，缩短持仓20%"
            else:  # swing
                # 波段高波动：使用ATR-based而非SR-based
                adjusted_params['use_sr_levels'] = False
                adjusted_params['atr_stop_multiplier'] = current_params.get('atr_stop_multiplier', 2.0) * 1.2
                strategy_note = "高波动：使用ATR止损而非SR levels"
        
        # 低波动 (atr_pct < 1.0%)
        elif atr_pct < 1.0:
            if signal_type == 'scalping':
                # 超短线低波动：缩小TP距离，延长持仓
                adjusted_params['atr_tp_multiplier'] = current_params.get('atr_tp_multiplier', 1.5) * 0.8
                adjusted_params['max_holding_hours'] = current_params.get('max_holding_hours', 1.5) * 1.2
                strategy_note = "低波动：缩小止盈20%，延长持仓20%"
            else:  # swing
                # 波段低波动：优先使用SR-based
                adjusted_params['use_sr_levels'] = True
                adjusted_params['atr_tp_multiplier'] = current_params.get('atr_tp_multiplier', 6.0) * 0.9
                strategy_note = "低波动：优先SR levels，缩小止盈距离"
        
        # 正常波动 (1.0% <= atr_pct <= 2.5%)
        else:
            strategy_note = "正常波动：使用标准参数"
        
        return adjusted_params, strategy_note
        
    except Exception as e:
        print(f"⚠️ 策略选择失败: {e}")
        return current_params, "使用默认参数"


# ==================================================
# V8.3.13.5: RL框架设计（仅框架，不实现）
# ==================================================

class TradingEnvironment:
    """
    【V8.3.13.5】交易环境 - RL框架
    
    这是一个框架设计，暂不实现具体代码
    """
    def __init__(self, historical_data):
        """初始化环境"""
        self.data = historical_data
        self.current_step = 0
        self.current_params = {}
    
    def reset(self):
        """重置环境到初始状态"""
        self.current_step = 0
        self.current_params = {}
        return self._get_state()
    
    def step(self, action):
        """
        执行动作（参数调整）
        
        返回: (next_state, reward, done, info)
        """
        # 应用动作到参数
        self.current_params = self._apply_action(action)
        
        # 模拟交易
        reward = self._simulate_trading(self.current_params)
        
        # 更新状态
        self.current_step += 1
        done = (self.current_step >= len(self.data))
        
        return self._get_state(), reward, done, {}
    
    def _get_state(self):
        """获取当前状态"""
        pass
    
    def _apply_action(self, action):
        """应用动作"""
        pass
    
    def _simulate_trading(self, params):
        """模拟交易，返回reward"""
        pass


class ParameterAgent:
    """
    【V8.3.13.5】参数优化智能体 - RL框架
    
    这是一个框架设计，暂不实现具体代码
    """
    def __init__(self):
        """初始化智能体"""
        self.policy_network = None
        self.value_network = None
        self.memory = []
    
    def select_params(self, state):
        """根据当前状态选择参数"""
        pass
    
    def update(self, experience):
        """更新策略"""
        pass
    
    def save(self, path):
        """保存模型"""
        pass
    
    def load(self, path):
        """加载模型"""
        pass

