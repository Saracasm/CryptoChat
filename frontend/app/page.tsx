"use client";

import { FormEvent, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

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
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [profileId, setProfileId] = useState<string | null>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [sending, setSending] = useState(false);

  async function loadConversationList(pid: string) {
    const res = await fetch(`/api/conversations`, {
      headers: { "X-Profile-Id": pid },
    });
    const list = await res.json();
    setConversations(Array.isArray(list) ? list : []);
  }

  async function startConversation(pid: string) {
    const res = await fetch(`/api/conversations`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Profile-Id": pid },
    });
    const conversation = await res.json();
    setConversationId(conversation.id);
    setMessages([]);
    await loadConversationList(pid);
  }

  async function openConversation(cid: string) {
    if (!profileId) return;
    const res = await fetch(`/api/conversations/${cid}/messages`, {
      headers: { "X-Profile-Id": profileId },
    });
    const history = await res.json();
    setConversationId(cid);
    setMessages(Array.isArray(history) ? history : []);
  }

  useEffect(() => {
    async function setup() {
      const savedProfile = localStorage.getItem("profileId");

      if (savedProfile) {
        setProfileId(savedProfile);
        const res = await fetch(`/api/conversations`, {
          headers: { "X-Profile-Id": savedProfile },
        });
        const list = await res.json();
        const existing = Array.isArray(list) ? list : [];
        setConversations(existing);

        if (existing.length > 0) {
          const cid = existing[0].id;
          const msgRes = await fetch(`/api/conversations/${cid}/messages`, {
            headers: { "X-Profile-Id": savedProfile },
          });
          const history = await msgRes.json();
          setConversationId(cid);
          setMessages(Array.isArray(history) ? history : []);
        } else {
          await startConversation(savedProfile);
        }
        return;
      }

      // First visit: create a profile and remember it.
      const profileRes = await fetch(`/api/profiles`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "Demo User" }),
      });
      const profile = await profileRes.json();
      localStorage.setItem("profileId", profile.id);
      setProfileId(profile.id);
      await startConversation(profile.id);
    }
    setup();
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!draft.trim() || !profileId || !conversationId || sending) return;

    setMessages((current) => [...current, { role: "user", content: draft }]);
    const text = draft;
    setDraft("");
    setSending(true);

    const response = await fetch(
      `/api/conversations/${conversationId}/messages`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Profile-Id": profileId },
        body: JSON.stringify({ content: text }),
      }
    );
    const reply = await response.json();

    setMessages((current) => [
      ...current,
      { role: reply.role, content: reply.content },
    ]);
    setSending(false);
    await loadConversationList(profileId);
  }

  function handleNewChat() {
    if (profileId) startConversation(profileId);
  }

  return (
    <div className="flex min-h-screen">
      {/* Sidebar: chat history */}
      <aside className="w-64 shrink-0 border-r p-4 space-y-3">
        <Button className="w-full" onClick={handleNewChat}>
          New chat
        </Button>
        <div className="space-y-1">
          {conversations.map((c) => (
            <button
              key={c.id}
              onClick={() => openConversation(c.id)}
              className={
                "w-full truncate rounded-lg px-3 py-2 text-left text-sm " +
                (c.id === conversationId ? "bg-muted" : "hover:bg-muted")
              }
            >
              {c.title ?? "New chat"}
            </button>
          ))}
        </div>
      </aside>

      {/* Main chat area */}
      <main className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-6 py-12">
        <h1 className="text-3xl font-semibold">Week 2 Demo - CryptoChat</h1>

        <Card className="flex-1 space-y-3 p-6">
          {messages.map((message, index) => (
            <div
              key={index}
              className={
                message.role === "user"
                  ? "ml-auto max-w-[80%] rounded-2xl bg-primary px-4 py-3 text-primary-foreground"
                  : "max-w-[80%] rounded-2xl bg-muted px-4 py-3"
              }
            >
              {message.content}
            </div>
          ))}
          {sending && (
            <div className="max-w-[80%] rounded-2xl bg-muted px-4 py-3 text-muted-foreground">
              Thinking...
            </div>
          )}
        </Card>

        <form className="flex gap-3" onSubmit={handleSubmit}>
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