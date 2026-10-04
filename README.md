# 飞书短信验证码桥接 Demo

把你现在的流程接起来：**手机短信 → 短信转发器 → 短信机器人发到飞书群 → 每日报表机器人后端取得验证码 → 继续下载报表**。人工复制验证码并 @ 每日报表机器人的步骤由程序替代。

这是可运行的独立 Python 示例，附带给另一个 AI 的集成说明。它不会替你重新实现各平台的报表下载逻辑。真实接入需要你填写飞书应用凭据、群 ID、短信机器人的来源 ID 和短信匹配规则；这些值没有写进交付包。

## 先跑离线演示

Python 3.12，离线演示和轮询入口无需安装第三方库。解压后进入本目录。

Windows PowerShell，沿用你项目的固定 Python 解释器路径：

```powershell
& "C:\Users\win\AppData\Local\Programs\Python\Python312\python.exe" -m otp_bridge demo
```

Linux / macOS：

```bash
python3 -m otp_bridge demo
```

演示会登记等待任务、注入模拟短信机器人的消息、验证事件和轮询消息去重、把验证码填入模拟表单。最后出现 `"ok": true`。演示使用的是虚构验证码，不会连接飞书或发送任何消息。

## 真实的两个机器人怎么接通

接收方应是开启机器人能力的**企业自建应用**，可以直接复用“每日报表机器人”所属应用。短信发送方可以继续使用你现有的群 Webhook 机器人。

| 入口 | 适用场景 | 代码入口 |
| --- | --- | --- |
| 原生长连接事件 | 每日报表后端已经接收飞书事件；实时把短信机器人的消息交给等待任务 | `OtpBridge.feed_event()` + `OtpBridge.wait()` |
| 群历史轮询 | 想先做独立测试，或暂时不改现有机器人的事件接收器 | `PollingSource.wait()` |

**本场景推荐“包含机器人消息的全部群消息”事件权限**，因此短信转发器不必额外添加 @。不要把它与旧的“全部用户消息”权限混淆。具体权限与配置步骤见 [FEISHU_SETUP.md](docs/FEISHU_SETUP.md)，依据见 [SOURCES.md](docs/SOURCES.md)。

如果你的“每日报表机器人”只有一个群 Webhook URL，没有应用凭据和可接收事件的后端，Webhook 本身不能充当接收器：让下载脚本接本示例的轮询入口，或配置一个企业自建应用作为接收身份。

## 做一次真实群内测试

完整步骤见 [FEISHU_SETUP.md](docs/FEISHU_SETUP.md)：

1. 将接收应用机器人加入短信所在的测试群，开通权限并发布应用版本。
2. 复制 `config.example.json` 为 `config.json`，填群 ID。
3. 设置 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`。先运行 `inspect` 获取**发送方**真实身份，再填 `trusted_senders`。
4. 运行 `wait --route test_sms`，随后用短信机器人的 Webhook 发送一条带测试标记的假验证码。
5. 接收终端输出 `"ok": true` 和掩码验证码，表示群消息已交给报表接收逻辑。

```bash
# 先查看短信机器人实际身份，不打印短信正文
python3 -m otp_bridge inspect --config config.json --transport poll

# 原生事件模式需安装官方 SDK
python3 -m pip install -r requirements-websocket.txt
python3 -m otp_bridge inspect --config config.json --transport ws

# 测试接收二选一；事件模式需等飞书控制台显示长连接建立后再发消息
python3 -m otp_bridge wait --config config.json --transport poll --route test_sms
python3 -m otp_bridge wait --config config.json --transport ws --route test_sms

# 另一个终端执行；这条命令会向配置的短信机器人 Webhook 发一条假验证码
python3 examples/send_test_sms.py
```

发送测试消息需要另外设置 `FEISHU_SMS_WEBHOOK_URL`，如果该群机器人启用了签名校验，还需要 `FEISHU_SMS_WEBHOOK_SECRET`。接收程序不需要这两个变量。

`test_sms` 路由只接受 `OTP_BRIDGE_TEST` 与 `demo-account-8888` 标记。它和真正下载报表用的 `douyin_shop_b` 路由分开；真实下载测试应由平台实际发送短信，经手机短信转发器进入群。

WebSocket CLI 是单个等待窗口的烟雾测试，成功或超时后仍保持连接，按 Ctrl+C 结束。持续处理真实任务应按下面的集成示例接到现有后台。

## 给另一个 AI 看哪些文件

先读 [AI_INTEGRATION.md](AI_INTEGRATION.md)，再选择与现有项目一致的示例：

- [report_integration.py](examples/report_integration.py)：现有下载脚本直接轮询取得验证码。
- [existing_event_handler.py](examples/existing_event_handler.py)：复用每日报表机器人的事件接收器。
- [FEISHU_SETUP.md](docs/FEISHU_SETUP.md)：配置凭据、权限、群、发送方身份与测试命令。
- [TEST_REPORT.md](docs/TEST_REPORT.md)：本次已完成的验证及尚未执行的真实环境验证。

现有下载脚本主要替换这一步：

```python
ticket = bridge.arm(route)       # 必须先登记等待，再触发短信
try:
    trigger_existing_sms_step()
    result = source.wait(ticket) # 轮询模式；事件模式使用 bridge.wait(ticket)
    existing_submit_code(result.code)
finally:
    bridge.cancel(ticket)
```

事件模式中，`bridge` 必须是事件接收器与下载任务共享的同一个对象。异步、多进程及并发店铺接入的注意事项见 AI 文档。

## 已实现的行为与边界

- 只匹配指定群、白名单短信机器人、全部路由关键词；忽略普通用户的聊天消息。
- 使用消息 ID 去重；同一条消息最多交给一个任务，多个可能任务同时匹配时拒绝猜测。
- 只接受等待窗口建立后到达、且未过期的消息。单个路由只能有一个等待任务。
- 解析文本、富文本及常见卡片文字；图片验证码和未覆盖的卡片结构不解析。
- 正则提取明确带验证码标签的 4～8 位数字；一条消息有多个不同验证码时不选择其中一个。
- 验证码只在内存中交给现有代码，默认输出掩码；不写入文件，也不传给模型。
- 使用官方 SDK 接收长连接事件；轮询使用官方历史消息接口，含分页、短时失败重试、令牌缓存与刷新。

这份示例的任务状态保存在**单个进程的内存**，没有独立 HTTP 服务、跨进程队列或重启恢复机制。不同账号的短信如果本身不能区分，就必须由调度器串行发送验证码；修改路由名称不能增加短信里不存在的账号信息。

飞书消息时间代表“进入群的时间”，不一定等于短信实际接收时间。手机可能把积压的旧短信新转发到群；严格场景要让转发模板附带原始短信时间，并在接入项目时增加时间校验。主机时钟也需要准确。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

未安装官方 SDK 时，SDK 兼容性测试会跳过，其余测试照常执行。安装后可运行全部测试。详细结果见 `docs/TEST_REPORT.md`。
