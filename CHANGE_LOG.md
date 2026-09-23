# Change Log

## v0.1.0（未发布）

首个可用版本，按 `docs/02-新软件包创建流程.md` 的 P1–P6 阶段产出。

### 新增节点（CATEGORY = `Ollama/QWEnhancer`）

| Node ID | 显示名 | 说明 |
| --- | --- | --- |
| `OllamaQWEConnect` | Ollama QWE 连接 (QwenVL) | 共享地址 / 模型 / `keep_alive`，输出 `QWE_OLLAMA_CONN` |
| `OllamaQWEVL` | Ollama QwenVL | 预设 + 自定义 prompt、system prompt、图像/视频、seed |
| `OllamaQWEVLAdvanced` | Ollama QwenVL (Advanced) | 追加采样参数、`num_ctx`、`think`（独立输出端口） |
| `OllamaQWEEnhancer` | Ollama QwenVL Prompt 增强 | 6 种增强风格 + 自定义 system prompt |

### 核心层

- `core/ollama_client.py`：`/api/tags` + `/api/show` 能力探测、模型名容错解析、
  统一可读异常、参数映射（`max_tokens→num_predict`、`repetition_penalty→repeat_penalty`）
- `core/media.py`：移植上游 `tensor_to_pil` / `tensor_to_base64_png` /
  `sample_video_frames` / `resolve_safe_video_max_side`
- `core/cleaner.py`：移植上游 `clean_model_output`，剥离 `think` 块与代码围栏
- `core/prompts.py`：装载 `config/system_prompts.json`（9 条 VL 预设 + 6 种风格）

### HTTP / Web

- 新增独立路由 `POST /ollama_qwenhancer/list_models`
  （**不复用** `/ollama/get_models`，规避 aiohttp 重复注册崩溃）
- `web/js/model_list.js`：节点上的「🔄 刷新模型」按钮
- `web/js/appearance.js`：节点配色

### 按需求移除

llama-server 本地加载、HuggingFace 下载、GGUF/llama.cpp、bitsandbytes 量化、
SageAttention/FlashAttention、`torch.compile`、设备选择、`num_beams`。

### 示例工作流

`example_workflows/` 下 4 个：图像描述、视频抽帧、Prompt 增强、共享连接。

### 测试

`bash tests/run_all.sh` 一键跑通 G1–G6；共 **54 项**自动化测试：

| 脚本 | 项数 |
| --- | --- |
| `tests/test_core_offline.py` | 26 |
| `tests/test_example_workflows.py` | 9 |
| `tests/test_route_registration.py` | 7 |
| `tests/test_live_ollama.py` | 12 |

### 开发期修复的缺陷

1. 思考型模型未显式发送 `think` 导致正文为空（关键）
2. `RouteTableDef` 无 `resources()` 导致 HTTP 路由永远注册不上（关键）
3. `preset_prompt` 候选集误用模型列表
4. 默认地址指向 localhost 而非实际局域网服务
5. 输出清洗不认 Qwen `｜end▁of▁thinking｜` 分隔符

## v0.1.2

- 修复：`tests/run_all.sh` 在**干净克隆**下会退回系统 `python3`（缺 numpy/Pillow），
  导致 4 个测试报 `No module named 'PIL'` 这种难以定位的错误。
  现在支持 `QWE_PYTHON` / `COMFY_VENV` / `config/local.json` 三种指定方式，
  并在预检阶段直接说明缺什么、该怎么指定。

## v0.1.1

相对 v0.1.0 的增量：

- **日志治理**：新增 `core/log.py`，`QWE_LOG` 控制级别（默认 `warn`）。
  移除每次执行的连接打印，同类告警去重；控制台每次启动仅 1 行横幅。
- **禁用直通**：三个推理节点新增 `enabled`（默认 `True`）；关闭后跳过推理、
  原样输出提示文本，且**不产生任何网络请求**。
- **Bypass 兼容**：新增 `prompt_in`（`STRING`，`forceInput`）输入插槽，
  使 ComfyUI 原生 Bypass 可按类型匹配直通到文本输出。
- **可配置默认值**：`QWE_KEEP_ALIVE` / `QWE_KEEP_ALIVE_UNIT` 环境变量。
- **采纳实机取值**：增强节点 `max_tokens` 默认 4096（min 256 / max 16384 / step 256），
  `temperature` 默认 0.3。
- 修正 `preset_prompt` 候选集误用模型列表、默认地址指向 localhost 两处缺陷。

### 已知限制

- **视频降级为图片**：Ollama 无原生 video 输入，`video` 输入按 `frame_count`
  抽帧后作为多张图片发送，无时序建模（见 `docs/01-系统需求分析.md` R1）
- 单次请求最多 16 张图像（含抽帧），超出会截断并告警
