# Phase 3 重构设计文档

## 🎯 Phase 3的目标

**在Phase 2基础上，进行风险控制优化**

## 📊 五个阶段的明确分工

1. **Phase 1**：客观统计所有机会
   - 输出：X个机会，平均最大利润Y%
   
2. **Phase 2**：快速探索，最大化捕获率
   - 目标：捕获率60% + 利润比率40%
   - 输出：捕获Z个(W%)，平均利润A%
   
3. **Phase 3**：风险控制优化 ⭐️（本次重构）
   - 约束：捕获率≥Phase 2的90%
   - 目标：利润最大化 + 风险最小化
   - 输出：最优参数（超短线+波段）
   
4. **Phase 4.5**：验证新参数
   - 检查平均利润是否为正
   
5. **Phase 5**：前向验证
   - 在验证期测试参数稳定性

## 🔧 Phase 3的实现逻辑

### 输入
- `phase1_baseline`: Phase 1统计结果
- `phase2_baseline`: Phase 2最优结果（捕获率、平均利润、参数）
- `ai_suggested_params`: AI分析订单后的建议参数
- `separated_opportunities`: 超短线和波段机会列表

### 评分公式

```python
# 约束条件
if capture_rate < phase2_baseline['capture_rate'] * 0.9:
    score = -1000  # 不合格

# 优化目标
profit_score = avg_profit  # 利润最大化
risk_score = win_rate * profit_ratio  # 风险最小化（胜率×盈亏比）

# 综合得分
score = profit_score * 0.6 + risk_score * 0.4
```

### 测试参数组合

为超短线和波段分别测试：
1. Phase 2参数（baseline）
2. AI建议参数
3. Phase 2 + AI建议的组合参数
4. 在组合参数基础上微调的参数

### 输出
```python
{
    'scalping': {
        'optimized_params': {...},
        'capture_rate': 0.38,  # 必须≥Phase 2的90%
        'avg_profit': 4.2,
        'win_rate': 0.45,
        'risk_score': 1.8
    },
    'swing': {...}
}
```

## 📝 实现步骤

1. 创建新函数：`optimize_strategy_with_risk_control()`
2. 分别优化超短线和波段
3. 每个策略测试4-6组参数组合
4. 选择综合得分最高且满足约束条件的参数
5. 在主流程中调用新Phase 3

## 🎯 预期效果

- **捕获率**：保持在Phase 2的90-100%
- **平均利润**：提升10-20%
- **风险控制**：胜率提升，盈亏比改善
- **耗时**：约1-2分钟（比旧Phase 3快，因为只测试4-6组参数）

## ⚠️ 与旧Phase 3的区别

| 对比项 | 旧Phase 3 | 新Phase 3 |
|--------|----------|----------|
| 优化目标 | time_exit率最小化 | 利润+风险综合优化 |
| 约束条件 | 无明确约束 | 捕获率≥Phase 2的90% |
| 参数空间 | 200组Grid Search | 4-6组精选参数 |
| 基准参考 | 当前配置 | Phase 2 baseline |
| AI参数 | 加入测试 | 加入测试+组合 |
| 耗时 | 3-5分钟 | 1-2分钟 |

