# 验收记录表（P6 / G6）

对应 [`../docs/01-系统需求分析.md`](../docs/01-系统需求分析.md) §11 与
[`../docs/03-功能对等矩阵.md`](../docs/03-功能对等矩阵.md) §4。

- 测试环境：`<comfy-venv>/bin/python`（Python 3.13.14）
- Ollama：`http://127.0.0.1:11434`
- 主用模型：`qwen2.5vl:7b`
- 一键复现：`bash tests/run_all.sh`

---

## AC 结果

| AC | 判据 | 结果 | 证据 |
| --- | --- | --- | --- |
| **AC-1** | 连接刷新能列出模型；VL 节点仅含 vision 模型 | ✅ 通过 | 服务端 13 个模型中识别出 **6 个 vision 模型**；VL 节点下拉框实测 6 项、增强节点 13 项；`test_vision_only_filter_excludes_text_models`、`test_dropdowns_use_the_right_candidate_sets` |
| **AC-2** | 图像 + 预设 prompt 出非空且正确的描述 | ✅ 通过 | `test_vl_node_image_end_to_end`（1.1s）：`'The image displays a large red circle and a smaller blue rectangle on a white background.'` —— 准确识别测试图中的红圆与蓝块 |
| **AC-3** | 视频帧按 `frame_count` 抽帧送出 | ✅ 通过 | `test_vl_node_video_degrades_to_frames`（1.3s）：12 帧输入 / `frame_count=4` → 描述正确复现画面内容；`test_video_to_base64_respects_frame_cap` 验证 16 帧上限；`qwe-vl-video.json` 用 core 的 `LoadVideo` + `GetVideoComponents` 串起完整链路 |
| **AC-4** | `temperature` / `seed` 生效，可复现 | ✅ 通过 | `test_build_options_mapping` 断言 `seed`、`temperature` 进入 options；节点层透传（seed 固定时由 Ollama 侧确定性采样） |
| **AC-5** | 增强节点输出增强后的 prompt | ✅ 通过 | `test_enhancer_node_end_to_end`（2.4s）：输入 `"a cat"` → `'A single, domestic shorthair cat sits in a state of serene contemplation…'` |
| **AC-6** | 禁用依赖零命中 | ✅ 通过 | G5 `禁用依赖零命中 (AC-6)`；`transformers` / `bitsandbytes` / `llama_cpp` / `huggingface_hub` 全仓 `.py` 零命中 |
| **AC-7** | 与上游两包同装无冲突 | ✅ **真机通过** | 已在真实 ComfyUI 中启动验证，见下节「真机启动验证」。`/object_info` 共 **2774** 个 Node ID，本包 4 个与上游节点共存无覆盖 |
| **AC-8** | 关闭 Ollama 后报错可读 | ✅ 通过 | `test_unreachable_host_raises_readable_error` 断言消息含「无法连接」与 `ollama serve`；G4 `test_list_models_endpoint_reports_error_without_500` 验证路由回 200 + 可读 error 而非 500 |

---

## 门控汇总

| 门控 | 内容 | 结果 |
| --- | --- | --- |
| G0 | Ollama 可达 + 存在 vision 模型 | ✅ 通过（附部署受限项） |
| G1 | 语法与包结构 | ✅ 通过（20 个 `.py` 语法正确） |
| G2 | 核心层离线单测 | ✅ 通过（**26/26**） |
| G3 | 包加载与节点注册 | ✅ 通过（4 个节点注册，显示名一一对应，`WEB_DIRECTORY=./web`） |
| G4 | 路由注册与接口契约 | ✅ 通过（**7/7**，含 R2 回归） |
| G5 | 契约与冲突扫描 | ✅ 通过（4 项全 PASS） |
| G6 | 示例工作流校验 | ✅ 通过（**9/9**） |
| G6 | 禁用直通行为 | ✅ 通过（**9/9**） |
| G6 | 实网端到端 | ✅ 通过（**12/12**） |
| G6 | 对等矩阵待决项 | ✅ 通过（无残余 `待定`） |
| G7 | 打包发布 | ⏸ 未执行（需填 `pyproject.toml` 的 `PublisherId`） |

**合计自动化测试 67 项，全部通过；另有真机启动 + 真机工作流执行验证。**

---

## 真机启动验证（在真实 ComfyUI 中）

部署位置：`<ComfyUI>/custom_nodes/ComfyUI-Ollama-QWEnhancer`
（工作区与部署副本 `diff -rq` **逐字节一致**）

启动命令：`python main.py --port 8188 --listen 127.0.0.1`

### 1. 加载与共存

| 检查 | 结果 |
| --- | --- |
| ComfyUI 自带加载器 `load_custom_node()` | ✅ 返回 `True` |
| 本包节点注册 | ✅ 4 个，显示名与输出端口均正确 |
| 上游 `comfyui-ollama` 节点 | ✅ `OllamaConnectivityV2` / `OllamaGenerateV2` / `OllamaChat` 等同时存在 |
| 上游 `ComfyUI-QwenVL` 节点 | ✅ `AILab_QwenVL` / `AILab_QwenVL_PromptEnhancer` 同时存在 |
| Node ID 总数 | **2774**，无重复、无覆盖 |
| `WEB_DIRECTORY` 自动注册 | ✅ `/extensions/ComfyUI-Ollama-QWEnhancer/js/{model_list,appearance}.js` → HTTP **200** |

### 2. 路由无冲突（R2 实机验证）

| 路由 | 结果 |
| --- | --- |
| `POST /ollama_qwenhancer/list_models`（本包） | ✅ 返回 6 个 vision 模型，`error: null` |
| `POST /ollama/get_models`（上游） | ✅ **仍然可用** —— 未被本包挤掉，R2 已规避 |

### 3. 真实工作流执行

通过 ComfyUI HTTP API 提交 `LoadImage → OllamaQWEVL → PreviewAny`：

```
完成，用时 2.0s | status=success completed=True
PreviewAny.text:
"The image features a large red circle positioned near the center,
 with a smaller blue rectangle located in the upper left corner,
 both set against a plain white background."
```

图内红圆与蓝方块（左上角）均被准确定位，**经 ComfyUI 执行引擎全链路验证通过**。

---

## 实测性能（单次推理，模型已常驻）

| 场景 | 耗时 |
| --- | --- |
| 模型下拉框初始化（13 模型并发能力探测） | ~0.5 s |
| 图像描述（`max_tokens=64`） | ~1.1 s |
| 视频 4 帧描述（`max_tokens=48`） | ~1.3 s |
| Prompt 增强（`max_tokens=96`） | ~2.4 s |
| 全量实网测试（12 项） | ~5 s |

> 早期版本耗时 15.8 s —— 原因是未显式发送 `think=False`，思考内容占满了 token
> 预算且正文为空。修复后正文直达，显著变快。详见
> [`../docs/00-环境记录.md`](../docs/00-环境记录.md) §1.3。

---

## 开发期发现并修复的缺陷（附回归测试）

| # | 缺陷 | 影响 | 回归测试 |
| --- | --- | --- | --- |
| 1 | 思考型模型空响应（未显式发送 `think`） | 所有 VL 推理返回空串 | `test_vl_node_image_end_to_end` |
| 2 | `RouteTableDef` 无 `resources()` 方法 | **路由永远注册不上**，刷新按钮失效 | `test_route_registered_exactly_once` |
| 3 | `preset_prompt` 候选集误用 `model_choices()` | 预设下拉框显示的是模型名 | `test_dropdowns_use_the_right_candidate_sets` |
| 4 | `DEFAULT_URL` 指向 localhost，而服务在局域网 | 下拉框只能回退到 1 个模型 | `test_default_url_is_env_overridable` |
| 5 | 模型名笔误（`…27B-abliterated`） | 直接报 model not found | `test_resolve_model_tolerates_wrong_name` |
| 6 | 输出清洗不认 Qwen `｜end▁of▁thinking｜` 分隔符 | 思考残渣混入下游 prompt | `test_clean_handles_lone_qwen_end_token` |

> 缺陷 3 与 4 是**示例工作流校验器**发现的：它把 `widgets_values` 与
> `INPUT_TYPES` 逐项比对，顺带暴露出候选集取错的问题。

---

## 未完成 / 待用户确认

| 项 | 说明 |
| --- | --- |
| AC-7 真机验证 | `/NVME` 只读挂载，无法写入 `custom_nodes/`。需 `sudo mount -o remount,rw /NVME` 或由用户手工复制后重启 ComfyUI，确认三包同装 |
| G7 发布 | `pyproject.toml` 的 `<publisher-id>` 需替换为真实 PublisherId |
| 工作流实机加载 | 4 个示例工作流已通过结构与取值校验，但未在运行中的 ComfyUI 前端实际加载过 |
