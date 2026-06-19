import { NextResponse } from "next/server";
import { readAgents } from "@/lib/agent-utils";
import { chatWithAzure, isAzureChatConfigured, mockChatReply } from "@/lib/azure-chat";
import type { ChatMessage } from "@/lib/types";

type Props = {
  params: Promise<{ id: string }>;
};

export async function POST(request: Request, { params }: Props) {
  const { id } = await params;
  const body = (await request.json()) as { messages?: ChatMessage[] };
  const messages = body.messages ?? [];

  const agents = await readAgents();
  const agent = agents.find((entry) => entry.id === id);
  if (!agent) return NextResponse.json({ error: "Not found" }, { status: 404 });

  const lastUser = [...messages].reverse().find((message) => message.role === "user");
  if (!lastUser?.content.trim()) {
    return NextResponse.json({ error: "Message is required" }, { status: 400 });
  }

  try {
    const reply = isAzureChatConfigured()
      ? await chatWithAzure({
          systemPrompt: agent.logic || `You are ${agent.name}. ${agent.description}`,
          messages,
        })
      : mockChatReply(agent.name, lastUser.content, agent.logic);

    return NextResponse.json({ reply });
  } catch (error) {
    const message = error instanceof Error ? error.message : "Chat failed";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
