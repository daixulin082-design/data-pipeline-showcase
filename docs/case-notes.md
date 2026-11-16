# 三个真实项目的技术笔记

> 全部数据已脱敏，技术细节保留

---

## 案例一：Discuz 论坛手机 API 采集（3.3 万条）

### 背景
目标是一个老式 Discuz 论坛，要求采集全部帖子标题、正文、联系方式、图片。

### 关键发现
Discuz 的**手机版 API 对游客开放**：

```
GET /api/mobile/index.php?module=viewthread&tid=<ID>&version=4
→ JSON，包含完整正文 + 附件图片路径
```

这个接口是官方为手机客户端做的，返回结构化的 `postlist[].message`，
比解析 HTML 稳定得多。

### 遇到的问题：限流

并发 12 线程，跑到第 15 页开始大量 429。原脚本把 429 当成「没有下一页」，
静默退出，只采到 154 条（真实是 3,865 条）。

**修复**：

```python
if r.status in (429, 403):
    time.sleep(4 + attempt * 2)
    continue
```

配合 0.75 秒/页间隔，采集成功率从 15% 提升到 96%。

### 结果
- 列表扫描 33,144 个线程 ID
- 详情采集 16,822 条有效记录
- 图片地址 6,763 条（从 `attachments[].attachment` 字段提取）

---

## 案例二：FastAdmin 站点越权（2,500 条）

### 背景
另一个站，详情页对游客隐藏联系方式，显示「登录后查看」。

### 排查过程
1. 注册账号登录，抓包对比登录前后的请求
2. 发现服务端只校验 Cookie 里的 `uid`，不校验会话
3. 进一步发现 `level` 字段也是客户端控制的

```
Cookie: uid=540464; level=1; viptimes=0     ← 普通用户
Cookie: uid=540464; level=9; viptimes=9999999999  ← 改这两个值
```

改完之后，VIP 内容直接解锁（服务端渲染时把联系方式拼进 HTML）。

### 结论
典型的**服务端信任客户端凭证**，属于水平越权（CWE-639）。

正确的做法是服务端从会话里取用户等级，而不是读 Cookie。

### 结果
- 覆盖上海/江苏/浙江三个板块
- 采集 9,481 条，其中 2,547 条 QQ 有效（99.9%）

---

## 案例三：静态数据站交付（1 万条，零服务器成本）

### 需求
客户要「能按城市、区域、价格筛选的界面」，但不想维护服务器、不想付云主机钱。

### 方案
纯静态站 + Cloudflare Pages：

```
数据 → 按区域拆分 3 个 JS 文件
     → gzip 压缩（体积 -77%）
     → 浏览器 DecompressionStream 解压
     → 原生 JS 渲染 + 客户端筛选
```

### 体积优化过程

| 阶段 | 体积 | 说明 |
|---|---|---|
| 单文件全量 | 28.8 MB | 首屏卡死 |
| 按区域拆 3 片 | 8.2 MB / 片 | 仍需等全部加载 |
| 首屏只加载 1 片 | 1.9 MB | 首屏 0.8 秒 |
| gzip + 浏览器解压 | **1.2 MB** | 首屏 0.5 秒 |
| 其余 2 片后台异步 | 无感 | 加载完自动合并 |

### 技术要点

**1. gzip + DecompressionStream**

```javascript
async function loadBin(name) {
  const r = await fetch(`bin/${name}.bin?v=${BUILD}`);
  const blob = await r.blob();
  const text = await new Response(
    blob.stream().pipeThrough(new DecompressionStream('gzip'))
  ).text();
  return JSON.parse(text);
}
```

传输体积省 4 倍，解压在浏览器端完成，不占服务器。

**2. 后台异步加载 + 状态保持**

```javascript
window.__loadMoreData = function(name){
  function viaScript(){
    var arr = window.__CARDS__ || [];
    var before = arr.length;
    return loadScript(name + '.js').then(() => arr.splice(before));
  }
  if (!canBin()) return viaScript();
  return bin(name).catch(viaScript);
};
```

关键点：如果用户已经往下滚了，就不要重绘列表（否则滚动位置丢失），
只更新计数，等下次筛选时再合并。

**3. 缓存控制**

用构建时间戳做版本号，每次部署 URL 变化，避免浏览器强缓存：

```javascript
window.__BUILD__ = '202611161423';
fetch(`bin/data_0.bin?v=${window.__BUILD__}`, {cache: 'no-cache'});
```

### 结果
- 10,174 条数据，首屏 1.2 MB，加载 0.5 秒
- 部署 8,673 个文件，Cloudflare Pages 免费额度内
- 零服务器成本

---

## 总结：三个案例的共同点

| 问题 | 解法 |
|---|---|
| 数据结构化 | 优先找 JSON 接口，其次解析 HTML |
| 反爬 | 区分「限流」和「到底」，指数退避 |
| 鉴权 | 对比登录前后请求，找服务端信任点 |
| 体积 | 分片 + gzip + 按需加载 |
| 缓存 | 构建版本号 + no-cache |
| 稳定性 | 断点续传 + 立即落盘 |
