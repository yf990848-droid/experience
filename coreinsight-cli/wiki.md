coreinsight-cli 使用指南
coreinsight-cli 是面向 AI Agent / 脚本的 Core Insight 命令行工具：Go 1.21、零第三方依赖、本地 Cookie 会话、JSON-RPC 2.0 输出。它把"登录、知识问答/检索、Skill 管理、经验检索/上传"封装成一条条命令，输出固定为 JSON，便于脚本与 Agent 稳定消费。

本指南面向使用者，说明 CLI 的能力范围、核心概念、快速上手步骤、各命令的用法与参数、全局配置方式，以及常见问题的排查方法。

目录
一、能力总览
二、快速上手
三、核心概念
四、登录
五、知识问答 / 检索（rag）
六、Skill（skill）
七、经验（experience）
八、全局参数与环境变量
九、输出格式与退出码
十、常见问题
一、能力总览
命令	作用	后端服务	是否需登录
auth login/logout/status	登录、清除会话、查看本地认证状态	IDaaS 门户	否
rag	知识问答（--qa）或纯检索（--retrieve）	Chat 服务	是
skill scenes	按代码仓查询产品与对应场景	Core Harness + Chat	是
skill search / scene-search	Skill 智能检索	AI Community	是
skill download	按 Skill ID 下载 ZIP	AI Community	是
skill upload / verify	上传 / 校验 Skill ZIP	AI Community	是
experience search	检索经验	Chat 服务	是
experience upload	贡献经验	Chat 服务	是
version	版本信息	本机	否
登录前置要求：rag、skill、experience 的所有业务命令（包括 skill search 等后端不校验 Cookie 的子命令）都必须在本地存在有效登录会话后才能执行。未登录或会话过期时，命令在发出任何网络请求前即被拦截，返回 JSON-RPC 错误 -32002 Not Authenticated，退出码为 3；显式传入的 --user_id / --caller_id 不能绕过。auth、version 及所有 --help 帮助输出不受此限制。

二、快速上手
三步走完从零到第一次检索：

# 1. 构建
go build -o coreinsight-cli ./cmd/coreinsight-cli

# 2. 登录（域账号，交互式输入密码；密码不会回显）
coreinsight-cli auth login --username <域账号>

# 3. 第一笔业务命令（纯检索）
coreinsight-cli rag --retrieve --query "问题" --departments "分组核心网产品部"
​
登录后，caller_id / user_id 等身份字段默认使用登录工号，无需重复传入。要了解某命令的参数，随时在命令后加 --help。

三、核心概念
本地会话：auth login 成功后，从响应 Set-Cookie 提取 Cookie 与过期时间，保存到 ~/.coreinsight-cli/session.json（目录权限 0700、文件 0600）。后续业务命令自动携带该 Cookie，会话过期后需重新 auth login。
身份工号：登录用户名即用户工号，默认填充到需要身份参数的接口（如 rag 的 user_id、experience search 的 caller_id、experience upload / skill download 的 user_id）。显式传入的 --user_id / --caller_id 优先于登录工号。
JSON-RPC 2.0 输出：所有命令的 stdout 输出固定为 JSON-RPC 结构，含 jsonrpc、result/error、id；error.code 为负数，便于脚本判断。
退出码：0 成功；1 参数错误/后端/网络失败；3 未认证或会话过期（业务命令被登录校验拦截）。
读写区分：upload 类命令是写操作，会真实写入后端；search/scenes/status 等为只读操作。
四、登录
认证能力只有一个入口 auth，支持三个子命令。

auth login
作用：向华为 IDaaS 门户发起登录，成功后建立本地会话。

参数（优先级从高到低标注）：

参数	说明	优先级
--body-file <file> / --body <json>	直接使用原始 JSON 请求体，兼容旧调用	最高
--username/-u	域账号用户名	次高
--password/-p	密码（命令历史可见，脚本慎用）	中
--password-stdin	从标准输入读取密码，密码不进命令历史	中
（无参数，交互终端）	逐行提示输入用户名与密码	最低
示例：

# 交互式登录（推荐）
coreinsight-cli auth login --username s00012345

# 脚本 / CI 推荐：密码不进历史
printf '%s\n' "$PASS" | coreinsight-cli auth login --username U --password-stdin

# 环境变量方式（测试友好）
set COREINSIGHT_AUTH_USERNAME=U
set COREINSIGHT_AUTH_PASSWORD=P
coreinsight-cli auth login
​
登录用户名来源依次为：--username/-u → COREINSIGHT_AUTH_USERNAME（兼容 OMRES_AUTH_USERNAME）→ 交互输入。密码来源依次为：--password-stdin → --password/-p → COREINSIGHT_AUTH_PASSWORD（兼容 OMRES_AUTH_PASSWORD）→ 交互式无回显输入。

auth status
作用：查看本地认证状态，0 已认证，3 未认证或会话过期。会输出用户名、Cookie（脱敏）、会话文件路径等。

auth logout
作用：清除本地会话文件，之后业务命令将回到"未认证"拦截态。

coreinsight-cli auth status
coreinsight-cli auth logout
​
五、知识问答 / 检索（rag）
rag 同时提供问答与纯检索两种模式，通过互斥开关区分，二者必须指定其一且不能同时指定：

模式开关	说明
--qa	知识问答，走问答接口
--retrieve	纯检索，返回知识片段，不发答案
路由参数四选一：--kb_sns / --products / --departments / --scenes，多个值用逗号分隔。

示例：

# 问答模式
coreinsight-cli rag --qa --query "如何配置SDD" --kb_sns 123,456 --prompt_template SDD

# 纯检索模式
coreinsight-cli rag --retrieve --query "问题" --products UPCF,UDG
​
--user_id 默认取登录工号，也可显式指定；--prompt_template 仅问答模式使用。

六、Skill（skill）
skill 有 6 个子命令，覆盖"查场景、检索、下载、上传/校验"全流程。

1. skill scenes 查询产品场景
作用：读取当前 git 仓库的 remote url，查询对应产品列表，再逐个查询场景。

cd /path/to/repo
coreinsight-cli skill scenes --repo .
​
必须传入 --repo <git 仓库目录>；该目录必须是 git 仓库（依赖 git remote get-url origin）。

2. skill search / scene-search 检索
skill search 走 AI Community 智能检索；scene-search 使用相同接口，且支持用产品/场景参数拼成关键词。

coreinsight-cli skill search --query "数据库" --page 1 --page_size 6 --sort_by downloads --sort_order desc

# 场景搜索也走智能检索
coreinsight-cli skill scene-search --query "333"

# 兼容旧参数：product + first_scene + second_scene 空格拼接为 keyword
coreinsight-cli skill scene-search \
  --product "UNC USMF" --first_scene "需求开发" --second_scene "MML开发"
​
参数：--query（关键字）、--page（默认 1）、--page_size（默认 6）、--sort_by（默认 downloads）、--sort_order（默认 desc）。scene-search 未提供 --query 时按"产品→一级场景→二级场景"顺序拼接关键词。

3. skill download 下载
作用：先向 AI Community 获取下载地址，再用普通 GET 下载 ZIP。

coreinsight-cli skill download \
  --skill_id "bca61fb0-3734-49c0-906e-0209d17032fd" \
  --version "0.0.1" \
  --output ./skills
​
参数：--skill_id（必填）、--version（可选）、--output（下载目录，默认 ./skills）、--user_id（默认登录工号，作为 userId 查询参数）。

4. skill upload / verify 上传与校验
作用：上传 Skill ZIP；verify 走解析校验接口，不真正入库。

coreinsight-cli skill upload --file ./skill.zip --business_dimension "产品级"
coreinsight-cli skill verify --file ./skill.zip --business_dimension "产品级"
​
参数：--file（必填，Skill ZIP 路径）、--business_dimension（业务维度）、--user_id（默认登录工号）。

七、经验（experience）
1. experience search 检索经验
作用：按标题/补充检索文本/场景检索经验，支持按贡献者、部门、产品过滤。

# 基本检索（默认按 title 字段检索）
coreinsight-cli experience search \
  --query "智能客服系统" \
  --scene ALL \
  --page 1 \
  --page_size 5

# 指定检索字段为 rag_search_text（按补充检索文本检索）
coreinsight-cli experience search \
  --query "智能客服系统" \
  --search_field rag_search_text \
  --scene ALL

# 按部门过滤（多个用逗号分隔）
coreinsight-cli experience search \
  --query "智能客服系统" \
  --departments "云核心网维护部,网络产品部"

# 按产品名称过滤（多个用逗号分隔）
coreinsight-cli experience search \
  --query "智能客服系统" \
  --products "UPCF,UDG"
​
参数：

参数	说明
--query	查询文本，必填
--search_field	检索字段，默认 title（按标题检索）；可指定 rag_search_text（按补充检索文本检索）
--scene	场景名，默认 ALL
--user_id	按贡献者工号过滤经验；未指定则检索所有用户的经验
--caller_id	调用方工号，默认用登录工号
--departments	部门名称，逗号分隔多个；后端映射 product.pdu_name 过滤
--products	产品名称，逗号分隔多个；后端映射 product.product_name 过滤
--page / --page_size	分页，默认 1 / 5
--search_field 不指定时默认 title，保持与旧行为一致；指定时按指定字段检索。

--user_id 只过滤目标贡献者，不会改变调用方工号；--caller_id 才是调用方身份。
--departments 与 --products 可同时指定、叠加过滤（部门与产品同时命中的经验才返回）；两者是可选过滤条件，未指定时检索全部经验。

2. experience upload 贡献经验
作用：写入一条经验，核心字段为 user_id、title、summary、scene_id、scene、experience、rag_search_text。

coreinsight-cli experience upload \
  --scene "测试脚本调测经验" \
  --scene_id "scene-001" \
  --title "在U2020上执行MML命令" \
  --summary "完整字段示例，包含向量化文本与元数据" \
  --experience "在该场景下积累的经验点" \
  --rag_search_text "MML命令 U2020 执行"
​
必填：--scene、--scene_id、--title、--summary、--experience。--user_id 默认登录工号；旧的 --doc_id 与产品字段参数保留透传兼容。成功响应中 result.data 为经验 ID 字符串。

{"code":200,"msg":"success","data":"3659f967-a733-4045-9b09-c3ba2ad8d9a1"}
​
八、全局参数与环境变量
所有命令均支持以下全局参数（放在命令名之前）：

全局参数	作用	默认值
--server <url>	Core Insight 地址；对 auth 也作为登录 server 覆盖	见"服务地址"
--chat-server <url>	Chat 地址（问答、经验、skill scenes 使用）	<server>/chat
--auth-server <url>	登录地址	https://login.huawei.com/login1
--ai-community-server <url>	AI Community 地址（skill 检索/下载/上传）	https://aicommunity.coreai.rnd.huawei.com
--core-harness-server <url>	Core Harness 地址（skill scenes 产品接口）	http://coreharness.spec.rnd.huawei.com
--timeout <seconds>	请求超时	120s
--debug	调试日志写 stderr（含请求体，分享日志前请脱敏）	关
同名环境变量可替代（环境变量优先被读取，其次内置默认）：

COREINSIGHT_SERVER、COREINSIGHT_CHAT_SERVER、COREINSIGHT_AUTH_SERVER、COREINSIGHT_AI_COMMUNITY_SERVER、COREINSIGHT_CORE_HARNESS_SERVER、COREINSIGHT_TIMEOUT、COREINSIGHT_AUTH_USERNAME（兼容 OMRES_AUTH_USERNAME）、COREINSIGHT_AUTH_PASSWORD（兼容 OMRES_AUTH_PASSWORD）。

# 覆盖服务地址与超时
coreinsight-cli --server https://coreinsight.rnd.huawei.com --timeout 300 rag --retrieve --query "问题" --kb_sns 1
​
九、输出格式与退出码
输出格式（JSON-RPC 2.0，stdout）：

{
  "jsonrpc": "2.0",
  "result": {"code": 200, "data": [], "msg": "success"},
  "id": "req-xxxx"
}
​
失败时 result 换成 error：{"code": -32002, "message": "Not Authenticated", "data": {...}}。

退出码：

退出码	含义
0	成功（含 help / version / 已认证 status）
1	参数不合法、后端错误、网络失败
3	未认证或本地会话过期（业务命令被拦截、auth status 未认证）
脚本判断成功推荐：先看退出码，再看 result.code（通常 200）。

十、常见问题
Q1：未登录执行业务命令会怎样？
返回 -32002 Not Authenticated（含"请执行 auth login"提示），退出码 3，不发出任何网络请求。显式传 --user_id / --caller_id 也不能绕过。

Q2：会话过期了怎么办？
重新执行 coreinsight-cli auth login --username <域账号>。auth status 返回 3 即代表未认证/过期。

Q3：如何写脚本 / CI？
使用 --password-stdin 管道传密码，避免进入命令历史；判断成功用退出码 + result.code。示例：

printf '%s\n' "$PASS" | coreinsight-cli auth login --username U --password-stdin
coreinsight-cli rag --retrieve --query "$Q" --departments "xx" > out.json
​
Q4：如何切换测试 / 生产环境？
优先用环境变量 COREINSIGHT_SERVER（Chat 跟随），或每次加 --server。切环境后建议先 auth status 确认会话与目标环境匹配。

Q5：skill scenes 报"读取 git origin 失败"？
当前目录不是 git 仓库。先 cd 进仓库再 --repo .，或直接 --repo /path/to/repo。

Q6：如何确认请求打到了哪个环境？
加 --debug 运行，stderr 会打印请求方法与完整 URL（含调试体，分享前脱敏）。

Q7：遇到 405 / 请求超时？
405 检查网关路由与后端 Allow，不能只凭 405 断定接口限制；超时先核对内网/VPN、DNS、代理与 NO_PROXY，必要时再调 --timeout。确认服务基址（如 Chat 需含 /chat）是否正确。

Q8：退出码和 result.code 有什么区别？
退出码反映 CLI 自身执行结果（参数/认证/网络/后端错误统一 1，未认证 3）；result.code 是后端业务码（通常 200 成功）。业务语义以 result.code 为准，调用成功与否以退出码为准。
