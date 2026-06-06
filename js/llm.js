// WebLLM engine wrapper. Loads a model entirely in the browser via WebGPU and
// exposes a streaming chat-completions call with tool/function support.
import * as webllm from 'https://esm.run/@mlc-ai/web-llm';

// Curated models that fit comfortably on a phone. Smaller = faster + less RAM.
export const MODELS = [
  { id: 'Qwen2.5-0.5B-Instruct-q4f16_1-MLC', label: 'Qwen2.5 0.5B (الأخف · للأجهزة المتواضعة)', tools: true },
  { id: 'Qwen2.5-1.5B-Instruct-q4f16_1-MLC', label: 'Qwen2.5 1.5B (متوازن · موصى به)', tools: true },
  { id: 'Llama-3.2-1B-Instruct-q4f16_1-MLC', label: 'Llama 3.2 1B', tools: true },
  { id: 'Llama-3.2-3B-Instruct-q4f16_1-MLC', label: 'Llama 3.2 3B (الأقوى · للأجهزة الحديثة)', tools: true },
  { id: 'gemma-2-2b-it-q4f16_1-MLC', label: 'Gemma 2 2B', tools: false },
];

export function isWebGPUAvailable() {
  return typeof navigator !== 'undefined' && 'gpu' in navigator;
}

export class LocalLLM {
  constructor() {
    this.engine = null;
    this.modelId = null;
    this.loading = false;
  }

  get ready() {
    return !!this.engine && !this.loading;
  }

  // load (or switch) a model; onProgress({ progress 0..1, text })
  async load(modelId, onProgress) {
    if (this.modelId === modelId && this.engine) return;
    this.loading = true;
    try {
      const initProgressCallback = (r) => {
        onProgress?.({ progress: r.progress ?? 0, text: r.text || '' });
      };
      if (!this.engine) {
        this.engine = await webllm.CreateMLCEngine(modelId, { initProgressCallback });
      } else {
        this.engine.setInitProgressCallback(initProgressCallback);
        await this.engine.reload(modelId);
      }
      this.modelId = modelId;
    } finally {
      this.loading = false;
    }
  }

  // Streaming chat. `messages` is OpenAI-style. Optionally pass `tools`.
  // onDelta(textChunk) is called for each streamed token of assistant content.
  // Returns the full assistant message object (may include tool_calls).
  async chat(messages, { tools, onDelta, signal } = {}) {
    if (!this.engine) throw new Error('النموذج غير محمّل');

    const request = {
      messages,
      stream: true,
      stream_options: { include_usage: false },
      temperature: 0.6,
      max_tokens: 800,
    };
    if (tools && tools.length) {
      request.tools = tools;
      request.tool_choice = 'auto';
    }

    const chunks = await this.engine.chat.completions.create(request);

    let content = '';
    const toolCalls = [];

    for await (const chunk of chunks) {
      if (signal?.aborted) { await this.engine.interruptGenerate(); break; }
      const delta = chunk.choices?.[0]?.delta;
      if (!delta) continue;

      if (delta.content) {
        content += delta.content;
        onDelta?.(delta.content);
      }
      if (delta.tool_calls) {
        for (const tc of delta.tool_calls) {
          const i = tc.index ?? 0;
          if (!toolCalls[i]) toolCalls[i] = { id: tc.id || `call_${i}`, type: 'function', function: { name: '', arguments: '' } };
          if (tc.id) toolCalls[i].id = tc.id;
          if (tc.function?.name) toolCalls[i].function.name += tc.function.name;
          if (tc.function?.arguments) toolCalls[i].function.arguments += tc.function.arguments;
        }
      }
    }

    const msg = { role: 'assistant', content };
    const calls = toolCalls.filter(Boolean);
    if (calls.length) msg.tool_calls = calls;
    return msg;
  }

  async interrupt() {
    try { await this.engine?.interruptGenerate(); } catch {}
  }
}
