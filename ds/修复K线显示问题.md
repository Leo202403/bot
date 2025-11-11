# K线显示问题分析与修复

## 根本原因

从浏览器控制台看到：
```
✅ 有效K线数据: 2189条
ð K线范围: 2025/10/20 08:00:00 至 2025/11/12 01:15:00
```

**数据正常，但Canvas报错**：
```
Error: Canvas is already in use. Chart with ID 'X' must be destroyed...
```

## 两个关键问题

### 问题1：Chart实例未正确销毁

在`updateChart`和`loadPriceChart`函数中，Chart对象被重复创建而没有彻底销毁。

### 问题2：图表容器冲突

`pnlChart`容器在PNL图表（Chart.js）和价格图表（LightweightCharts）之间共享，导致冲突。

## 修复策略

1. **在切换图表模式时，强制销毁所有Chart实例**
2. **清空并重建容器元素**
3. **确保LightweightCharts和Chart.js不会同时存在**

## 修复方案

### 修复点1：`toggleChartMode`函数

```javascript
function toggleChartMode(){
    chartMode=chartMode==='pnl'?'price':'pnl';
    document.getElementById('chartModeBtn').textContent=chartMode==='pnl'?'切换到价格':'切换到盈亏';
    document.getElementById('symbolControls').style.display=chartMode==='price'?'flex':'none';
    
    const symbolStatsDiv=document.getElementById('symbolStats');
    if(symbolStatsDiv){
        symbolStatsDiv.style.display=chartMode==='price'?'block':'none'
    }
    
    // ð¥ 关键修复：彻底销毁和重建容器
    const container=document.getElementById('pnlChart');
    
    if(chartMode==='pnl'){
        // 销毁价格图表
        if(priceChart&&priceChart.remove){
            priceChart.remove();
            priceChart=null
        }
        // 清空容器
        while(container.firstChild){
            container.removeChild(container.firstChild)
        }
        // 重建Canvas
        const canvas=document.createElement('canvas');
        canvas.id='pnlChartCanvas';
        container.appendChild(canvas)
    }else{
        // 销毁Chart.js实例
        if(chart){
            try{chart.destroy()}catch(e){}
            chart=null
        }
        if(compareChart){
            try{compareChart.destroy()}catch(e){}
            compareChart=null
        }
        // 清空容器
        while(container.firstChild){
            container.removeChild(container.firstChild)
        }
    }
    
    if(window.lastSummaryData){
        updateUI(window.lastSummaryData);
        updatePos(window.lastSummaryData);
        updateTrades(window.lastSummaryData)
    }
    
    if(chartMode==='pnl'){
        updateChart(window.lastSummaryData)
    }else{
        loadPriceChart()
    }
}
```

### 修复点2：`updateChart`函数开头

```javascript
async function updateChart(d){
    if(chartMode!=='pnl')return;
    if(!d?.pnl_24h&&!d?.status)return;
    try{
        // ð¥ 强制销毁现有图表
        if(chart){
            try{chart.destroy()}catch(e){}
            chart=null
        }
        if(compareChart){
            try{compareChart.destroy()}catch(e){}
            compareChart=null
        }
        
        const isMobile=window.innerWidth<=768;
        const canvas=document.getElementById('pnlChartCanvas');
        if(!canvas){
            console.error('找不到 pnlChartCanvas');
            return
        }
        
        // ... 剩余代码
```

### 修复点3：`loadPriceChart`函数开头

```javascript
async function loadPriceChart(){
    if(chartMode!=='price')return;
    try{
        // ð¥ 强制销毁LightweightCharts
        if(priceChart&&priceChart.remove){
            priceChart.remove();
            priceChart=null
        }
        
        console.log('ð 当前时间范围:',currentTimeRange);
        
        // ... 剩余代码
```

## 实施方案

由于前端代码是压缩在一行中的，无法用sed精确替换。建议：

1. **本地编辑修复**：将前端代码提取出来修复
2. **服务器直接替换整个文件**：从本地上传修复后的完整文件

## 临时解决方案

用户可以先**刷新浏览器（F5）**，避免频繁切换图表模式，这样可以绕过Canvas重用问题。

