// P4：模型列表刷新按钮。
//
// 为带 url/model widget 的节点注入「🔄 刷新模型」按钮，
// 调用本包**独立**路由 POST /ollama_qwenhancer/list_models。
//
// 禁止改用 comfyui-ollama 的 /ollama/get_models：两条路由的重复注册
// 会让后加载的包在 aiohttp 上抛 RuntimeError（风险 R2）。
//
// 注意：下拉框的取值始终是**真实的模型名**，不加任何装饰前缀，
// 否则该字符串会被序列化进工作流并原样送到后端，导致模型解析失败。

import { app } from "/scripts/app.js";

const ROUTE = "/ollama_qwenhancer/list_models";

// 这些节点的模型下拉框只列出具备 vision 能力的模型（FR-03）
const VISION_ONLY_NODES = new Set(["OllamaQWEVL", "OllamaQWEVLAdvanced"]);

const TARGET_NODES = new Set([
  "OllamaQWEConnect",
  "OllamaQWEVL",
  "OllamaQWEVLAdvanced",
  "OllamaQWEEnhancer",
]);

function toast(severity, summary, detail) {
  try {
    app.extensionManager.toast.add({ severity, summary, detail, life: 6000 });
  } catch (e) {
    console.warn("[OllamaQWEnhancer]", summary, detail);
  }
}

app.registerExtension({
  name: "Comfy.OllamaQWEnhancer.ModelList",

  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (!TARGET_NODES.has(nodeData.name)) return;

    const onCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const result = onCreated?.apply(this, arguments);

      const urlWidget = this.widgets?.find((w) => w.name === "url");
      const modelWidget = this.widgets?.find((w) => w.name === "model");
      if (!urlWidget || !modelWidget) return result;

      // 连接节点上的 vision_only 开关可覆盖默认行为
      const visionWidget = this.widgets?.find((w) => w.name === "vision_only");
      const visionOnly = () =>
        visionWidget ? !!visionWidget.value : VISION_ONLY_NODES.has(nodeData.name);

      const refresh = async () => {
        button.name = "⏳ 拉取中…";
        this.setDirtyCanvas(true, true);

        let payload = { models: [], error: null };
        try {
          const resp = await fetch(ROUTE, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url: urlWidget.value, vision_only: visionOnly() }),
          });
          payload = await resp.json();
        } catch (error) {
          button.name = "🔄 刷新模型";
          this.setDirtyCanvas(true, true);
          toast("error", "Ollama 连接失败", String(error));
          return;
        }

        button.name = "🔄 刷新模型";
        this.setDirtyCanvas(true, true);

        if (payload.error) {
          toast("error", "模型列表获取失败", payload.error);
          return;
        }

        const names = (payload.models || []).map((m) => m.name);
        if (names.length === 0) {
          toast(
            "warn",
            "没有可用模型",
            visionOnly()
              ? "服务器上未找到具备 vision 能力的模型。可关闭 vision_only，或先执行 ollama pull。"
              : "服务器上没有任何模型，请先执行 ollama pull。"
          );
          return;
        }

        const previous = modelWidget.value;
        modelWidget.options = modelWidget.options || {};
        modelWidget.options.values = names;

        // 保持原选择；已失效时退回到第一个
        modelWidget.value = names.includes(previous) ? previous : names[0];

        toast("success", "模型列表已更新", `共 ${names.length} 个模型`);
        this.setDirtyCanvas(true, true);
      };

      const button = this.addWidget("button", "🔄 刷新模型", null, refresh);
      // 按钮不进工作流，避免污染序列化结果
      button.serialize = false;

      return result;
    };
  },
});
