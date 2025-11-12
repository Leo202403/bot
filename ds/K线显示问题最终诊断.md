# K线显示问题最终诊断

## 问题描述
单页面（DeepSeek或Qwen）点击"切换到价格"按钮后，K线图不显示，但综合页面可以正常显示。

## 已确认正常的部分
1. ✅ 后端API正常（`/trading-price-data`返回数据）
2. ✅ 数据路径已修复（`/root/10-23-bot/ds/trading_data`）
3. ✅ Canvas销毁逻辑已修复（`priceChart.remove()`在创建前调用）
4. ✅ 根路径已恢复（`@app.route('/')`）

## 可能的原因

### 1. 模型切换时chartMode状态丢失
当用户从"综合"页面切换到"DeepSeek"或"Qwen"单页面时，`chartMode`可能没有被正确保留。

### 2. refresh()函数的调用时机
`switchModel()`函数会重置很多状态，包括清空图表容器，可能导致`loadPriceChart()`无法找到正确的容器。

### 3. 容器innerHTML被重置
在`toggleChartMode()`中，当切换到pnl模式时，会执行：
```javascript
container.innerHTML='<canvas id="pnlChartCanvas"></canvas>'
```
但切换到price模式时，只是销毁chart，没有重新创建容器结构。

## 建议的修复方案

### 方案1：确保容器正确初始化
在`loadPriceChart()`开始时，确保容器是干净的：
```javascript
const container=document.getElementById('pnlChart');
container.innerHTML='';  // 清空容器
```

### 方案2：在switchModel时保留chartMode
修改`switchModel()`函数，不要重置`chartMode`。

### 方案3：添加调试日志
在浏览器控制台查看：
- `loadPriceChart()`是否被调用
- API返回的数据是否正确
- LightweightCharts是否成功创建

## 用户操作步骤
1. 打开浏览器开发者工具（F12）
2. 切换到Console标签
3. 点击"DeepSeek"或"Qwen"标签
4. 点击"切换到价格"按钮
5. 查看控制台输出：
   - 是否有"🔍 当前时间范围"日志
   - 是否有"📡 请求价格数据"日志
   - 是否有"📥 收到数据"日志
   - 是否有"✅ 有效K线数据"日志
   - 是否有任何错误信息

## 快速测试
在浏览器控制台直接执行：
```javascript
console.log('chartMode:', chartMode);
console.log('currentModel:', currentModel);
console.log('priceChart:', priceChart);
loadPriceChart();
```

