# Roblox Explore 排行接口数据不完整问题说明

这份文档用于向 Roblox 官方说明当前通过 Explore 排行接口获取榜单时出现的“漏游戏”问题，便于官方复现、确认原因并给出修复建议或替代方案。

## 问题摘要

我们当前通过 Roblox Explore 排行接口获取以下榜单数据：

- `Top_Trending_V4`
- `Up_And_Coming_V4`
- `CCU_Based_V1`
- `top-playing-now`

在实际使用中发现：

- 某些榜单返回的条数少于预期
- 某些明显应当出现在榜单中的游戏没有被返回
- 这些异常不是由我们本地解析、过滤或排序造成的，而是接口源数据本身就未返回对应游戏

其中问题最明显的例子是：

- `CCU_Based_V1` 榜单中缺少 `Murder Mystery 2`
- 但该游戏在排查时的在线人数约为 `180K+`
- 按常识应当进入基于在线人数的榜单

## 我们的使用场景

我们构建了一个飞书机器人工作流，用于定时和手动拉取 Roblox 榜单并生成飞书表格。

主要场景包括：

1. 手动触发 `/roblox-top-day`
2. 定时触发日榜同步
3. 将多个 Roblox 榜单写入飞书普通表格的多个 Sheet
4. 基于上一次同步结果计算“排名变化”

因为我们的业务依赖榜单完整性，所以如果接口返回缺失，会直接导致：

- 表格中缺少应上榜的游戏
- 排名变化计算失真
- 运营人员误判榜单变化

## 实际调用的接口

### 1. 榜单内容接口

当前项目使用：

```text
GET https://apis.roblox.com/explore-api/v1/get-sort-content
```

请求参数：

- `sessionId=<随机UUID>`
- `sortId=<榜单ID>`
- `device=all`
- `country=all`

说明：

- 排名来源完全依赖这个接口返回的榜单内容
- 我们不会在本地额外插入、删除、重排游戏

### 2. 榜单类型发现接口

当前项目也会使用：

```text
GET https://apis.roblox.com/explore-api/v1/get-sorts
```

请求参数：

- `sessionId=<随机UUID>`

用途：

- 获取当前可用的 Explore sort 列表
- 确认 `Top_Trending_V4`、`Up_And_Coming_V4`、`CCU_Based_V1` 等 sort id

### 3. 游戏详情补充接口

当前项目还会使用：

```text
GET https://games.roblox.com/v1/games?universeIds=...
```

用途：

- 补充开发者、访问量、更新时间等详情字段

重要说明：

- 这个接口不决定榜单排序
- 也不会影响“某个游戏是否上榜”
- 因此漏游戏问题不在这个接口

## 复现方式

### 复现条件

- 调用 `get-sort-content`
- 使用 `device=all`
- 使用 `country=all`
- 使用以下 sortId 之一：
  - `Top_Trending_V4`
  - `Up_And_Coming_V4`
  - `CCU_Based_V1`

### 复现步骤

1. 调用：

```text
GET https://apis.roblox.com/explore-api/v1/get-sort-content?sessionId=<uuid>&sortId=CCU_Based_V1&device=all&country=all
```

2. 检查返回结果中的游戏列表

3. 对照当时 Roblox 站内已知高在线游戏，例如：

- `Murder Mystery 2`

4. 观察到：

- 返回列表中未包含该游戏
- 返回条数也可能少于预期 100 条

## 已观察到的异常现象

### 现象 1：榜单返回条数不足

我们期望相关榜单返回接近 Top 100 的列表，但实际有时返回明显少于 100 条。

这会导致：

- 飞书表格记录条数不足
- 榜单展示不完整

### 现象 2：明显应上榜的游戏未返回

在 `CCU_Based_V1` 中，我们观察到：

- `Murder Mystery 2` 未被返回

但在排查时：

- 该游戏的在线人数足够高
- 理论上应当进入以在线人数为核心的榜单

### 现象 3：Trending / Up-and-Coming 也存在类似问题

除了 `CCU_Based_V1` 以外，我们也在以下榜单中观察到疑似漏数问题：

- `Top_Trending_V4`
- `Up_And_Coming_V4`

这说明问题可能不是单个 sort 特有，而是 Explore 排行接口返回数据的完整性存在不确定性。

## 我们已经排除的本地原因

为避免误判，我们已经排查并排除以下本地问题：

### 1. 不是本地排序问题

我们对 `get-sort-content` 返回的游戏列表按返回顺序直接生成排名：

- 第 1 条数据就是第 1 名
- 不会在本地再根据在线人数或其他字段重新排序

### 2. 不是本地过滤问题

我们没有对榜单结果做以下处理：

- 不会按在线人数设门槛过滤
- 不会按地区过滤
- 不会按设备过滤
- 不会按游戏类型过滤

### 3. 不是详情补充接口造成的

`games.roblox.com/v1/games` 只负责补充详情：

- 开发者
- 访问量
- 更新时间

这个接口不会影响榜单是否包含某个游戏。

### 4. 不是设备 / 地区参数过窄

当前参数已经使用：

- `device=all`
- `country=all`

所以不是因为我们只查了某个设备或某个国家而导致缺失。

## 期望官方协助确认的问题

希望 Roblox 官方协助确认以下问题：

1. `get-sort-content` 在以下 sortId 下是否存在已知数据缺失问题：
   - `Top_Trending_V4`
   - `Up_And_Coming_V4`
   - `CCU_Based_V1`

2. 这些 sort 是否本身带有额外筛选逻辑，因此并不是完整榜单

3. 如果这些 sort 本来就不是完整榜单，是否有官方推荐的、面向公开使用的、数据更完整的排行榜接口或替代 sortId

4. `CCU_Based_V1` 是否可以被视为完整的基于在线人数的榜单

5. 如果不能，官方建议用哪个接口或 sort 来获取更稳定、完整的排行榜结果

## 对官方最关键的一句话

我们当前的问题不是本地解析错误，而是 Explore 排行接口返回的数据源本身疑似不完整，导致部分明显应上榜的游戏没有出现在返回结果中。

## 当前项目里的相关代码位置

如需对照实现，可参考：

- [app/roblox_client.py](/C:/Users/41539/Desktop/roblox-top100-fetcher/app/roblox_client.py)

其中关键位置包括：

- 排行接口定义：`GET_SORT_CONTENT_URL`
- 请求参数：`device=all`、`country=all`
- sort 拉取逻辑：`fetch_games_by_sort_id(...)`

