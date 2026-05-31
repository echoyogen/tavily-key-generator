# Cloudflare 邮件设置详解

[English Version](./Cloudflare-Mail-Setup-Guide.md)

通用版教程：用 Cloudflare Email Routing、Catch-all 和 Email Workers，搭一套可以长期复用的“无限别名域名邮箱”方案。

> 本文里的“无限域名邮箱”，准确说是“无限别名域名邮箱”。
> 也就是：你不需要预先创建每一个邮箱账号，就能接住发往你域名下任意随机地址的邮件。
> 这对注册网站、自动化收验证码、测试环境、内部通知系统都很好用。

本文已按 Cloudflare 官方文档于 `2026-03-16` 核对。

---

## 一、这篇文档适合谁

这篇教程不是只给 `tavily-key-generator` 用的。

只要你有下面这些需求，它都适用：

- 想把自己的域名变成“可无限生成别名”的收信入口
- 想收验证码、登录链接、确认邮件，而不想手动建一堆邮箱账号
- 想把域名邮箱接进脚本、自动化系统、注册机、测试环境
- 想把邮件转发给 Gmail / Outlook / 企业邮箱
- 想自己做一个邮件 API，让程序通过 HTTP 查询邮件内容

如果你只是想做最简单的域名邮箱转发，这篇能用。  
如果你想做自动化邮件系统，这篇也能直接沿着往下搭。

---

## 二、先把“无限域名邮箱”这件事说清楚

很多人第一次听到“无限域名邮箱”，会误以为是下面两种意思：

1. 一个 Cloudflare 账号可以无限创建正式邮箱账户
2. Cloudflare 原生提供完整的收件箱系统，像 Gmail 一样直接登录查看邮件

这两个理解都不准确。

更准确的说法是：

### 你可以用自己的域名，接住几乎无限多的随机收件地址，而不需要一条条手工创建邮箱。

比如下面这些地址：

```text
anything-1@example.com
signup-abc@example.com
tavily-x8y9z0@example.com
notify-order-123@example.com
```

你并不需要提前在后台创建这些具体邮箱。

你只需要：

1. 开启 Cloudflare Email Routing
2. 配置 Catch-all
3. 决定这些邮件最终交给谁处理

这样一来，发到你域名上的大量随机地址都能被统一接住。

### 但它不是没有任何限制

根据 Cloudflare 官方文档，截至 `2026-03-16`，你仍然需要注意这些限制：

- Email Routing 的 `Rules` 默认上限是 `200`
- `Addresses` 默认上限是 `200`
- 单封邮件大小目前不支持超过 `25 MiB`
- 如果你用 Email Workers，仍然受 Workers 资源限制影响

如果默认上限不够，Cloudflare 官方文档还提供了申请提高限制的入口。

所以，“无限”更适合理解成：

### 对实际使用来说，你可以不预创建邮箱账号，靠 Catch-all 和 Worker 处理无限多的随机别名地址。

这才是这套方案真正的价值。

---

## 三、它能做什么，不能做什么

先把边界说清楚，后面配置时就不容易绕。

### 它很适合做这些事

- 网站注册验证码收信
- 自动化注册系统
- 测试环境邮箱
- 服务通知归集
- 多平台订阅和注册分流
- 内部工具邮件入口
- 给不同用途分配不同别名地址

### 它不适合直接替代完整企业邮箱

如果你想要的是这些能力：

- 标准网页邮箱界面
- 发件箱 / 已发送 / 草稿箱
- IMAP / POP3 的完整邮箱客户端体验
- 一套“一个人一个正式邮箱账号”的办公邮箱系统

那你要找的是：

- Google Workspace
- Microsoft 365
- Zoho Mail
- Fastmail
- 其他专门的邮箱托管服务

Cloudflare Email Routing 更像是：

**一套极强的“收信入口 + 分发/处理层”**

而不是一套完整的传统邮箱产品。

另外，Cloudflare 官方文档也明确写了：

### Email Routing 不处理出站发信，也不提供 SMTP server。

所以如果你需要“发邮件”能力，需要额外接别的发信方案。

---

## 四、整体架构怎么选

这套方案通常有两种常见用法。

### 模式 A：普通转发模式

适合个人和轻量使用。

```text
发往你的域名邮箱
        ↓
Cloudflare Email Routing
        ↓
转发到你的 Gmail / Outlook / 企业邮箱
```

优点：

- 配起来最快
- 不需要写代码
- 适合普通订阅、备用邮箱、注册收信

缺点：

- 自动化能力有限
- 不方便程序直接读取
- 后续做分类、API 查询、验证码提取时不够灵活

### 模式 B：Worker 自动化模式

适合开发者、脚本、项目接入。

```text
发往你的域名邮箱
        ↓
Cloudflare Email Routing
        ↓
Catch-all 命中
        ↓
Email Worker 处理
        ↓
D1 / KV / R2 / Webhook / 你的 API
        ↓
程序、项目或内部系统读取
```

优点：

- 非常适合自动化
- 可以直接做邮件 API
- 可以解析验证码、链接、主题、正文
- 可以接通知系统、数据库、后台面板
- 可以把“无限别名地址”真正变成程序可用能力

缺点：

- 需要写一点 Worker 代码
- 需要理解 D1 / API / 路由这些概念

如果你只是想正常收信，用模式 A。  
如果你是为了自动化、脚本或项目接入，直接上模式 B。

---

## 五、主域名还是子域名，怎么选

这一步很重要，关系到后面会不会踩坑。

### 最推荐：单独用一个子域名

例如：

- `mail.example.com`
- `notify.example.com`
- `signup.example.com`
- `box.example.com`

为什么推荐子域名：

1. 不会影响你主域名现有业务
2. DNS 更干净
3. 更适合“自动化收信”这种场景
4. 排障更简单

### 如果你的主域名已经在跑正式邮箱，别硬改

Cloudflare 官方文档说明得很明确：

当 Email Routing 正在工作时，你不能在同一个被配置的域名上同时保留其他活跃的 MX 邮件服务。

换句话说，如果你的主域名已经在用：

- Google Workspace
- 腾讯企业邮
- 阿里云企业邮箱
- Microsoft 365

那最稳的方式永远是：

**新开一个专用子域名来做这件事。**

---

## 六、开始前需要准备什么

正式动手前，先准备好这些：

1. 一个已经接入 Cloudflare 的域名
2. Cloudflare Dashboard 访问权限
3. 一个决定好的主域名或子域名
4. 如果要做自动化模式，本地能使用 `node`、`npm`、`wrangler`

如果你还没装 `wrangler`：

```bash
npm install -g wrangler
```

登录：

```bash
wrangler login
```

---

## 七、第一步：开启 Email Routing

进入：

```text
Cloudflare Dashboard
-> 你的域名
-> Email
-> Email Routing
```

第一次使用时，Cloudflare 会提示你开启 Email Routing。

你照向导做即可，核心动作是：

1. 开启 Email Routing
2. 允许 Cloudflare 自动添加需要的 DNS 记录

这一步通常会涉及：

- `MX`
- `TXT`

### 这里有 3 个高频坑

#### 1. 旧 MX 记录冲突

如果这个域名本来就在跑其他邮件服务，Cloudflare 会提示冲突。

如果你不删除旧 MX，Email Routing 通常无法正常启用。

#### 2. SPF 记录冲突

如果后台报 SPF 问题，尽快修。

多个 SPF 记录经常会让邮件链路表现异常。

#### 3. 不要乱改 Cloudflare 自动生成的邮件 DNS

Cloudflare 为 Email Routing 自动生成的记录，能不手改就别手改。

---

## 八、第二步：如果要用子域名，先把子域名加进去

如果你用的是：

```text
signup.example.com
```

这种子域名，而不是 zone 顶级域名，那么要先在 Cloudflare 里启用这个子域名的 Email Routing 能力。

操作路径：

```text
Email
-> Email Routing
-> Settings
-> Add subdomain
```

加好之后，Cloudflare 会在 Routing Rules 里允许你选择：

- 顶级域名
- 已配置的子域名

这一步做完后，你就可以对这个子域名创建自定义地址和路由规则了。

---

## 九、第三步：理解 3 个核心概念

Cloudflare Email Routing 里最常用的其实就这 3 个概念。

### 1. Custom address

这是你显式创建的一条邮箱规则，比如：

```text
info@example.com
news@example.com
verify@example.com
```

适合你明确知道自己要哪些固定地址时使用。

### 2. Catch-all

这是最关键的能力。

它的作用是：

**让没有显式创建规则的地址，也能被统一接住。**

对“无限别名邮箱”方案来说，Catch-all 基本上是必需的。

有了它，你就不需要逐个创建：

```text
a1@example.com
a2@example.com
a3@example.com
random-1@example.com
random-2@example.com
```

这些地址都可以统一走 Catch-all。

### 3. Subaddressing（Plus Addressing）

Cloudflare 现在支持类似：

```text
user+tag@example.com
```

这样的地址形式。

这更适合“在一个固定地址上附加标签”。

例如：

```text
newsletter+reddit@example.com
newsletter+github@example.com
```

它适合做来源标记，但它不是 Catch-all 的替代品。

简单说：

- 想接住任意随机 local-part，用 Catch-all
- 想在一个已有地址上附加上下文标签，用 Subaddressing

---

## 十、第四步：先决定邮件最终去哪

你在 Cloudflare 里配置路由时，最终一般有两条路。

### 方案 A：转发给一个真实邮箱

比如：

- Gmail
- Outlook
- 企业邮箱

这是最简单的路线。

操作逻辑是：

```text
自定义地址 / Catch-all
-> 转发到 verified destination address
```

适合：

- 普通收信
- 个人备用邮箱
- 注册网站
- 邮件归集

### 方案 B：交给 Email Worker

这是更适合自动化和项目接入的路线。

操作逻辑是：

```text
自定义地址 / Catch-all
-> Send to Email Worker
```

适合：

- 自动提取验证码
- 自动取确认链接
- 做邮件 API
- 接数据库
- 推送到 Telegram / Discord / Webhook
- 给程序读取

如果你的目标是“让脚本和项目直接读邮件”，就别转发到普通邮箱，直接交给 Worker。

---

## 十一、第五步：开启 Catch-all

现在进入：

```text
Email
-> Email Routing
-> Routes
```

找到 `Catch-all address`。

然后：

1. 打开它，让状态变成 `Active`
2. 选择处理动作
3. 保存

处理动作可以是：

- Forward to destination address
- Send to Worker

### 推荐做法

如果你只想把各种随机地址收进 Gmail：

```text
Catch-all -> Forward to Gmail
```

如果你想做自动化邮箱系统：

```text
Catch-all -> Send to Worker
```

这一步就是“无限别名邮箱”能否跑起来的关键。

---

## 十二、第六步：普通转发模式怎么配

如果你只是想让自己的域名邮箱转发到一个真实邮箱，这里就是最短路径。

### 配置流程

1. 启用 Email Routing
2. 添加一个 Destination address
3. 完成 destination 验证
4. 新建一条 Custom address 或 Catch-all
5. Action 选 `Forward`
6. Destination 选你刚验证过的邮箱

### 例子

你可以这样配：

```text
newsletter@example.com -> yourname@gmail.com
billing@example.com -> yourname@gmail.com
Catch-all@example.com -> yourname@gmail.com
```

这样以后发到：

```text
anything@example.com
signup-test@example.com
random-2026@example.com
```

的邮件都能进你的 Gmail。

### 这条路线适合谁

适合：

- 普通收信
- 网站注册
- 订阅管理
- 个人邮箱分流

不太适合：

- 自动提取验证码
- 程序直接读邮件
- 搭内部邮箱 API

---

## 十三、第七步：自动化模式怎么配

如果你要的是“让程序直接读邮件”，就走这条。

推荐结构：

```text
Cloudflare Email Routing
        ↓
Catch-all
        ↓
Email Worker
        ↓
D1 / KV / R2 / Webhook / API
        ↓
你的程序或项目
```

最常见、最好用的落地方式是：

- `Email Worker` 负责接邮件
- `D1` 负责存邮件内容
- `fetch()` 负责暴露一个 HTTP API

这是最通用的模式。

---

## 十四、第八步：创建一个通用邮件 Worker

本地执行：

```bash
npm create cloudflare@latest mail-gateway-api
cd mail-gateway-api
npm i postal-mime
```

这里用 `postal-mime` 的原因很简单：

Cloudflare 给 Worker 的是原始邮件。  
我们通常需要把它解析成：

- `subject`
- `text`
- `html`
- `from`
- `to`

这样后面的 API、数据库和自动化逻辑都更容易做。

---

## 十五、第九步：创建 D1 数据库

先建库：

```bash
npx wrangler d1 create mail_gateway
```

记住返回的 `database_id`。

然后新建 `schema.sql`：

```sql
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  message_to TEXT NOT NULL,
  message_from TEXT,
  subject TEXT,
  text TEXT,
  html TEXT,
  received_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_to_time
ON messages(message_to, received_at DESC);
```

执行：

```bash
npx wrangler d1 execute mail_gateway --file=schema.sql
```

这套表结构已经足够应付绝大多数“自动收验证码 / 自动收通知”的场景。

---

## 十六、第十步：最小可用 Worker 示例

在 `src/index.ts` 里放一个最小版本：

```ts
import PostalMime from "postal-mime";

export interface Env {
  DB: D1Database;
  API_TOKEN: string;
}

function unauthorized() {
  return new Response("Unauthorized", { status: 401 });
}

function checkAuth(req: Request, env: Env) {
  const auth = req.headers.get("Authorization") || "";
  return auth === `Bearer ${env.API_TOKEN}`;
}

export default {
  async email(message: ForwardableEmailMessage, env: Env) {
    const parsed = await new PostalMime().parse(message.raw);
    const id =
      parsed.messageId ||
      `${String(message.to).toLowerCase()}-${Date.now()}-${crypto.randomUUID()}`;

    await env.DB.prepare(
      `INSERT OR REPLACE INTO messages
       (id, message_to, message_from, subject, text, html, received_at)
       VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)`
    )
      .bind(
        id,
        String(message.to).toLowerCase(),
        parsed.from?.address || "",
        parsed.subject || "",
        parsed.text || "",
        typeof parsed.html === "string" ? parsed.html : "",
        Date.now()
      )
      .run();
  },

  async fetch(req: Request, env: Env) {
    if (!checkAuth(req, env)) {
      return unauthorized();
    }

    const url = new URL(req.url);

    if (req.method === "GET" && url.pathname === "/messages") {
      const address = (url.searchParams.get("address") || "").trim().toLowerCase();
      if (!address) {
        return Response.json({ error: "missing address" }, { status: 400 });
      }

      const result = await env.DB.prepare(
        `SELECT id, message_to, message_from, subject, text, html, received_at
         FROM messages
         WHERE message_to = ?1
         ORDER BY received_at DESC
         LIMIT 20`
      )
        .bind(address)
        .all();

      return Response.json({
        messages: result.results || [],
      });
    }

    return new Response("Not found", { status: 404 });
  },
};
```

这段代码做了 2 件事：

### `email()`

Cloudflare 收到邮件后，会把邮件交给这里。  
这里负责解析邮件并写进 D1。

### `fetch()`

你的脚本、项目、后台、自动化程序，都可以通过：

```text
GET /messages?address=xxx@example.com
```

来读取某个邮箱地址最近收到的邮件。

---

## 十七、第十一步：配置 `wrangler.toml`

一个最小可用配置长这样：

```toml
name = "mail-gateway-api"
main = "src/index.ts"
compatibility_date = "2026-03-16"

[[d1_databases]]
binding = "DB"
database_name = "mail_gateway"
database_id = "replace-with-your-database-id"
```

再设置一个访问 API 用的 Bearer Token：

```bash
npx wrangler secret put API_TOKEN
```

输入一串足够长的随机字符串。

这个 token 的用途是：

**保护你的邮件读取 API，不让别人随便查。**

---

## 十八、第十二步：部署 Worker

执行：

```bash
npx wrangler deploy
```

部署完成后，你通常会得到一个地址，像这样：

```text
https://mail-gateway-api.xxx.workers.dev
```

这个地址以后可以给：

- 自动化脚本
- 项目配置
- 内部系统
- 管理后台

用来读取邮件内容。

---

## 十九、第十三步：把 Cloudflare 路由到 Worker

现在回到 Cloudflare Dashboard：

```text
Email
-> Email Routing
-> Routes
```

找到：

- 某个 Custom address
- 或者 Catch-all

把 `Action` 设成：

```text
Send to a Worker
```

然后选中你刚部署好的 Worker。

到这里，这套链路就齐了：

```text
任意别名地址来信
-> Cloudflare Catch-all 命中
-> Email Worker 接收
-> D1 保存
-> API 提供查询
```

---

## 二十、最常见的 4 种实际玩法

### 玩法 1：网站注册专用域名邮箱

比如你准备：

```text
signup.example.com
```

以后注册任何网站都用随机地址：

```text
reddit-001@signup.example.com
github-002@signup.example.com
shop-003@signup.example.com
```

这样做的好处：

- 不暴露主邮箱
- 一看地址就知道来源
- 哪个站泄露了邮箱很容易定位

### 玩法 2：自动化验证码收信

比如：

- 自动化注册脚本
- 测试环境注册流程
- QA 邮件验证流程

这类场景最适合：

```text
Catch-all -> Worker -> API
```

程序直接读 API，不用登录邮箱网页。

### 玩法 3：内部通知入口

你可以把不同系统通知发到不同别名：

```text
billing@notify.example.com
alarm@notify.example.com
backup@notify.example.com
```

再由 Worker 按主题、来源、目标系统分流。

### 玩法 4：临时一次性邮箱体系

你甚至可以在 Worker 里加上：

- 自动过期
- 定时清理
- 只保留最近 N 天
- 只允许指定发件人

这样就能把它做成一套自己的“临时邮箱系统”。

---

## 二十一、怎么验证你这套链路真的通了

推荐按下面顺序测试。

### 验证 1：人工发一封测试邮件

随便找一个会命中 Catch-all 的地址，比如：

```text
test-123@signup.example.com
```

从另一个邮箱给它发一封测试邮件。

注意：

Cloudflare 官方建议你不要从目标 destination 自己发给自己。  
有些邮箱提供商会把这种情况视为重复邮件，导致你误判链路有问题。

### 验证 2：如果你走普通转发模式

看 Gmail / Outlook / 企业邮箱里有没有收到。

### 验证 3：如果你走 Worker 自动化模式

用 curl 测试 API：

```bash
curl -H "Authorization: Bearer your-token" \
  "https://mail-gateway-api.xxx.workers.dev/messages?address=test-123@signup.example.com"
```

如果能返回 `messages` 数组，说明链路已经打通。

---

## 二十二、最常见的坑

### 1. 没开 Catch-all，却以为随机别名会自动生效

不会。

如果你没有显式创建每个地址，又没开 Catch-all，那大多数随机地址不会按你预期处理。

### 2. 主域名已经在跑别的邮箱，还强行上 Email Routing

这非常容易和现有 MX 冲突。

最稳做法还是：

**换一个专用子域名。**

### 3. 以为 Cloudflare 自带完整 inbox API

没有。

Cloudflare Email Routing 负责收信和处理流转；  
如果你要“按地址查邮件内容”，通常需要你自己做 Worker + D1 + API 这一层。

### 4. 忘了保护自己的邮件查询 API

如果你暴露了 `/messages?address=...` 这种接口，一定要加认证。

最简单的就是：

- `Authorization: Bearer ...`

更进一步还可以加：

- Cloudflare Access
- IP 白名单
- 内部网络限制

### 5. 把 Subaddressing 当成 Catch-all

这两个不是一回事。

- `user+tag@example.com` 适合固定地址加标签
- Catch-all 适合接住完全随机的地址

---

## 二十三、这套方案的限制和现实边界

为了避免把“无限别名”误解成“完全无限”，这里把边界说清楚。

### 1. Cloudflare 仍然有官方限制

例如：

- Routing rules 默认 `200`
- Addresses 默认 `200`
- 邮件大小上限 `25 MiB`
- Worker 资源限制

所以不要把“无限”理解成平台侧完全没有任何资源边界。

### 2. 真正“无限”的是别名管理成本

这套方案真正厉害的地方不是：

“平台什么都无限”

而是：

### 你不再需要人工维护成百上千个真实邮箱账号。

你只要：

- 一个域名或子域名
- 一条 Catch-all
- 一套 Worker 处理逻辑

就能把大量随机地址收进来。

---

## 二十四、如果你只是想最快跑通，最推荐这样做

直接用这套最小组合：

1. 一个子域名，例如 `signup.example.com`
2. 开启 Email Routing
3. 开启 Catch-all
4. Catch-all 指向 Email Worker
5. Worker 把邮件写到 D1
6. Worker 暴露 `GET /messages?address=...`

这已经足够支持：

- 注册机
- 自动化收验证码
- 测试环境收信
- 一次性别名邮箱
- 内部通知系统

---

## 二十五、作为示例：怎么接进本仓库项目

虽然本文是通用教程，但顺手给一个仓库内示例，方便你对照理解。

如果你要把这套通用方案接进本仓库项目，项目里主要读取的是这些环境变量：

```env
EMAIL_PROVIDER=cloudflare
EMAIL_API_URL=https://mail-gateway-api.xxx.workers.dev
EMAIL_API_TOKEN=your-worker-token
EMAIL_DOMAIN=signup.example.com
```

如果你准备多个域名，也可以：

```env
EMAIL_PROVIDER=cloudflare
EMAIL_API_URL=https://mail-gateway-api.xxx.workers.dev
EMAIL_API_TOKEN=your-worker-token
EMAIL_DOMAINS=signup.example.com,verify.example.com
```

在这个仓库里，它们最终会驱动：

- 生成随机邮箱地址
- 调用你自己的 `/messages` API
- 提取验证码和验证链接

但这只是本文的一个应用场景，不是本文的前提。

---

## 二十六、官方参考资料

下面这些是这次改写时重点对照的 Cloudflare 官方文档：

- [Overview](https://developers.cloudflare.com/email-routing/)
- [Enable Email Routing](https://developers.cloudflare.com/email-routing/get-started/enable-email-routing/)
- [Configure Rules and Addresses](https://developers.cloudflare.com/email-routing/setup/email-routing-addresses/)
- [Subdomains](https://developers.cloudflare.com/email-routing/setup/subdomains/)
- [Enable Email Workers](https://developers.cloudflare.com/email-routing/email-workers/enable-email-workers/)
- [Email Workers](https://developers.cloudflare.com/email-routing/email-workers/)
- [Runtime API](https://developers.cloudflare.com/email-routing/email-workers/runtime-api/)
- [Limits](https://developers.cloudflare.com/email-routing/limits/)
- [Test Email Routing](https://developers.cloudflare.com/email-routing/get-started/test-email-routing/)

---

## 二十七、最后一句最实用的话

如果你想搭一套真正能长期复用的“无限别名域名邮箱”系统，最稳的方案不是：

“在后台手工建一堆邮箱”

而是：

### Cloudflare Email Routing + Catch-all + Email Worker + 一个你自己的读取接口

这套东西一旦搭好，后面无论你是给注册脚本、测试平台、自动化系统、通知中心，还是像本仓库这种项目接入，都可以直接复用。
