"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Markdown } from "@/components/markdown";
import { ThemeToggle } from "@/components/theme-toggle";

type Message = {
  role: string;
  content: string;
};

type Conversation = {
  id: string;
  title: string | null;
  created_at: string;
};

export default function ChatInterface() {
  const [token, setToken] = useState<string | null>(null);
  const [authMode, setAuthMode] = useState<"login" | "signup">("login");
  const [authUsername, setAuthUsername] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authError, setAuthError] = useState<string | null>(null);
  const [authLoading, setAuthLoading] = useState(false);

  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [sending, setSending] = useState(false);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState(256);
  const isResizing = useRef(false);

  const startResizing = useCallback(() => {
    isResizing.current = true;
  }, []);

  const stopResizing = useCallback(() => {
    isResizing.current = false;
  }, []);

  const resize = useCallback((event: MouseEvent) => {
    if (!isResizing.current) return;
    const next = Math.min(Math.max(event.clientX, 180), 480);
    setSidebarWidth(next);
  }, []);

  useEffect(() => {
    window.addEventListener("mousemove", resize);
    window.addEventListener("mouseup", stopResizing);
    return () => {
      window.removeEventListener("mousemove", resize);
      window.removeEventListener("mouseup", stopResizing);
    };
  }, [resize, stopResizing]);

  function authHeaders(extra: Record<string, string> = {}) {
    return { Authorization: `Bearer ${token}`, ...extra };
  }

  async function loadConversationList(tok: string) {
    const res = await fetch(`/api/conversations`, {
      headers: { Authorization: `Bearer ${tok}` },
    });
    if (res.status === 401) {
      handleLogout();
      return;
    }
    const list = await res.json();
    setConversations(Array.isArray(list) ? list : []);
  }

  async function startConversation(tok: string) {
    const res = await fetch(`/api/conversations`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${tok}` },
    });
    const conversation = await res.json();
    setConversationId(conversation.id);
    setMessages([]);
    await loadConversationList(tok);
  }

  async function openConversation(cid: string) {
    if (!token) return;
    const res = await fetch(`/api/conversations/${cid}/messages`, {
      headers: authHeaders(),
    });
    const history = await res.json();
    setConversationId(cid);
    setMessages(Array.isArray(history) ? history : []);
  }

  // Bootstraps from a saved token, or waits for login.
  useEffect(() => {
    async function setup(tok: string) {
      const res = await fetch(`/api/conversations`, {
        headers: { Authorization: `Bearer ${tok}` },
      });
      if (res.status === 401) {
        handleLogout();
        return;
      }
      const list = await res.json();
      const existing = Array.isArray(list) ? list : [];
      setConversations(existing);

      if (existing.length > 0) {
        const cid = existing[0].id;
        const msgRes = await fetch(`/api/conversations/${cid}/messages`, {
          headers: { Authorization: `Bearer ${tok}` },
        });
        const history = await msgRes.json();
        setConversationId(cid);
        setMessages(Array.isArray(history) ? history : []);
      } else {
        await startConversation(tok);
      }
    }

    const savedToken = localStorage.getItem("accessToken");
    if (savedToken) {
      setToken(savedToken);
      setup(savedToken);
    }
  }, []);

  async function handleAuthSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAuthError(null);
    setAuthLoading(true);

    try {
      if (authMode === "signup") {
        const signupRes = await fetch(
          `/api/profiles/signup?username=${encodeURIComponent(authUsername)}&password=${encodeURIComponent(authPassword)}`,
          { method: "POST" }
        );
        if (!signupRes.ok) {
          const err = await signupRes.json();
          throw new Error(err.detail ?? "Signup failed");
        }
      }

      const loginBody = new URLSearchParams();
      loginBody.set("username", authUsername);
      loginBody.set("password", authPassword);

      const loginRes = await fetch(`/api/profiles/login`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: loginBody.toString(),
      });
      if (!loginRes.ok) {
        const err = await loginRes.json();
        throw new Error(err.detail ?? "Login failed");
      }
      const data = await loginRes.json();
      localStorage.setItem("accessToken", data.access_token);
      setToken(data.access_token);
      await startConversation(data.access_token);
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setAuthLoading(false);
    }
  }

  function handleLogout() {
    localStorage.removeItem("accessToken");
    setToken(null);
    setConversations([]);
    setMessages([]);
    setConversationId(null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft.trim() || !token || !conversationId || sending) return;

    setMessages((current) => [...current, { role: "user", content: draft }]);
    const text = draft;
    setDraft("");
    setSending(true);

    const response = await fetch(
      `/api/conversations/${conversationId}/messages`,
      {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ content: text }),
      }
    );
    const reply = await response.json();

    setMessages((current) => [
      ...current,
      { role: reply.role, content: reply.content },
    ]);
    setSending(false);
    await loadConversationList(token);
  }

  function handleNewChat() {
    if (token) startConversation(token);
  }

  async function confirmDelete(cid: string) {
    if (!token) return;
    await fetch(`/api/conversations/${cid}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    setPendingDeleteId(null);

    const remaining = conversations.filter((c) => c.id !== cid);
    setConversations(remaining);

    if (cid === conversationId) {
      if (remaining.length > 0) {
        await openConversation(remaining[0].id);
      } else {
        await startConversation(token);
      }
    }
  }

  // --- Login/signup screen ---
  if (!token) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Card className="w-full max-w-sm space-y-4 p-6">
          <h1 className="text-xl font-semibold">
            {authMode === "login" ? "Log in" : "Sign up"}
          </h1>
          <form className="space-y-3" onSubmit={handleAuthSubmit}>
            <Input
              value={authUsername}
              onChange={(e) => setAuthUsername(e.target.value)}
              placeholder="Username"
              disabled={authLoading}
            />
            <Input
              type="password"
              value={authPassword}
              onChange={(e) => setAuthPassword(e.target.value)}
              placeholder="Password"
              disabled={authLoading}
            />
            {authError && (
              <p className="text-sm text-destructive">{authError}</p>
            )}
            <Button type="submit" className="w-full" disabled={authLoading}>
              {authLoading
                ? "Please wait..."
                : authMode === "login"
                  ? "Log in"
                  : "Sign up"}
            </Button>
          </form>
          <button
            className="text-sm text-muted-foreground underline"
            onClick={() =>
              setAuthMode(authMode === "login" ? "signup" : "login")
            }
          >
            {authMode === "login"
              ? "Need an account? Sign up"
              : "Already have an account? Log in"}
          </button>
        </Card>
      </div>
    );
  }

  // --- Main chat UI (unchanged layout, just header swap done above) ---
  return (
    <div className="flex h-screen overflow-hidden">
      <aside
        style={{ width: sidebarWidth }}
        className="flex shrink-0 flex-col border-r p-4 space-y-3 overflow-y-auto"
      >
        <Button className="w-full" onClick={handleNewChat}>
          New chat
        </Button>
        <div className="space-y-1">
          {conversations.map((c) =>
            pendingDeleteId === c.id ? (
              <div
                key={c.id}
                className="flex items-center justify-between gap-2 rounded-lg bg-muted px-3 py-2 text-sm"
              >
                <span className="truncate text-muted-foreground">Delete chat?</span>
                <div className="flex shrink-0 gap-1">
                  <Button
                    variant="destructive"
                    size="xs"
                    onClick={() => confirmDelete(c.id)}
                  >
                    Delete
                  </Button>
                  <Button
                    variant="ghost"
                    size="xs"
                    onClick={() => setPendingDeleteId(null)}
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            ) : (
              <div
                key={c.id}
                className={
                  "group flex items-center rounded-lg pr-1 " +
                  (c.id === conversationId ? "bg-muted" : "hover:bg-muted")
                }
              >
                <button
                  onClick={() => openConversation(c.id)}
                  className="min-w-0 flex-1 truncate px-3 py-2 text-left text-sm"
                >
                  {c.title ?? "New chat"}
                </button>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Delete conversation"
                  className="shrink-0 opacity-0 group-hover:opacity-100"
                  onClick={() => setPendingDeleteId(c.id)}
                >
                  <Trash2 />
                </Button>
              </div>
            )
          )}
        </div>
        <Button variant="ghost" className="mt-auto w-full" onClick={handleLogout}>
          Log out
        </Button>
      </aside>

      <div
        onMouseDown={startResizing}
        className="w-1 shrink-0 cursor-col-resize bg-transparent hover:bg-border active:bg-border"
      />

      <main className="mx-auto flex h-full w-full max-w-3xl flex-col gap-6 overflow-hidden px-6 py-12">
        <div className="flex shrink-0 items-center justify-between">
          <h1 className="text-3xl font-semibold">CryptoChat</h1>
          <ThemeToggle />
        </div>

        <Card className="flex-1 space-y-3 overflow-y-auto p-6">
          {messages.map((message, index) => (
            <div
              key={index}
              className={
                message.role === "user"
                  ? "ml-auto max-w-[80%] rounded-2xl bg-primary px-4 py-3 text-primary-foreground"
                  : "max-w-[80%] rounded-2xl bg-muted px-4 py-3"
              }
            >
              {message.role === "user" ? (
                message.content
              ) : (
                <Markdown content={message.content} />
              )}
            </div>
          ))}
          {sending && (
            <div className="max-w-[80%] rounded-2xl bg-muted px-4 py-3 text-muted-foreground">
              Thinking...
            </div>
          )}
        </Card>

        <form className="flex shrink-0 gap-3" onSubmit={handleSubmit}>
          <Input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Type a message..."
            disabled={sending}
          />
          <Button type="submit" disabled={sending}>
            Send
          </Button>
        </form>
      </main>
    </div>
  );
}