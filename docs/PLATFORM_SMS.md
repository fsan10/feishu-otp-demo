# 京东、快手、抖店真实短信接入

依据用户提供的五条短信制定规则。代码保留原始大小写和前导零，允许 4～8 位 ASCII 字母/数字。这个长度范围覆盖目前样例，不代表平台对所有短信的官方长度保证；出现新的格式时，应补充样例再调整。

| 用途 | 后台 route_id | 短信标记 | 样例提取结果 |
| --- | --- | --- | --- |
| 京东加密导出文件密码 | jd_archive_password | 【京东】、以taskid-、加密导出文件、密码（区分大小写） | KkTa3q |
| 快手订单导出验证码 | kuaishou_export_otp | 【快手小店】、验证码、正申请导出订单 | 2c19 |
| 快手文件提取码 | kuaishou_extract_code | 【快手小店】、提取码、正申请文件提取码 | b96566 |
| 抖店订单验证码 | douyin_order_otp | 【抖店】、验证码 | 3762 |
| 抖音商城导出文件解压密码 | douyin_archive_password | 【抖音商城】、订单导出文件已加密、解压密码 | vGCPMK |

## 手机转发规则

1. 匹配字段选择「短信内容」。
2. 匹配模式选择「正则匹配」。
3. 将 [mobile_sms_match_regex.txt](mobile_sms_match_regex.txt) 的整行内容复制到「匹配的值」。直接粘贴，不加引号、不加 / 分隔符、不将反斜杠加倍。
4. 启用自定义模板，填写 `{{SMS}}`。关闭「启用正则替换内容」，保持原始短信完整。
5. 选择已经能发消息的飞书 Webhook 通道，保存并启用规则。停用重叠的旧「包含验证码」规则，避免一条短信转发两次。
6. 检查「免打扰（禁用转发）」时间和星期是否覆盖实际运行时段；夜间任务需要允许转发。

短信内容变量 `{{SMS}}` 见 [SmsForwarder 官方变量说明](https://github.com/pppscn/SmsForwarder/wiki/附录3：自定义模板可用变量)。匹配模式见 [官方转发规则说明](https://github.com/pppscn/SmsForwarder/wiki/3.转发规则)。没有在用户手机上执行规则，仍需手机规则测试和一条真实短信联调。

## 飞书 Webhook 通道

POST，Header 为 `Content-Type: application/json; charset=utf-8`，消息模板：

```json
{"msg_type":"text","content":{"text":"[msg]"}}
```

通道的 `[msg]` 是规则生成的正文，规则中的 `{{SMS}}` 是手机原始短信。移除先前通道模板中的固定「验证码」前缀。

若飞书机器人采用关键词校验，可配置「京东」「快手小店」「抖店」「抖音商城」为允许的关键词，满足任意一个即可（见 [飞书自定义机器人指南](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot)）。只允许「验证码」会阻止京东密码和抖店解压密码短信。手机端签名问题需另外处理，不由短信正则解决。

## 后台接收

项目 config.json 已追加表中的五个路由，现有 test_sms 保留用于合成测试。真实短信不需要 OTP_BRIDGE_TEST 和 demo-account-8888。

开始等待后，再到相应平台触发短信。例如：

```powershell
python -m otp_bridge wait --config config.json --transport poll --route kuaishou_export_otp
python -m otp_bridge wait --config config.json --transport poll --route kuaishou_extract_code
python -m otp_bridge wait --config config.json --transport poll --route douyin_order_otp
python -m otp_bridge wait --config config.json --transport poll --route douyin_archive_password
```

一次执行所需的一条命令。默认输出 ok、route_id 和 code_masked；后端从 `result.code` 获取原始字符串。字母不转换大小写，数字不转整数。

京东能取得当前导出任务编号时，必须绑定它：

```powershell
python -m otp_bridge wait --config config.json --transport poll --route jd_archive_password --task-id taskid-106467192356
```

这里的编号仅演示格式，实际运行换成当前文件的编号；不能长期固定这个值。尚未取得 taskid 时可省略参数，但同一短信流的京东任务必须串行，无法仅凭「京东密码」辨认是哪份文件。

在现有后端中：

```python
route = load_route(settings, "jd_archive_password", task_id=current_task_id)
ticket = bridge.arm(route)  # 在触发短信之前登记
try:
    trigger_sms()
    result = source.wait(ticket)
    submit_password(result.code)  # 原样传入，不做 lower/upper/int
finally:
    bridge.cancel(ticket)
```

如果 taskid 已存在但没有绑定，时间窗口只能减少错配，不能证明密码属于某份文件。快手和抖店样例没有店铺/手机号标识：同一短信流内多个店铺的同种用途必须串行；路由名称不能提供短信中不存在的身份信息。抖店验证码样例也不能区分订单验证与登录验证，需避免这类请求重叠。

后台仍验证指定群、实际发送机器人的白名单身份、用途关键词、新消息时间和有效期。一条短信含多个不同匹配码，或多个任务同时匹配时，会拒绝选择。识别未知格式失败时应超时并由任务处理，不自动猜测。

保留完整短信是必要的：只转发 KkTa3q、2c19 等会丢失平台、用途、京东 taskid，现有路由无法据此可靠分配任务。短信中的日期、手机号、taskid 不作为验证码候选，只有明确标签后面的代码参与提取。

## 本次离线核对（2026-10-10）

使用用户提供的五条短信执行了 127 项内存断言，全部通过：手机正则（Python 正则引擎）、默认及路由专用提取、模拟飞书历史/事件入口、五种用途同时等待的分配、去重、京东 taskid 绑定、大小写及前导零保留、手机号/日期干扰排除、过长或非 ASCII 代码拒绝。另检查了 CLI 帮助和 Git 差异格式。没有新增测试文件，没有联网发送群消息，也未在手机或平台上执行真实短信联调。

随后运行了项目现有的 47 个测试：46 个通过，1 个官方 SDK 测试因未安装可选 lark-oapi 而跳过。未新增测试文件。
