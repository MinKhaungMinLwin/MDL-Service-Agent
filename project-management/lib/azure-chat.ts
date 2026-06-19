import type { ChatMessage } from "@/lib/types";

type AzureChatOptions = {
  systemPrompt: string;
  messages: ChatMessage[];
};

export function isAzureChatConfigured(): boolean {
  return Boolean(
    process.env.AZURE_OPENAI_ENDPOINT &&
      process.env.AZURE_OPENAI_API_KEY &&
      process.env.AZURE_OPENAI_CHAT_DEPLOYMENT,
  );
}

export async function chatWithAzure({ systemPrompt, messages }: AzureChatOptions): Promise<string> {
  const endpoint = process.env.AZURE_OPENAI_ENDPOINT!.replace(/\/$/, "");
  const deployment = process.env.AZURE_OPENAI_CHAT_DEPLOYMENT!;
  const apiVersion = process.env.AZURE_OPENAI_CHAT_API_VERSION ?? "2024-12-01-preview";

  const url = `${endpoint}/openai/deployments/${deployment}/chat/completions?api-version=${apiVersion}`;

  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "api-key": process.env.AZURE_OPENAI_API_KEY!,
    },
    body: JSON.stringify({
      messages: [
        { role: "system", content: systemPrompt || "You are a helpful assistant." },
        ...messages.map((message) => ({ role: message.role, content: message.content })),
      ],
      temperature: 0.7,
      max_tokens: 1024,
    }),
  });

  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Azure OpenAI error (${res.status}): ${detail.slice(0, 200)}`);
  }

  const data = (await res.json()) as {
    choices?: { message?: { content?: string } }[];
  };

  return data.choices?.[0]?.message?.content?.trim() ?? "";
}

export function mockChatReply(agentName: string, userMessage: string, logic: string): string {
  const logicPreview = logic.trim()
    ? `\n\n[적용된 개발 로직]\n${logic.trim().slice(0, 300)}${logic.length > 300 ? "…" : ""}`
    : "\n\n[개발 로직이 비어 있습니다. logic 탭에서 등록하세요.]";

  return `[테스트 모드] ${agentName}\n\n입력: ${userMessage}${logicPreview}\n\n실제 LLM 테스트는 AZURE_OPENAI_* 환경 변수 설정 후 가능합니다.`;
}
