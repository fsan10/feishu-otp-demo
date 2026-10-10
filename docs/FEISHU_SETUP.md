# 飞书配置与真实测试步骤

## 1. 确认机器人身份

短信转发器使用的群机器人通常通过 `https://open.feishu.cn/open-apis/bot/v2/hook/...` 发消息。保留这个发送端即可。

接收端复用“每日报表机器人”的**企业自建应用**，开启机器人能力，并把它加入同一个测试群。如果目前只有一个通知 Webhook，则需要一个应用身份才能订阅或读取消息；Webhook URL 不是 App ID / App Secret。

使用普通内部对话群做测试，先让两个机器人都在群中，再发送新的测试消息。历史接口的权限和群可见性还会影响能读取的记录；保密群和外部群可能有额外限制。不要用话题回复测试本例的历史轮询，本例查询的是 `chat` 容器。

## 2. 按入口开通权限

| 入口 | 所需配置 | 为什么 |
| --- | --- | --- |
| 长连接，短信无需 @ | `im:message.group_msg.include_bot:read`；订阅 `im.message.receive_v1` | 非 @ 的短信机器人群消息可进入接收事件 |
| 长连接，仅明确 @ 接收机器人 | `im:message.group_at_msg.include_bot:readonly`；同一消息事件 | 可以收其他机器人真正 @ 接收方的消息；本例不依赖这条路线 |
| 读取群历史 | `im:message:readonly` + `im:message.group_msg` | 官方历史消息接口的应用身份读取组合；接收机器人必须在群中 |

**不要把 `im:message.group_msg` 当成事件入口接收机器人消息的权限。** 事件入口需要带 `include_bot` 的对应权限。历史读取的权限组合以该接口文档及实际返回的缺权限信息为准；若你的租户提示额外权限，按提示补齐并重新发布，不能靠忽略错误解决。

本 demo 的接收端不发送群回复，因此不要求为了接收验证码申请发消息权限。若你后续保留已有报表通知功能，沿用项目本来所需的发送权限。

长连接配置：

1. 在应用里开启机器人能力。
2. 添加本入口需要的应用身份权限。
3. 在“事件与回调”中选择“使用长连接接收事件”，添加“接收消息 v2.0”，事件标识为 `im.message.receive_v1`。
4. 创建并发布含最新权限、事件和能力的版本，使配置生效。
5. 把已发布应用的机器人加入目标群，确认可用范围包含测试账号。

如果现有每日报表后端已运行该应用的长连接，不要同时启动本 CLI 的第二条长连接。应在现有接收器挂载 `bridge.feed_event()`，或用轮询 CLI 单独测试。

## 3. 设置凭据和群 ID

复制配置：

```powershell
Copy-Item config.example.json config.json
```

将 `chat_id` 改成实际群 ID，例如 `oc_...`。群名称或群邀请链接不能代替 ID。可从已有机器人收到的人类消息事件的 `message.chat_id`、项目配置或官方 API 调试台获得。

在项目根目录创建本地 `.env` 文件。程序会自动读取它；`.env` 已被 Git 忽略。下面都是占位值：

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

在文件中填写接收应用凭据：

```dotenv
FEISHU_APP_ID=cli_你的接收应用ID
FEISHU_APP_SECRET=你的接收应用Secret
```

运行 `inspect`、`wait` 或示例脚本时，程序会加载 `.env` 中支持的变量。已经由当前进程设置的同名环境变量优先；不要把真实凭据写入 `config.json` 或提交到 Git。

要运行发送假短信的示例，再填写原短信群机器人的 Webhook；只有机器人启用了签名校验时才填写 Secret：

```dotenv
FEISHU_SMS_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/你的Webhook
FEISHU_SMS_WEBHOOK_SECRET=你的签名Secret
```

## 4. 获取短信发送方身份

不要用机器人显示名称匹配。历史和事件的 sender 字段结构不同，请用将要接入的入口观察实际消息。

### 历史入口

先让短信转发器发送一条测试短信消息，再执行：

```powershell
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m otp_bridge inspect --config config.json --transport poll
```

它读取最近十分钟消息，仅打印 ID、来源类型、时间和是否含可读文字，不打印短信正文。

参考输出（虚构 ID）：

```json
{"message_id":"om_example","chat_id":"oc_example","sender_type":"app","sender_ids":[{"id_type":"app_id","id":"cli_example_sms_sender"}],"created_ms":1800000000000,"has_visible_text":true}
```

把观察到的**短信机器人** `id_type` 和 `id` 原样填入配置 `trusted_senders`。不要把每日报表接收应用自身的 App ID 填进去。

### 事件入口

安装官方 Python SDK：

```powershell
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m pip install -r requirements-websocket.txt
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m otp_bridge inspect --config config.json --transport ws
```

等开放平台显示长连接建立后，再让短信机器人发一条测试消息。CLI 输出其实际来源信息，然后 Ctrl+C 退出。

参考输出（虚构 ID）：

```json
{"message_id":"om_example","chat_id":"oc_example","sender_type":"bot","sender_ids":[{"id_type":"open_id","id":"ou_example_sms_sender"}],"created_ms":1800000000000,"has_visible_text":true}
```

该入口把来源 `open_id` 填入配置。只使用一种入口时，删掉另一个入口的占位身份；使用两种入口时，可以保留各自已观察并确认的真实身份。`header.app_id` 是接收应用，不是发送方。

如果 `inspect` 完全看不到你新发的短信机器人消息，先核查权限是否含机器人来源、是否发布、两机器人是否同群，以及脚本连接的应用是否正确。不要把短信机器人身份伪造成普通用户来骗过过滤条件。

## 5. 用假验证码测试机器人互通

打开接收终端，使用独立测试路由：

```powershell
# 轮询方式，无第三方依赖
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m otp_bridge wait --config config.json --transport poll --route test_sms

# 或原生事件方式，需官方 SDK；不要同时执行两种等待命令
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m otp_bridge wait --config config.json --transport ws --route test_sms
```

轮询模式等终端出现 `Waiting for a NEW SMS` 后发消息；事件模式等飞书控制台显示长连接建立后发消息。等待窗口默认 120 秒。

在另一个终端配置**原短信机器人的** Webhook：

```powershell
$env:FEISHU_SMS_WEBHOOK_URL = "https://open.feishu.cn/open-apis/bot/v2/hook/你的原短信机器人Webhook"
# 只有启用了签名校验时设置这一项
$env:FEISHU_SMS_WEBHOOK_SECRET = "你的群机器人签名Secret"
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" examples/send_test_sms.py
```

发送脚本只发这一条虚构短信：

```text
OTP_BRIDGE_TEST
demo-account-8888
验证码：123456（仅测试，非真实平台验证码）
```

群机器人启用了自定义关键词时，要保证这条测试正文包含允许的关键词；可在测试群中使用“验证码”这一关键词。启用了 IP 限制时，发送机器必须属于允许的来源。签名算法按飞书自定义机器人文档实现。

接收端输出 `"ok": true`、`"route_id": "test_sms"` 与 `"code_masked": "******"`，就证明同群短信机器人消息进入了报表接收后端。`--show-code` 是显式调试选项，默认不打印验证码。

这个测试不会调用真实平台导出接口。要证明**手机短信转发链路**也正常，还需要执行下一步。

## 6. 接入真实短信与报表任务

京东、快手、抖店的五类真实短信已提供正式路由和手机正则，按 [PLATFORM_SMS.md](PLATFORM_SMS.md) 配置即可；以下 `douyin_shop_b` 是带虚构账号标记的旧演示路由。

在已知可区分账号的前提下，修改 `douyin_shop_b.required_keywords`，使它们确实出现在短信正文或可信转发模板里。示例里的平台、店铺和掩码手机号是演示字段，不保证你的转发器默认带这些字段。

通常至少需要平台或业务关键词，以及能区分接收手机号/账号的标记。一个手机号接收同平台多个店铺短信且正文没有账号信息时，调度器必须让这些导出验证码任务串行执行；不要固定给所有短信贴一个店铺名。

如果转发器支持自定义消息模板，可以为固定来源附加实际手机号标记及原始短信接收时间。具体模板变量随你使用的短信转发器及版本而变化，此 demo 不假设某个变量名。

把原有下载脚本的“人工等验证码”位置替换成 `examples/` 中的对应模式。任务先登记、平台再发短信；消息由手机转发进群后，后端自动取得 `result.code` 并继续提交。集成步骤、并发约束和异步示例见 `AI_INTEGRATION.md`。

## 7. 常见排查

| 现象 | 重点检查 |
| --- | --- |
| 人 @ 机器人能收到，短信机器人不能收到 | 是否仍是只包含用户来源的事件权限；是否开通 include_bot 并发布 |
| 收到事件但验证码任务不动 | 是否在代码前部过滤了 `sender_type="bot"`；是否强制要求 @；回调与任务是否使用同一 broker |
| inspect 能看到消息，但 wait 超时 | 正确 sender 身份、全部关键词、消息发送时间是否在 arm 之后、主机时钟及验证码正则 |
| 历史查询返回 230002 | 接收机器人不在该群，或配置了其他群 ID |
| 返回 230006 | 机器人能力未生效，检查能力与发布版本 |
| 返回 230027 / 99991672 | 缺少本入口权限或授权尚未生效；按平台返回的权限要求核实 |
| 测试消息发送失败 | 原短信 Webhook、签名 Secret、群关键词限制、IP 限制与网络 |
| 多实例偶发收不到 | 同应用重复启动长连接、回调与等待任务处于不同进程，或任务被并发抢占 |
| 卡片不提取 / has_visible_text=false | 用脱敏卡片样本扩展可读文字提取；不要递归提取所有 ID 和 URL 中的数字 |
| 一条消息匹配多个任务 | 路由条件重叠，停止猜测并改为明确区分或串行执行 |

程序异常只输出 HTTP 状态、错误码和非敏感提示。排查时不要直接打印整个事件、短信正文或带 token 的 Webhook URL。
