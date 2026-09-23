# ComfyUI Ollama QWEnhancer

在 **Ollama** 后端上复现 [`ComfyUI-QwenVL`](https://github.com/1038lab/ComfyUI-QwenVL)
的推理侧能力：Qwen-VL 风格的图像理解、多帧视频处理与 Prompt 增强。
去掉全部本地模型加载与下载，推理交给 Ollama 服务。

---

## 需求来源（原始任务书）

> **Task**：构建一个 ComfyUI custom node 插件，插件功能：
> 利用现有的 comfyui-ollama（源代码放在 `../comfyui-ollama`）插件实现的连接 LLM
> 模型的功能，实现 ComfyUI-QwenVL 插件的全部功能（source code in `../ComfyUI-QwenVL`）。
> 主要步骤包括：
> 1. 去掉 ComfyUI-QwenVL 里面自己加载建立 LLAMA server 的功能，去掉从 huggingface
>    下载模型的功能，保留其他全部功能。例如可选 system prompt，可选 LLM VL 模型等。
> 2. 采用 ollama 提供 LLM 服务，要求可选择 ollama 服务器 ip/port，可查询选择 ollama 可用模型。
> 3. 可以直接扩展 comfyui-ollama 的功能，添加新的 node，实现新的插件包
>    ComfyUI-Ollama-QWEnhancer。

**补充约束（用户确认）**

- ComfyUI 本体：`<ComfyUI>`
- ComfyUI venv：`<comfy-venv>`（Python 3.13.14）
- Ollama 服务：`http://127.0.0.1:11434`
- 主用 VL 模型：`qwen2.5vl:7b`
- **视频暂时按 Ollama 服务能力降级为图片处理**
- **按新的独立软件包创建**，命名 / 路由冲突须避免

---

## 节点（CATEGORY = `Ollama/QWEnhancer`）

| 节点 | 显示名 | 输出 | 说明 |
| --- | --- | --- | --- |
| `OllamaQWEConnect` | Ollama QWE 连接 (QwenVL) | `QWE_OLLAMA_CONN` | 地址 / 模型 / `keep_alive`，可被下游节点共享 |
| `OllamaQWEVL` | Ollama QwenVL | `RESPONSE` | 预设 + 自定义 prompt、system prompt、图像 / 视频、seed |
| `OllamaQWEVLAdvanced` | Ollama QwenVL (Advanced) | `RESPONSE`, `THINKING` | 追加温度 / top_p / 重复惩罚 / `num_ctx` / `think` |
| `OllamaQWEEnhancer` | Ollama QwenVL Prompt 增强 | `ENHANCED_OUTPUT` | 6 种增强风格 + 自定义风格指令 |

三个推理节点都有 `prompt_in`（文本输入插槽）与 `enabled`（直通开关），见下节。

所有节点的 `url` / `model` 都是普通 widget：**不连 `OllamaQWEConnect` 也能直接用**；
连上后 `conn` 输入会覆盖本节点的 url/model，便于在工作流中统一改地址。

### 跳过 / 禁用节点时的直通

想在某个节点被禁用时让 prompt 原样流到输出，有两条路：

**1. `enabled=False`（推荐，确定性）**

每个推理节点末尾都有 `enabled` 开关，默认 `True`。关掉后节点**完全不调用 Ollama**，
直接把提示文本送到输出：

| 节点 | 关闭 `enabled` 后输出 |
| --- | --- |
| `OllamaQWEEnhancer` | `prompt_in` → 否则 `prompt_text` → 否则占位文本 |
| `OllamaQWEVL` / `Advanced` | `prompt_in` → 否则 `custom_prompt` → 否则预设模板正文 |

好处：连线完全不用改，也不受下游输入类型影响。适合「先看原样 prompt，稍后再开增强」。

**2. ComfyUI 原生 Bypass（Ctrl+B）**

ComfyUI 的旁路是**前端**实现的（`ExecutableNodeDTO.resolveOutput`）：被旁路的节点
不会进入 API prompt，前端为每个**输出**寻找**类型匹配的输入**并直通：

```ts
if (this.mode === LGraphEventMode.BYPASS) {
  const matchingIndex = this._getBypassSlotIndex(slot, type)
  if (matchingIndex === -1) return   // 没有类型匹配的输入 → 什么都不会输出
  return this.resolveInput(matchingIndex, visited)
}
```

所以节点必须有**类型能对上的输入插槽**才可能直通。三个推理节点都提供了
`prompt_in`（`STRING`，`forceInput`），与文本输出（`STRING`）类型匹配。

⚠️ 注意两个限制：
- 若下游输入的类型是 `*`（如 `PreviewAny`），前端会退回「按插槽号匹配」，
  此时不一定命中 `prompt_in` → **请优先用 `enabled=False`**
- 输入插槽的位置会影响按插槽号匹配的结果，因此新增插槽一律**追加在末尾**，
  以免破坏已有工作流的连线

### 日志与噪声控制

节点默认只在启动时打印一行横幅，**每次执行不再输出任何日志**（早期版本会在
每次执行时打印连接信息，批量运行会刷屏）。

需要排查时用环境变量提升级别：

| `QWE_LOG` | 输出 |
| --- | --- |
| `error` | 仅错误 |
| `warn`（默认） | 错误 + 告警；同类告警只打印一次（去重） |
| `info` | 追加连接/执行摘要、路由注册信息 |
| `debug` | 追加完整请求/响应明细 |

```bash
QWE_LOG=debug python main.py     # 启动 ComfyUI 时带上
```

### 示例工作流

`example_workflows/` 下 4 个可直接加载的工作流：

| 文件 | 内容 |
| --- | --- |
| `qwe-vl-image.json` | LoadImage → Ollama QwenVL（Detailed Description）→ PreviewAny |
| `qwe-vl-video.json` | LoadVideo → GetVideoComponents → Ollama QwenVL（Video Summary）→ PreviewAny |
| `qwe-prompt-enhance.json` | Ollama Prompt 增强（📝 Enhance）→ PreviewAny |
| `qwe-shared-connection.json` | 一个 OllamaQWEConnect 同时供 VL 与增强节点复用 |

> 校验：`tests/test_example_workflows.py`（9 项）会检查节点类型是否真实存在、
> 链接是否双向一致、以及 `widgets_values` 与本包 `INPUT_TYPES` 是否**逐项对齐**。

### 「🔄 刷新模型」按钮

每个节点上都有一个刷新按钮，调用本包**专属路由** `POST /ollama_qwenhancer/list_models`
拉取服务器模型列表：

- VL 节点只列出具备 `vision` 能力的模型（通过 `/api/show` 的 `capabilities` 判定）
- 连接节点可用 `vision_only` 开关控制

---

## 安装

### 1. 安装依赖

本包运行期**只需要** `ollama` 客户端；`torch` / `numpy` / `Pillow` / `aiohttp`
全部复用 ComfyUI 宿主。

```bash
<comfy-venv>/bin/python -m pip install -r requirements.txt
```

### 2. 放入 custom_nodes

```bash
cd <ComfyUI>/custom_nodes
git clone https://github.com/manuxcjh/ComfyUI-Ollama-QWEnhancer.git
```

或手动复制整个目录。辅助脚本见
[`tools/deploy_to_comfyui.sh`](tools/deploy_to_comfyui.sh)（会把包复制/软链到
`custom_nodes`，并检查目标是否可写）。

### 3. 重启 ComfyUI

启动日志应出现：

```
[ComfyUI-Ollama-QWEnhancer] v0.1.0 | 4 nodes Loaded
[OllamaQWEnhancer] 已注册模型列表路由 POST /ollama_qwenhancer/list_models
```

---

## 环境要求

| 项 | 要求 |
| --- | --- |
| Ollama 服务 | 可达。默认 `http://127.0.0.1:11434`（Ollama 标准端口），可用环境变量或本机配置覆盖 |
| VL 模型 | 至少一个具备 vision 能力的模型，如 `qwen2.5vl:7b` |
| `ollama` 客户端 | `>=0.4,<1.0`（实测 0.6.0） |
| ComfyUI | `>=1.3.0` |

模型名支持容错：写成 `qwen2.5vl-27B:7b` 这类笔误时，
若与某个真实模型相似度 ≥0.85 且明显领先其他候选，会自动纠正并打印告警；
否则报错并列出可用模型。

---

## 参数映射（对照 ComfyUI-QwenVL）

| 本包 widget | Ollama | 上游对应 |
| --- | --- | --- |
| `max_tokens` | `options.num_predict` | `max_tokens` |
| `temperature` | `options.temperature` | `temperature` |
| `top_p` | `options.top_p` | `top_p` |
| `repetition_penalty` | `options.repeat_penalty` | `repetition_penalty` |
| `seed` | `options.seed` | `seed` |
| `num_ctx` | `options.num_ctx` | 上游固定 8192 |
| `keep_alive` + 单位 | `keep_alive` | `keep_model_loaded`（🔁 语义映射） |
| `preset_prompt` / `custom_prompt` | `system` | 同名（`custom_prompt` 非空即**完全覆盖**预设） |
| `frame_count` / `video_frame_size` | 不发送 | 同名，仅用于本地抽帧 |
| `think` | `think` | 无（新增） |
| — | — | `quantization` / `attention_mode` / `use_torch_compile` / `device` / `num_beams`（已删除） |

---

## 已知限制

1. **视频降级为图片**：Ollama 没有原生 video 输入，`video` 输入会按 `frame_count`
   均匀抽帧后作为多张图片发送，**没有时序建模**，运动 / 因果类描述会弱于原生视频模型。
2. **单次请求最多 16 张图像**（含抽帧），超出会截断并打印告警。
3. **思考型模型**：节点默认 `think=False`。这一点是刻意的——不显式关闭思考时，
   模型会把 `num_predict` 全部消耗在 `thinking` 上，`RESPONSE` 会是空字符串。
4. `num_beams`（束搜索）无对应实现，已移除。

---

## 测试

测试依赖 **ComfyUI 宿主的 Python**（需要 numpy / Pillow / torch / aiohttp）：

```bash
# 指定 ComfyUI 的解释器（推荐写进 config/local.json 的 "python" 字段，之后免参数）
QWE_PYTHON=/path/to/ComfyUI/venv/bin/python bash tests/run_all.sh
# 或
COMFY_VENV=/path/to/ComfyUI/venv bash tests/run_all.sh

# 全部（含对真实 Ollama 的端到端测试）
bash tests/run_all.sh

# 仅离线（无需 Ollama 服务）
QWE_OFFLINE=1 bash tests/run_all.sh
```

若解释器选错（例如退回到系统 python3），预检会直接指出缺少哪个模块并给出上面的命令，
而不是抛出 `No module named 'PIL'` 之类难以定位的报错。

单独运行：

| 脚本 | 覆盖 |
| --- | --- |
| `tests/test_core_offline.py` | **30 项**：地址规范化、默认地址可覆盖、参数映射、媒体适配、输出清洗、prompt 资产、Node ID 前缀 |
| `tests/test_example_workflows.py` | **9 项**：工作流结构自洽、节点存在性（到 ComfyUI 源码核实）、链接双向一致、`widgets_values` 与 `INPUT_TYPES` 对齐、combo/数值取值合法 |
| `tests/test_passthrough.py` | **9 项**：`enabled=False` 直通（用不可达地址证明零网络请求）、`prompt_in` 优先级、`prompt_in` 为 STRING 插槽 |
| `tests/test_route_registration.py` | **7 项**：路由注册幂等、`add_routes` 不冲突、接口契约往返 |
| `tests/test_live_ollama.py` | **12 项**：模型清单 / vision 过滤 / 下拉框候选集 / 名称容错 / 4 个节点真实推理 / 错误路径 |
| `tests/test_contract_scan.sh` | 禁用依赖、CUDA 调用、requirements、命名空间冲突 |
| `tests/check_conflicts.py` | AST 精确比对 Node ID / 路由 / 数据类型与上游 |

---

## 文档

| 文档 | 内容 |
| --- | --- |
| [`docs/00-环境记录.md`](docs/00-环境记录.md) | P0 环境实测：Ollama 模型清单、ComfyUI 路径与挂载、venv、API 契约、踩坑记录 |
| [`docs/01-系统需求分析.md`](docs/01-系统需求分析.md) | 需求分析：FR / DR / NFR、接口契约、风险、验收标准 |
| [`docs/02-新软件包创建流程.md`](docs/02-新软件包创建流程.md) | P0–P7 阶段与 G0–G7 门控、命名规范、DoD |
| [`docs/03-功能对等矩阵.md`](docs/03-功能对等矩阵.md) | 上游功能逐条处置、参数映射、需求追溯、决策记录 |

---

## 默认地址与模型（可覆盖）

取值优先级：**环境变量 > `config/local.json` > 内置默认值**。

| 变量 | 内置默认值 | 说明 |
| --- | --- | --- |
| `QWE_OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama 地址；节点上的 `url` widget 亦可随时改 |
| `QWE_OLLAMA_MODEL` | `qwen2.5vl:7b` | 服务器不可达时下拉框的兜底值 |
| `QWE_KEEP_ALIVE` | `5` | `keep_alive` 数值（`-1` = 模型常驻不重载） |
| `QWE_KEEP_ALIVE_UNIT` | `minutes` | `keep_alive_unit`（`minutes` / `hours`） |
| `QWE_LOG` | `warn` | 日志级别，见「日志与噪声控制」 |

### 本机配置：`config/local.json`

如果你要连的 Ollama 不在本机、或想固定默认模型，**不必改代码**，复制一份本机配置即可：

```bash
cp config/local.json.example config/local.json
# 然后编辑 url / model / keep_alive
```

```json
{ "url": "http://192.168.1.50:11434", "model": "qwen2.5vl:7b" }
```

`config/local.json` 已在 `.gitignore` 中，不会提交，也不影响从仓库拉取的代码。

地址默认指向局域网服务而非 `localhost`，因此节点开箱即用即可拉到真实模型列表
（VL 节点 6 个 vision 模型 / 增强节点 13 个模型，实测 0.5 秒）。

## 许可

GPL-3.0。核心层（`core/media.py`、`core/cleaner.py`）与 `config/system_prompts.json`
移植自 [`ComfyUI-QwenVL`](https://github.com/1038lab/ComfyUI-QwenVL)（GPL-3.0），
已保留相应版权声明。Ollama Python 客户端为 MIT。
