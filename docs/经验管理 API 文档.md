# 经验管理 API 文档

## 1. 通用字段说明

### 1.1 顶层字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | ---: | --- |
| `scene` | string | 是 | 场景名称，例如：`AI替代测试执行` |
| `scene_id` | string | 是 | 场景/叶子节点 ID，用于检索、过滤和场景计数统计 |
| `title` | string | 是 | 标题字段，用于向量化检索 |
| `summary` | string | 是 | 经验摘要总结，用于向量化检索 |
| `experience` | string | 是 | 场景经验内容；内容非空时会生成 `experience_vector`，支持按该字段检索 |
| `rag_search_text` | string | 否 | 补充检索文本；内容非空时会生成 `rag_search_text_vector`，支持按该字段检索 |
| `product` | object | 否 | 产品过滤信息 |
| `metadata` | object | 否 | 元数据，存储扩展信息 |
| `user_id` | string | 是 | 用户 ID |
| `doc_id` | string | 否 | 记录 ID，不传则系统自动生成 |
| `log` | object | 否 | 日志信息 |
| `created_at` | datetime | 否 | 创建时间，由系统生成 |
| `updated_at` | datetime | 否 | 更新时间，由系统生成 |
| `version` | int | 否 | 版本号，由系统生成，从 1 开始 |
| `quality` / `quality_category` / `quality_reason` | - | 否 | 质量检测结果，写入后由系统异步生成，无需在请求中传入 |

### 1.2 `product` 字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | ---: | --- |
| `product.product_line_name` | string | 否 | 产品线名称 |
| `product.pdu_name` | string | 否 | PDU 名称；未传入时系统会根据 `user_id` 自动补全 |
| `product.product_id` | string | 否 | 产品 ID |
| `product.version_name` | string | 否 | 版本信息 |
| `product.feature` | string | 否 | 所属特性 |

### 1.3 通用响应结构

所有接口的返回统一为以下结构：

```json
{
  "code": 200,
  "msg": "success",
  "data": { }
}
```

请求失败时 `data` 为 `null`，`code` 与 HTTP 状态码保持一致（如 400 / 404 / 500 / 502），`msg` 中包含具体错误信息。

---

## 2. 接口列表

### 1) 写入单条记录（文档创建/覆盖）

- **Endpoint**：`POST /memory/experience/doc`
- **功能简述**：写入一条记录。标题、摘要会自动向量化，`experience`、`rag_search_text` 在内容非空时也会向量化。
  若传入的 `doc_id` 已存在，会覆盖写入并将版本号自增（旧版本自动归档，可通过版本历史接口查询）；若 `doc_id` 不存在或未传，则作为新记录写入，版本号为 1。
  写入成功后会自动进行一次质量检测，检测结果稍后回填到 `quality` / `quality_category` / `quality_reason` 字段。
- **请求体（DocumentCreate）**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | ---: | --- |
| `scene` | string | 是 | 场景名称 |
| `scene_id` | string | 是 | 场景/叶子节点 ID |
| `title` | string | 是 | 标题，向量化 |
| `doc_id` | string | 否 | 不传则自动生成 |
| `summary` | string | 是 | 摘要，向量化 |
| `experience` | string | 是 | 经验内容 |
| `rag_search_text` | string | 否 | 补充检索文本 |
| `product` | object | 否 | 产品过滤信息 |
| `metadata` | object | 否 | 元数据 |
| `user_id` | string | 是 | 用户 ID |
| `log` | object | 否 | 日志信息 |

- **请求示例**

```json
{
    "scene": "test",
    "scene_id": "scene-001",
    "title": "在U2020上执行MML命令",
    "summary": "完整字段示例，包含向量化文本与元数据",
    "user_id": "user-123",
    "experience": "在该场景下积累的经验点",
    "rag_search_text": "MML命令 U2020 执行",
    "product": {
        "product_line_name": "云产品线A",
        "pdu_name": "PDU-01",
        "product_id": "PID-123",
        "version_name": "v1.2",
        "feature": "向量混合检索"
    },
    "metadata": { "env": "prod", "platform": "web" },
    "log": { "created_by": "system", "notes": "首次写入" }
}
```

- **响应示例**

```json
{
    "code": 200,
    "msg": "success",
    "data": {
        "id": "ef1e23c3-4919-406f-9e18-56de63b88f10",
        "scene_id": "scene-001",
        "vectorized_fields": ["title_vector", "summary_vector", "experience_vector"],
        "version": 1,
        "is_overwrite": false,
        "archived_history_id": null,
        "upserted": 1,
        "updated": 0
    }
}
```

---

### 2) 更新记录（局部更新）

- **Endpoint**：`PUT /memory/experience/doc/{doc_id}`
- **功能简述**：仅更新请求体中传入的字段，其余字段保持不变。若更新了 `title`、`summary`、`experience` 中任意一项，会同步重新生成对应向量，并将质量检测状态重置为待检测，触发后台重新检测。
- **请求路径参数**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | ---: | --- |
| `doc_id` | string | 是 | 文档唯一标识 |

- **请求体（DocumentUpdate）**：与创建接口字段一致，均为可选，按需传入需要更新的字段即可，至少传一个。
- **响应示例**

```json
{
    "code": 200,
    "msg": "success",
    "data": {
        "id": "ef1e23c3-4919-406f-9e18-56de63b88f10",
        "updated": 1
    }
}
```

- **注意**：若 `doc_id` 不存在，返回 404；若未传任何需要更新的字段，返回 400。

---

### 3) 按文档 ID 删除单条记录

- **Endpoint**：`DELETE /memory/experience/doc/{doc_id}`
- **功能简述**：删除指定文档。删除前会自动归档当前版本，删除后仍可通过版本历史接口查询。
- **请求路径参数**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | ---: | --- |
| `doc_id` | string | 是 | 文档唯一标识 |

- **响应示例**

```json
{
    "code": 200,
    "msg": "success",
    "data": { "deleted": 1 }
}
```

- **注意**：若文档不存在，返回 404。

---

### 4) 按条件检索（非向量检索，分页）

- **Endpoint**：`POST /memory/experience/doc/search/by-filter`
- **功能简述**：按照给定过滤条件检索，支持分页和排序（基于字段匹配，非向量检索）。
- **请求体（SearchByFilter）**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | ---: | --- |
| `scene` | string | 否 | 场景名称 |
| `scene_id` | string 或 string 数组 | 否 | 场景/叶子节点 ID，传数组时匹配多个值 |
| `product` | object | 否 | 产品信息 |
| `doc_id` | string | 否 | 记录 ID |
| `user_id` | string | 否 | 用户工号 |
| `caller_id` | string | 是 | 调用方工号 |
| `quality_only` | bool | 否，默认 false | 为 true 时仅返回质量检测通过的记录 |
| `filter` | dict / object | 否 | 过滤条件 |
| `page` | int | 否，默认 1 | 页码 |
| `page_size` | int | 否，默认 10 | 每页数量 |
| `sort` | list[dict] | 否 | 排序条件 |

- **请求示例**

```json
{
  "scene": "test",
  "scene_id": "scene-001",
  "caller_id": "w00123456",
  "product": {
    "product_line_name": "云产品线A",
    "pdu_name": "PDU-01"
  },
  "filter": {
    "metadata.platform": "web",
    "metadata.env": "prod"
  },
  "page": 1,
  "page_size": 20,
  "sort": [ { "created_at": { "order": "desc" } } ]
}
```

- **响应示例**

```json
{
    "code": 200,
    "msg": "success",
    "data": {
        "total": 2,
        "page": 1,
        "page_size": 20,
        "total_pages": 1,
        "has_next": false,
        "has_prev": false,
        "items": [
            {
                "doc_id": "ef1e23c3-4919-406f-9e18-56de63b88f10",
                "scene": "test",
                "scene_id": "scene-001",
                "title": "在U2020上执行MML命令",
                "summary": "完整字段示例，包含向量化文本与元数据",
                "experience": "在该场景下积累的经验点",
                "userid": "user-123",
                "product": {
                    "version_name": "v1.2",
                    "product_line_name": "云产品线A",
                    "feature": "向量混合检索",
                    "product_id": "PID-123",
                    "pdu_name": "PDU-01"
                },
                "metadata": { "env": "prod", "platform": "web" },
                "log": { "notes": "首次写入", "created_by": "system" },
                "created_at": "2026-03-14 18:06:07",
                "updated_at": "2026-03-14 18:06:07"
            }
        ]
    }
}
```

- **注意**：`page` 与 `page_size` 的乘积（分页偏移量）不能超过 10000，超出时返回 400，请缩小页码或使用更精确的过滤条件。

---

### 5) 混合检索（向量 + BM25）

- **Endpoint**：`POST /memory/experience/doc/search`
- **功能简述**：根据指定的 `search_field` 字段进行向量化打分并结合 BM25 检索，返回融合排序后的结果，支持分页。
- **请求体（SearchRequest）**

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | ---: | --- |
| `query` | string | 是 | 查询文本 |
| `search_field` | string | 是 | 检索字段，可选 `title` / `summary` / `experience` / `rag_search_text` |
| `scene` | string 或 string 数组 | 否 | 场景名称，传数组时匹配多个值 |
| `scene_id` | string 或 string 数组 | 否 | 场景/叶子节点 ID，传数组时匹配多个值 |
| `top_k` | int | 否，默认 10 | 融合排序后取前 N 条参与分页 |
| `page` | int | 否，默认 1 | 页码 |
| `page_size` | int | 否，默认 10 | 每页数量 |
| `weights` | object | 否 | `vector` 和 `bm25` 的比重（默认向量 0.7，BM25 0.3） |
| `product` | object | 否 | 产品信息 |
| `filter` | dict / object | 否 | 过滤条件 |
| `score_threshold` | float | 否 | 分数阈值（0.0 到 1.0） |
| `quality_only` | bool | 否，默认 false | 为 true 时仅检索质量检测通过的记录 |
| `caller_id` | string | 是 | 调用方工号 |
| `doc_id` | string | 否 | 记录 ID 过滤 |
| `user_id` | string | 否 | 用户 ID 过滤 |

- **请求示例**

```json
{
    "query": "智能客服系统",
    "scene": "test",
    "search_field": "title",
    "caller_id": "w00123456",
    "top_k": 10,
    "page": 1,
    "page_size": 10,
    "weights": { "vector": 0.6, "bm25": 0.4 }
}
```

- **响应示例**

```json
{
    "code": 200,
    "msg": "success",
    "data": {
        "search_field": "title",
        "total_candidates": 2,
        "total_ranked": 2,
        "page": 1,
        "page_size": 10,
        "total_pages": 1,
        "has_next": false,
        "has_prev": false,
        "items": [
            {
                "doc_id": "ef1e23c3-4919-406f-9e18-56de63b88f10",
                "scene": "test",
                "scene_id": "scene-001",
                "title": "在U2020上执行MML命令",
                "summary": "完整字段示例，包含向量化文本与元数据",
                "experience": "在该场景下积累的经验点",
                "userid": "user-123",
                "created_at": "2026-03-14 18:06:07",
                "updated_at": "2026-03-14 18:06:07",
                "product": {
                    "product_line_name": "云产品线A",
                    "pdu_name": "PDU-01",
                    "product_id": "PID-123",
                    "version_name": "v1.2",
                    "feature": "向量混合检索"
                },
                "metadata": { "env": "prod", "platform": "web" },
                "log": { "created_by": "system", "notes": "首次写入" },
                "score": {
                    "final": 0.6178,
                    "vector_raw": 0.363,
                    "vector_norm": 0.363,
                    "bm25_raw": 1.0,
                    "bm25_norm": 1.0
                }
            }
        ]
    }
}
```
