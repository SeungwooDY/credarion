"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import { useCurrentOrg } from "../lib/swr";
import { useT } from "@/app/lib/i18n";

interface Message {
  role: "user" | "assistant";
  content: string;
}

export default function ChatPanel() {
  const t = useT();
  const { orgId: currentOrgId, orgName } = useCurrentOrg();
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // The logged-in user's organization.
  const orgId = currentOrgId || null;

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  useEffect(() => {
    if (open && inputRef.current) {
      inputRef.current.focus();
    }
  }, [open]);

  async function sendMessage() {
    const text = input.trim();
    if (!text || streaming) return;

    const userMsg: Message = { role: "user", content: text };
    const newMessages = [...messages, userMsg];
    setMessages(newMessages);
    setInput("");
    setStreaming(true);

    const assistantMsg: Message = { role: "assistant", content: "" };
    setMessages([...newMessages, assistantMsg]);

    try {
      const res = await fetch("/api/v1/chat/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          history: messages.slice(-20).map((m) => ({
            role: m.role,
            content: m.content,
          })),
          org_id: orgId,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        setMessages([
          ...newMessages,
          { role: "assistant", content: `Error: ${err.detail || "Something went wrong"}` },
        ]);
        setStreaming(false);
        return;
      }

      const reader = res.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let fullContent = "";

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed.startsWith("data: ")) continue;
            try {
              const data = JSON.parse(trimmed.slice(6));
              if (data.type === "text") {
                fullContent += data.content;
                setMessages([
                  ...newMessages,
                  { role: "assistant", content: fullContent },
                ]);
              } else if (data.type === "error") {
                fullContent += `\n\nError: ${data.content}`;
                setMessages([
                  ...newMessages,
                  { role: "assistant", content: fullContent },
                ]);
              }
            } catch {
              // skip malformed chunks
            }
          }
        }
      }
    } catch (e) {
      setMessages([
        ...newMessages,
        { role: "assistant", content: `Connection error: ${e instanceof Error ? e.message : String(e)}` },
      ]);
    }

    setStreaming(false);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  return (
    <>
      {/* Floating button */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed bottom-6 right-6 w-12 h-12 rounded-full bg-gradient-to-br from-[#5e82ec] via-accent to-accent-dark text-white shadow-lg hover:shadow-xl transition-all flex items-center justify-center z-50 group"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="group-hover:scale-110 transition-transform">
            <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
          </svg>
          {messages.length > 0 && (
            <span className="absolute -top-1 -right-1 w-4 h-4 bg-red-500 rounded-full text-[9px] font-bold flex items-center justify-center">
              {messages.filter((m) => m.role === "assistant").length}
            </span>
          )}
        </button>
      )}

      {/* Chat panel */}
      {open && (
        <div className="fixed bottom-6 right-6 w-[400px] h-[560px] rounded-2xl shadow-2xl border border-border flex flex-col z-50 overflow-hidden" style={{ backgroundColor: "#ffffff" }}>
          {/* Header — click anywhere to minimize */}
          <div
            onClick={() => setOpen(false)}
            className="px-4 py-3 flex items-center justify-between shrink-0 bg-gradient-to-r from-[#5e82ec] via-accent to-accent-dark text-white rounded-t-2xl cursor-pointer select-none"
          >
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-full bg-white/20 flex items-center justify-center text-xs font-bold">
                C
              </div>
              <div>
                <div className="text-sm font-semibold">{t("chat.title")}</div>
                {orgName && (
                  <div className="text-[10px] opacity-70 truncate max-w-[200px]">
                    {orgName}
                  </div>
                )}
              </div>
            </div>
            <div className="flex items-center gap-1">
              {messages.length > 0 && (
                <button
                  onClick={(e) => { e.stopPropagation(); setMessages([]); }}
                  className="p-1.5 rounded-lg hover:bg-white/15 transition-colors"
                  title={t("chat.clear_chat")}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="3 6 5 6 21 6" />
                    <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
                  </svg>
                </button>
              )}
              {/* Minimize chevron */}
              <div className="p-1.5 rounded-lg hover:bg-white/15 transition-colors">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="6 9 12 15 18 9" />
                </svg>
              </div>
            </div>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3 bg-white">
            {messages.length === 0 && (
              <div className="text-center py-8">
                <div className="w-10 h-10 rounded-full bg-accent-light flex items-center justify-center mx-auto mb-3">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-accent">
                    <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
                  </svg>
                </div>
                <p className="text-sm font-medium text-zinc-700">{t("chat.ask_anything")}</p>
                <p className="text-xs text-zinc-400 mt-1 max-w-[260px] mx-auto">
                  {t("chat.empty_subtitle")}
                </p>
                <div className="mt-4 space-y-1.5">
                  {[
                    "chat.suggest_status",
                    "chat.suggest_mismatches",
                    "chat.suggest_at_risk",
                  ].map((key) => {
                    const q = t(key);
                    return (
                      <button
                        key={key}
                        onClick={() => {
                          setInput(q);
                          setTimeout(() => inputRef.current?.focus(), 0);
                        }}
                        className="block w-full text-left px-3 py-2 text-xs text-zinc-600 bg-muted rounded-lg hover:bg-accent-light hover:text-accent transition-colors"
                      >
                        {q}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {messages.map((msg, i) => (
              <div
                key={i}
                className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={`max-w-[85%] px-3 py-2 rounded-2xl text-sm leading-relaxed ${
                    msg.role === "user"
                      ? "bg-accent text-white rounded-br-md whitespace-pre-wrap"
                      : "bg-muted text-zinc-800 rounded-bl-md"
                  }`}
                >
                  {msg.role === "assistant" ? (
                    <div className="chat-markdown">
                      <ReactMarkdown>{msg.content}</ReactMarkdown>
                    </div>
                  ) : (
                    msg.content
                  )}
                  {streaming && i === messages.length - 1 && msg.role === "assistant" && (
                    <span className="inline-block w-1.5 h-4 bg-accent/50 ml-0.5 animate-pulse rounded-sm" />
                  )}
                </div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <div className="px-3 pb-3 pt-1 shrink-0 bg-white">
            <div className="flex items-end gap-2 bg-muted rounded-xl px-3 py-2">
              <textarea
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={t("chat.input_placeholder")}
                rows={1}
                className="flex-1 bg-transparent text-sm resize-none outline-none max-h-24 placeholder:text-zinc-400"
                style={{
                  height: "auto",
                  minHeight: "24px",
                }}
                onInput={(e) => {
                  const target = e.target as HTMLTextAreaElement;
                  target.style.height = "auto";
                  target.style.height = Math.min(target.scrollHeight, 96) + "px";
                }}
              />
              <button
                onClick={sendMessage}
                disabled={!input.trim() || streaming}
                className="shrink-0 w-7 h-7 rounded-lg bg-accent text-white flex items-center justify-center disabled:opacity-30 hover:bg-accent-dark transition-colors"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="22" y1="2" x2="11" y2="13" />
                  <polygon points="22 2 15 22 11 13 2 9 22 2" />
                </svg>
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
