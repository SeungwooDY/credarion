"use client";

import { useState, useRef, useEffect, useCallback } from "react";

interface Message {
  role: "user" | "assistant";
  content: string;
}

interface ChatContext {
  page?: string;
  supplier?: {
    name: string;
    vendor_code: string;
    match_rate: number | null;
    total_mismatches: number;
    unmatched_erp: number;
    unmatched_stmt: number;
    qty_issues: number;
    price_issues: number;
  };
  mismatches?: {
    po_number?: string;
    part_number?: string;
    discrepancy_type?: string;
    quantity_delta?: number | null;
    price_delta?: number | null;
    amount_delta?: number | null;
    status?: string;
  }[];
  summary?: Record<string, unknown>;
}

// Global context store — pages set this to inject context into the chat
let _globalContext: ChatContext = {};
const _listeners: Set<() => void> = new Set();

export function setChatContext(ctx: ChatContext) {
  _globalContext = ctx;
  _listeners.forEach((fn) => fn());
}

function useChatContext(): ChatContext {
  const [ctx, setCtx] = useState(_globalContext);
  useEffect(() => {
    const listener = () => setCtx({ ..._globalContext });
    _listeners.add(listener);
    return () => { _listeners.delete(listener); };
  }, []);
  return ctx;
}

export default function ChatPanel() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const context = useChatContext();

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
          context: Object.keys(context).length > 0 ? context : undefined,
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

  const contextLabel = context.supplier?.name || context.page || null;

  return (
    <>
      {/* Floating button */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed bottom-6 right-6 w-12 h-12 rounded-full bg-gradient-to-br from-[#7c4dff] via-accent to-accent-dark text-white shadow-lg hover:shadow-xl transition-all flex items-center justify-center z-50 group"
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
          {/* Header */}
          <div className="px-4 py-3 flex items-center justify-between shrink-0 bg-gradient-to-r from-[#7c4dff] via-accent to-accent-dark text-white rounded-t-2xl">
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-full bg-white/20 flex items-center justify-center text-xs font-bold">
                C
              </div>
              <div>
                <div className="text-sm font-semibold">Credarion Assistant</div>
                {contextLabel && (
                  <div className="text-[10px] opacity-70 truncate max-w-[200px]">
                    Context: {contextLabel}
                  </div>
                )}
              </div>
            </div>
            <div className="flex items-center gap-1">
              {messages.length > 0 && (
                <button
                  onClick={() => setMessages([])}
                  className="p-1.5 rounded-lg hover:bg-white/15 transition-colors"
                  title="Clear chat"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="3 6 5 6 21 6" />
                    <path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
                  </svg>
                </button>
              )}
              <button
                onClick={() => setOpen(false)}
                className="p-1.5 rounded-lg hover:bg-white/15 transition-colors"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
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
                <p className="text-sm font-medium text-zinc-700">Ask me anything</p>
                <p className="text-xs text-zinc-400 mt-1 max-w-[260px] mx-auto">
                  I can help you understand mismatches, explain discrepancies, and suggest corrective actions.
                </p>
                <div className="mt-4 space-y-1.5">
                  {[
                    "Why are there so many quantity mismatches?",
                    "Which items should I investigate first?",
                    "Summarize the issues for this supplier",
                  ].map((q) => (
                    <button
                      key={q}
                      onClick={() => {
                        setInput(q);
                        setTimeout(() => inputRef.current?.focus(), 0);
                      }}
                      className="block w-full text-left px-3 py-2 text-xs text-zinc-600 bg-muted rounded-lg hover:bg-accent-light hover:text-accent transition-colors"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((msg, i) => (
              <div
                key={i}
                className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={`max-w-[85%] px-3 py-2 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap ${
                    msg.role === "user"
                      ? "bg-accent text-white rounded-br-md"
                      : "bg-muted text-zinc-800 rounded-bl-md"
                  }`}
                >
                  {msg.content}
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
                placeholder="Ask about mismatches..."
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
