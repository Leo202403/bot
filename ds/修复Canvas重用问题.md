# Canvas重用问题修复

## 问题诊断

控制台错误：
```
Error: Canvas is already in use. Chart with ID 'X' must be destroyed before the canvas with ID 'pnlChartCanvas' can be reused.
```

## 根本原因

`updateChart`函数中，虽然有`if(chart)chart.destroy()`，但是：
1. 当从价格图表切回盈亏图表时，Canvas元素被重新创建
2. Chart.js认为Canvas还在被占用
3. 需要更彻底的清理逻辑

## 修复方案

在`updateChart`函数开始处添加更强的清理逻辑：

```javascript
async function updateChart(d){
    if(chartMode!=='pnl')return;
    if(!d?.pnl_24h&&!d?.status)return;
    try{
        // 🔧 强制销毁所有图表对象
        if(chart){
            try{
                chart.destroy();
            }catch(e){
                console.warn('销毁chart失败:',e);
            }
            chart=null;
        }
        if(compareChart){
            try{
                compareChart.destroy();
            }catch(e){
                console.warn('销毁compareChart失败:',e);
            }
            compareChart=null;
        }
        
        // 🔧 清理Canvas元素
        const container=document.getElementById('pnlChart');
        if(container){
            // 移除所有子元素
            while(container.firstChild){
                container.removeChild(container.firstChild);
            }
            // 重新创建Canvas
            const newCanvas=document.createElement('canvas');
            newCanvas.id='pnlChartCanvas';
            container.appendChild(newCanvas);
        }
        
        const isMobile=window.innerWidth<=768;
        const canvas=document.getElementById('pnlChartCanvas');
        if(!canvas){
            console.error('找不到 pnlChartCanvas');
            return;
        }
        
        // ... 剩余代码保持不变
```

## 修复步骤

由于前端代码压缩在一行中，手动修改困难，建议：

### 方案1：重新生成前端文件（推荐）
从本地已修复的版本重新生成，确保所有Chart实例正确销毁。

### 方案2：服务器热修复
使用sed命令直接在服务器修改：

```bash
cd /root/pythonc程序/my_project/
# 备份
cp 每日壁纸更换.py 每日壁纸更换.py.bak

# 修复Chart销毁逻辑
# 在 if(chart)chart.destroy() 之后添加更强的清理
```

## 临时解决方案

用户可以：
1. **刷新页面**：F5强制刷新
2. **清除缓存**：Ctrl+Shift+R
3. **避免频繁切换**：切换到价格图表后，尽量不要频繁切回盈亏图表

## 预期效果

修复后：
- ✅ 切换图表模式不再报错
- ✅ Canvas正确重用
- ✅ K线图正常显示

