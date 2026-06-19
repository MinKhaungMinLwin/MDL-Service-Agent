"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useLocale } from "@/components/LocaleProvider";
import type { Agent, ChatMessage } from "@/lib/types";

type Props = {
  agent: Agent;
};

export default function AgentPlayground({ agent }: Props) {
  const { t } = useLocale();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || loading) return;

    const nextMessages: ChatMessage[] = [...messages, { role: "user", content: text }];
    setMessages(nextMessages);
    setInput("");
    setLoading(true);
    setError("");

    try {
      const res = await fetch(`/api/agents/${agent.id}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: nextMessages }),
      });
      const data = (await res.json()) as { reply?: string; error?: string };
      if (!res.ok) {
        setError(data.error ?? t.agents.chatError);
        setMessages(messages);
        return;
      }
      setMessages([...nextMessages, { role: "assistant", content: data.reply ?? "" }]);
    } catch {
      setError(t.agents.chatError);
      setMessages(messages);
    } finally {
      setLoading(false);
    }
  }

  function clearChat() {
    setMessages([]);
    setError("");
  }

  return (
    <div className="playground">
      <div className="playground-toolbar">
        <p className="playground-hint">{t.agents.playgroundHint}</p>
        <div className="btn-row">
          <Link href={`/agents/${agent.id}/logic`} className="btn btn-sm">
            {t.agents.tabLogic}
          </Link>
          <Link href={`/agents/${agent.id}/flow`} className="btn btn-sm">
            {t.agents.tabFlow}
          </Link>
          <button type="button" className="btn btn-sm" onClick={clearChat}>
            {t.agents.clearChat}
          </button>
        </div>
      </div>

      <div className="chat-panel">
        <div className="chat-messages">
          {messages.length === 0 && (
            <p className="chat-empty">{t.agents.chatEmpty}</p>
          )}
          {messages.map((message, index) => (
            <div
              key={`${message.role}-${index}`}
              className={`chat-bubble chat-bubble-${message.role}`}
            >
              <span className="chat-role">
                {message.role === "user" ? t.agents.chatYou : agent.name}
              </span>
              <div className="chat-content">{message.content}</div>
            </div>
          ))}
          {loading && (
            <div className="chat-bubble chat-bubble-assistant">
              <span className="chat-role">{agent.name}</span>
              <div className="chat-content chat-typing">{t.agents.chatTyping}</div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <form className="chat-input-row" onSubmit={handleSend}>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={t.agents.chatPlaceholder}
            disabled={loading}
          />
          <button type="submit" className="btn btn-primary" disabled={loading || !input.trim()}>
            {t.agents.chatSend}
          </button>
        </form>
        {error && <p className="form-error chat-error">{error}</p>}
      </div>
    </div>
  );
}
