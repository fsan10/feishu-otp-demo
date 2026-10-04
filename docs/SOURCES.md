# 实现依据

核实日期：2026-10-04。本 demo 自行编写，没有复制第三方项目代码。飞书在线文档可追加 `.md` 读取纯 Markdown；本次已直接读取官方原文并核对下列行为。

1. [飞书官方：接收消息](https://open.feishu.cn/document/server-docs/im-v1/message/events/receive)
   - 分别提供“包含机器人来源的群消息”和“包含机器人 @ 的群消息”权限。普通用户来源的群消息权限不能代替它们。
   - 事件标识保持为 `im.message.receive_v1`；重推时按 `message_id` 去重；来源需从 sender 字段读取。
2. [飞书官方：获取会话历史消息](https://open.feishu.cn/document/server-docs/im-v1/message/list)
   - 使用 `/open-apis/im/v1/messages`；群读取要求机器人在群内及相应权限。
   - 时间筛选用秒，消息生成时间用毫秒；每页上限 50，需处理 `page_token`；本例请求原始卡片结构进行文字提取。
3. [飞书官方：自定义机器人使用指南](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot)
   - 群 Webhook 负责发送通知；与可接收事件的应用机器人能力不同。假短信发送脚本采用该指南的签名约定。
4. [飞书官方 Python SDK](https://github.com/larksuite/oapi-sdk-python)
   - 原生长连接使用 `lark-oapi`，没有手工实现 WebSocket 二进制协议。本次验证版本为 1.7.3。
5. [SmsForwarder 项目](https://github.com/pppscn/SmsForwarder)
   - 可将短信转发到飞书、Webhook 等渠道；这只是候选项目参考，用户尚未确认其手机上的短信转发器就是这个仓库。本 demo 以群内实际消息为输入，不依赖它的内部代码或固定模板变量。

飞书 API 在线说明和租户实际权限界面可能更新。接入时以接收应用实际可申请的权限、发布状态、经过脱敏的真实消息结构及平台错误码为准。
