"use client";

import { ChangeEvent, FormEvent, useCallback, useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { BarChart3, ChevronLeft, ChevronRight, FileText, MessageSquare, Plus, Send, Trash2, Upload } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Markdown } from "@/components/markdown";
import { ThemeToggle } from "@/components/theme-toggle";

const Plot = dynamic(() => import("react-plotly.js"), { ssr: false });

type Message = {
  role: string;
  content: string;
};

type Conversation = {
  id: string;
  title: string | null;
  created_at: string;
};

type ChartMetric = "price_usd" | "daily_change_pct" | "market_cap_usd" | "volume_usd";

type MarketChart = {
  title: string;
  chart: {
    data: object[];
    layout: object;
  };
};

type Holding = {
  amount: number;
  current_value: number | null;
  profit_loss: number | null;
  portfolio_weight_percent: number | null;
  change_24h_percent: number | null;
};

type PortfolioTotal = {
  cost_basis: number;
  current_value: number | null;
  profit_loss: number | null;
  today_move_usd: number | null;
  today_move_percent: number | null;
};
type PortfolioMeta = { prices_unavailable: boolean; message: string };
type Portfolio = {
  _total?: PortfolioTotal;
  _meta?: PortfolioMeta;
  message?: string;
  [coin: string]: Holding | PortfolioTotal | PortfolioMeta | string | undefined;
};

type PortfolioChartType = "allocation" | "profit_loss" | "cost_vs_value";

type PortfolioChart = {
  chart_type: PortfolioChartType;
  title: string;
  chart: {
    data: object[];
    layout: object;
  };
};

type PinnedChart = {
  id: string;
  title: string;
  chart: {
    data: object[];
    layout: object;
  };
};

type DataframeInfo = {
  columns: string[];
  row_count: number;
  preview: Record<string, unknown>[];
};

type CustomChartResult = {
  dataframe: string;
  code: string;
  chart: {
    data: object[];
    layout: object;
  };
};

type UploadedDocument = {
  id: string;
  filename: string;
  content_type: string;
  created_at: string;
};

const ALLOWED_UPLOAD_EXTENSIONS = ".pdf,.docx,.md,.markdown,.txt,.csv";

const PORTFOLIO_CHART_OPTIONS: { type: PortfolioChartType; label: string }[] = [
  { type: "allocation", label: "Allocation donut" },
  { type: "profit_loss", label: "P&L by coin" },
  { type: "cost_vs_value", label: "Cost vs. value" },
];

const currency = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});

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
  const [dashboardWidth, setDashboardWidth] = useState(350);
  const [dashboardCollapsed, setDashboardCollapsed] = useState(false);
  const [selectedCoin, setSelectedCoin] = useState("bitcoin");
  const [selectedMetric, setSelectedMetric] = useState<ChartMetric>("daily_change_pct");
  const [selectedDays, setSelectedDays] = useState(30);
  const [marketChart, setMarketChart] = useState<MarketChart | null>(null);
  const [chartLoading, setChartLoading] = useState(false);
  const [chartError, setChartError] = useState<string | null>(null);
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [portfolioLoading, setPortfolioLoading] = useState(false);
  const [portfolioError, setPortfolioError] = useState<string | null>(null);
  const [portfolioChartType, setPortfolioChartType] = useState<PortfolioChartType>("allocation");
  const [portfolioChart, setPortfolioChart] = useState<PortfolioChart | null>(null);
  const [portfolioChartLoading, setPortfolioChartLoading] = useState(false);
  const [portfolioChartError, setPortfolioChartError] = useState<string | null>(null);
  const [pinnedCharts, setPinnedCharts] = useState<PinnedChart[]>([]);
  const [documents, setDocuments] = useState<UploadedDocument[]>([]);
  const [documentsLoading, setDocumentsLoading] = useState(false);
  const [documentsError, setDocumentsError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadStatus, setUploadStatus] = useState<string | null>(null);
  const [customChartOpen, setCustomChartOpen] = useState(false);
  const [dataframeInfo, setDataframeInfo] = useState<DataframeInfo | null>(null);
  const [dataframeLoading, setDataframeLoading] = useState(false);
  const [dataframeError, setDataframeError] = useState<string | null>(null);
  const [customChartCode, setCustomChartCode] = useState("");
  const [customChartPrompt, setCustomChartPrompt] = useState("");
  const [customChartGenerated, setCustomChartGenerated] = useState(false);
  const [customChartResult, setCustomChartResult] = useState<CustomChartResult | null>(null);
  const [customChartRunning, setCustomChartRunning] = useState(false);
  const [customChartGenerating, setCustomChartGenerating] = useState(false);
  const [customChartError, setCustomChartError] = useState<string | null>(null);
  const resizingPanel = useRef<"sidebar" | "dashboard" | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const startResizing = useCallback(() => {
    resizingPanel.current = "sidebar";
  }, []);

  const startDashboardResizing = useCallback(() => {
    if (!dashboardCollapsed) resizingPanel.current = "dashboard";
  }, [dashboardCollapsed]);

  const stopResizing = useCallback(() => {
    resizingPanel.current = null;
  }, []);

  const resize = useCallback((event: MouseEvent) => {
    if (resizingPanel.current === "sidebar") {
      setSidebarWidth(Math.min(Math.max(event.clientX, 180), 480));
    }
    if (resizingPanel.current === "dashboard") {
      setDashboardWidth(Math.min(Math.max(window.innerWidth - event.clientX, 300), 560));
    }
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

  const loadMarketChart = useCallback(async () => {
    if (!token || !conversationId) return;
    setChartLoading(true);
    setChartError(null);
    try {
      const response = await fetch(`/api/conversations/${conversationId}/visualizations`, {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          coin: selectedCoin,
          metric: selectedMetric,
          days: selectedDays,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "Unable to load market data.");
      setMarketChart(data);
    } catch (error) {
      setMarketChart(null);
      setChartError(error instanceof Error ? error.message : "Unable to load market data.");
    } finally {
      setChartLoading(false);
    }
  }, [conversationId, token, selectedCoin, selectedDays, selectedMetric]);

  useEffect(() => {
    if (!dashboardCollapsed && token) loadMarketChart();
  }, [dashboardCollapsed, loadMarketChart, token]);

  const loadPortfolio = useCallback(async () => {
    if (!token || !conversationId) return;
    setPortfolioLoading(true);
    setPortfolioError(null);
    try {
      const response = await fetch(`/api/conversations/${conversationId}/portfolio`, {
        headers: authHeaders(),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "Unable to load portfolio.");
      setPortfolio(data);
    } catch (error) {
      setPortfolio(null);
      setPortfolioError(error instanceof Error ? error.message : "Unable to load portfolio.");
    } finally {
      setPortfolioLoading(false);
    }
  }, [conversationId, token]);

  useEffect(() => {
    if (!dashboardCollapsed && token) loadPortfolio();
  }, [dashboardCollapsed, loadPortfolio, token]);

  const loadPortfolioChart = useCallback(async () => {
    if (!token || !conversationId) return;
    setPortfolioChartLoading(true);
    setPortfolioChartError(null);
    try {
      const response = await fetch(`/api/conversations/${conversationId}/portfolio-chart`, {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ chart_type: portfolioChartType }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "Unable to build portfolio chart.");
      setPortfolioChart(data);
    } catch (error) {
      setPortfolioChart(null);
      setPortfolioChartError(error instanceof Error ? error.message : "Unable to build portfolio chart.");
    } finally {
      setPortfolioChartLoading(false);
    }
  }, [conversationId, portfolioChartType, token]);

  useEffect(() => {
    if (!dashboardCollapsed && token) loadPortfolioChart();
  }, [dashboardCollapsed, loadPortfolioChart, token]);

  function pinPortfolioChart() {
    if (!portfolioChart) return;
    setPinnedCharts((current) => [
      ...current,
      { id: `${Date.now()}`, title: portfolioChart.title, chart: portfolioChart.chart },
    ]);
  }

  function unpinChart(id: string) {
    setPinnedCharts((current) => current.filter((c) => c.id !== id));
  }

  const loadDocuments = useCallback(async () => {
    if (!token) return;
    setDocumentsLoading(true);
    setDocumentsError(null);
    try {
      const response = await fetch(`/api/documents`, {
        headers: authHeaders(),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "Unable to load documents.");
      setDocuments(data);
    } catch (error) {
      setDocuments([]);
      setDocumentsError(error instanceof Error ? error.message : "Unable to load documents.");
    } finally {
      setDocumentsLoading(false);
    }
  }, [token]);

  useEffect(() => {
    if (!dashboardCollapsed && token) loadDocuments();
  }, [dashboardCollapsed, loadDocuments, token]);

  async function handleFileSelected(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = ""; // reset so re-selecting the same file re-triggers onChange
    if (!file || !token) return;

    setUploading(true);
    setUploadError(null);
    setUploadStatus(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const response = await fetch(`/api/documents`, {
        method: "POST",
        headers: authHeaders(),
        body: formData,
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "Upload failed.");
      setUploadStatus(
        `${data.filename} indexed — ${data.chunk_count} chunk${data.chunk_count === 1 ? "" : "s"} ready to search.`
      );
      await loadDocuments();
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  }

  async function openCustomChartModal() {
    setCustomChartOpen(true);
    if (dataframeInfo || !token || !conversationId) return;
    setDataframeLoading(true);
    setDataframeError(null);
    try {
      const response = await fetch(`/api/conversations/${conversationId}/dataframes`, {
        headers: authHeaders(),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "Unable to load available data.");
      const portfolio = data.dataframes?.portfolio as DataframeInfo | undefined;
      if (!portfolio) {
        setDataframeError("No portfolio data yet — log a purchase first.");
        return;
      }
      setDataframeInfo(portfolio);
    } catch (error) {
      setDataframeError(error instanceof Error ? error.message : "Unable to load available data.");
    } finally {
      setDataframeLoading(false);
    }
  }

  function closeCustomChartModal() {
    setCustomChartOpen(false);
    setCustomChartGenerated(false);
    setCustomChartCode("");
    setCustomChartPrompt("");
    setCustomChartResult(null);
    setCustomChartError(null);
  }

  async function runCustomChart(code: string) {
    if (!token || !conversationId || !code.trim()) return;
    setCustomChartRunning(true);
    setCustomChartError(null);
    try {
      const response = await fetch(`/api/conversations/${conversationId}/custom-chart`, {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ code }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "Unable to run this code.");
      setCustomChartResult(data);
      setCustomChartCode(data.code);
    } catch (error) {
      setCustomChartResult(null);
      setCustomChartError(error instanceof Error ? error.message : "Unable to run this code.");
    } finally {
      setCustomChartRunning(false);
    }
  }

  async function generateChartWithAI() {
    if (!token || !conversationId || !customChartPrompt.trim()) return;
    setCustomChartGenerating(true);
    setCustomChartError(null);
    try {
      const response = await fetch(`/api/conversations/${conversationId}/custom-chart`, {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ prompt: customChartPrompt }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "Unable to generate a chart for that.");
      setCustomChartResult(data);
      setCustomChartCode(data.code);
      setCustomChartGenerated(true);
    } catch (error) {
      setCustomChartResult(null);
      setCustomChartError(error instanceof Error ? error.message : "Unable to generate a chart for that.");
    } finally {
      setCustomChartGenerating(false);
    }
  }

  function pinCustomChart() {
    if (!customChartResult) return;
    setPinnedCharts((current) => [
      ...current,
      { id: `${Date.now()}`, title: "Custom graph", chart: customChartResult.chart },
    ]);
    setDashboardCollapsed(false);
    setCustomChartOpen(false);
  }

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

  async function sendMessage(text: string) {
    if (!text.trim() || !token || !conversationId || sending) return;

    setMessages((current) => [...current, { role: "user", content: text }]);
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
    await loadPortfolio();
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await sendMessage(draft);
  }

  const QUICK_COMMANDS = [
    "Show my allocation",
    "Explain today's BTC move",
    "Rebalance suggestions",
    "Compare ETH vs SOL",
  ];

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

  const portfolioTotal = portfolio?._total as PortfolioTotal | undefined;
  const pricesUnavailable = portfolio?._meta?.prices_unavailable ?? false;
  const portfolioHoldings = Object.entries(portfolio ?? {})
    .filter(([coin, value]) => coin !== "_total" && coin !== "_meta" && typeof value === "object" && value !== null && "amount" in value)
    .map(([coin, value]) => ({ coin, ...(value as Holding) }));
  const portfolioChangePercent = portfolioTotal?.cost_basis && portfolioTotal.profit_loss !== null
    ? (portfolioTotal.profit_loss / portfolioTotal.cost_basis) * 100
    : 0;

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Sidebar: chat history */}
      <aside
        style={{ width: sidebarWidth }}
        className="flex shrink-0 flex-col border-r bg-sidebar p-4 text-sidebar-foreground space-y-5 overflow-y-auto"
      >
        <div className="flex items-center gap-2 px-1 text-sm font-semibold">
          <span className="size-2 rounded-full bg-primary" />
          Portfolio Assistant
        </div>
        <Button className="w-full" onClick={handleNewChat}>
          <Plus />
          New chat
        </Button>
        <div className="space-y-2">
          <p className="px-1 text-xs font-medium tracking-wider text-muted-foreground">
            CONVERSATIONS
          </p>
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

      <main className="flex min-w-0 flex-1 flex-col gap-5 overflow-hidden px-6 py-7 xl:px-8">
        <div className="flex shrink-0 items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold">AI chat</h1>
            <p className="text-sm text-muted-foreground">
              Ask about your portfolio or the market
            </p>
          </div>
          <ThemeToggle />
        </div>

        <Card className="flex-1 overflow-y-auto p-6">
          {messages.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center text-center">
              <div className="mb-4 grid size-14 place-items-center rounded-full bg-primary/10 text-primary">
                <MessageSquare className="size-6" />
              </div>
              <h2 className="text-2xl font-semibold">Ask anything about your portfolio</h2>
              <p className="mt-2 max-w-md text-sm text-muted-foreground">
                Get analysis, compare assets, upload a statement, or log a purchase.
              </p>
              <div className="mt-6 flex flex-wrap justify-center gap-2">
                {QUICK_COMMANDS.map((prompt) => (
                  <Button
                    key={prompt}
                    variant="outline"
                    size="sm"
                    disabled={sending}
                    onClick={() => sendMessage(prompt)}
                  >
                    {prompt}
                  </Button>
                ))}
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              {messages.map((message, index) => (
                <div
                  key={index}
                  className={
                    message.role === "user"
                      ? "ml-auto max-w-[80%] rounded-2xl bg-primary px-4 py-3 text-primary-foreground"
                      : "max-w-[80%] rounded-2xl bg-muted px-4 py-3"
                  }
                >
                  {message.role === "user" ? message.content : <Markdown content={message.content} />}
                </div>
              ))}
              {sending && (
                <div className="max-w-[80%] rounded-2xl bg-muted px-4 py-3 text-muted-foreground">
                  Thinking...
                </div>
              )}
            </div>
          )}
        </Card>

        {messages.length > 0 && (
          <div className="flex shrink-0 flex-wrap gap-2">
            {QUICK_COMMANDS.map((prompt) => (
              <Button
                key={prompt}
                type="button"
                variant="outline"
                size="sm"
                disabled={sending}
                onClick={() => sendMessage(prompt)}
              >
                {prompt}
              </Button>
            ))}
          </div>
        )}

        <form className="flex shrink-0 gap-3" onSubmit={handleSubmit}>
          <input
            ref={fileInputRef}
            type="file"
            accept={ALLOWED_UPLOAD_EXTENSIONS}
            onChange={handleFileSelected}
            className="hidden"
          />
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label="Upload a file"
            disabled={uploading || !token}
            onClick={() => fileInputRef.current?.click()}
          >
            <Upload />
          </Button>
          <Input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Ask a question or upload a file..."
            disabled={sending}
          />
          <Button type="submit" size="icon" disabled={sending} aria-label="Send message">
            <Send />
          </Button>
        </form>
        {(uploading || uploadError || uploadStatus) && (
          <p
            className={
              uploadError
                ? "shrink-0 text-xs text-destructive"
                : "shrink-0 text-xs text-muted-foreground"
            }
          >
            {uploading ? "Uploading…" : uploadError ?? uploadStatus}
          </p>
        )}
      </main>

      {/* Dashboard: charts and portfolio data */}
      <div className="hidden shrink-0 xl:flex">
        <div
          onMouseDown={startDashboardResizing}
          className="w-1 cursor-col-resize bg-transparent hover:bg-border active:bg-border"
          aria-label="Resize dashboard"
        />
        <aside
          style={{ width: dashboardCollapsed ? 48 : dashboardWidth }}
          className="flex shrink-0 flex-col overflow-hidden border-l bg-card transition-[width] duration-200"
        >
          {dashboardCollapsed ? (
            <div className="flex h-full items-start justify-center pt-4">
              <Button variant="ghost" size="icon-sm" aria-label="Expand dashboard" onClick={() => setDashboardCollapsed(false)}>
                <ChevronLeft />
              </Button>
            </div>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
              <section className="border-b p-5">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <BarChart3 className="size-5 text-primary" />
                    <h2 className="text-lg font-semibold">Market charts</h2>
                  </div>
                  <Button variant="ghost" size="icon-sm" aria-label="Collapse dashboard" onClick={() => setDashboardCollapsed(true)}>
                    <ChevronRight />
                  </Button>
                </div>
                <div className="mt-4 grid grid-cols-3 gap-2">
                  <select
                    className="h-9 min-w-0 rounded-md border bg-background px-2 text-sm"
                    value={selectedCoin}
                    onChange={(event) => setSelectedCoin(event.target.value)}
                    aria-label="Select coin"
                  >
                    <option value="bitcoin">BTC</option>
                    <option value="ethereum">ETH</option>
                    <option value="solana">SOL</option>
                    <option value="usd-coin">USDC</option>
                  </select>
                  <select
                    className="h-9 min-w-0 rounded-md border bg-background px-2 text-sm"
                    value={selectedMetric}
                    onChange={(event) => setSelectedMetric(event.target.value as ChartMetric)}
                    aria-label="Select metric"
                  >
                    <option value="price_usd">Price</option>
                    <option value="daily_change_pct">Daily %</option>
                    <option value="market_cap_usd">Market cap</option>
                    <option value="volume_usd">Volume</option>
                  </select>
                  <select
                    className="h-9 min-w-0 rounded-md border bg-background px-2 text-sm"
                    value={selectedDays}
                    onChange={(event) => setSelectedDays(Number(event.target.value))}
                    aria-label="Select chart timeframe"
                  >
                    <option value={7}>7 days</option>
                    <option value={30}>30 days</option>
                    <option value={90}>90 days</option>
                    <option value={365}>1 year</option>
                  </select>
                </div>
                <div className="mt-5 flex h-52 items-center justify-center overflow-hidden rounded-lg border bg-muted/30">
                  {chartLoading && <p className="text-sm text-muted-foreground">Loading market data…</p>}
                  {chartError && <p className="px-4 text-center text-sm text-destructive">{chartError}</p>}
                  {marketChart && !chartLoading && !chartError && (
                    <Plot
                      data={marketChart.chart.data as never}
                      layout={{
                        ...marketChart.chart.layout,
                        autosize: true,
                        paper_bgcolor: "rgba(0,0,0,0)",
                        plot_bgcolor: "rgba(0,0,0,0)",
                        margin: { l: 45, r: 12, t: 40, b: 35 },
                        font: { size: 11 },
                      } as never}
                      config={{ displayModeBar: false, responsive: true }}
                      useResizeHandler
                      style={{ width: "100%", height: "100%" }}
                    />
                  )}
                </div>
                <Button
                  variant="outline"
                  className="mt-4 w-full"
                  disabled={!token || !conversationId}
                  onClick={openCustomChartModal}
                >
                  Make your own graph
                </Button>
              </section>

              <section className="border-b p-5">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <FileText className="size-5 text-primary" />
                    <h2 className="text-lg font-semibold">Documents</h2>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={uploading || !token}
                    onClick={() => fileInputRef.current?.click()}
                  >
                    {uploading ? "Uploading…" : "Upload"}
                  </Button>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  PDF, DOCX, Markdown, TXT, or CSV — indexed for the assistant to search in chat.
                </p>

                {uploadError && (
                  <p className="mt-2 text-xs text-destructive">{uploadError}</p>
                )}
                {uploadStatus && !uploadError && (
                  <p className="mt-2 text-xs text-emerald-600">{uploadStatus}</p>
                )}

                <div className="mt-3 max-h-40 space-y-2 overflow-y-auto">
                  {documentsLoading && (
                    <p className="text-sm text-muted-foreground">Loading documents…</p>
                  )}
                  {documentsError && (
                    <p className="text-sm text-destructive">{documentsError}</p>
                  )}
                  {!documentsLoading && !documentsError && documents.length === 0 && (
                    <div className="rounded-lg border border-dashed p-3 text-center text-xs text-muted-foreground">
                      No documents uploaded yet.
                    </div>
                  )}
                  {documents.map((doc) => (
                    <div
                      key={doc.id}
                      className="flex items-center gap-2 rounded-lg border px-3 py-2"
                    >
                      <FileText className="size-4 shrink-0 text-muted-foreground" />
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium">{doc.filename}</p>
                        <p className="truncate text-xs text-muted-foreground">
                          {new Date(doc.created_at).toLocaleDateString()}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              </section>

              <section className="min-h-0 flex-1 p-5">
                <h2 className="text-lg font-semibold">Portfolio</h2>
                {portfolioLoading && (
                  <p className="mt-4 text-sm text-muted-foreground">Loading portfolio…</p>
                )}
                {portfolioError && (
                  <p className="mt-4 text-sm text-destructive">{portfolioError}</p>
                )}
                {portfolio && "message" in portfolio && (
                  <div className="mt-6 rounded-lg border border-dashed p-4 text-center text-sm text-muted-foreground">
                    {portfolio.message}
                  </div>
                )}
                {portfolioTotal && !portfolioLoading && (
                  <>
                    {pricesUnavailable && (
                      <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
                        {portfolio?._meta?.message ?? "Live prices are temporarily unavailable."}
                      </div>
                    )}
                    {pricesUnavailable ? (
                      <div className="mt-3 flex items-end justify-between gap-2">
                        <p className="text-2xl font-semibold tracking-tight text-muted-foreground">
                          {currency.format(portfolioTotal.cost_basis)}
                        </p>
                        <span className="text-sm text-muted-foreground">cost basis</span>
                      </div>
                    ) : (
                      <>
                        <p className="text-xs font-medium tracking-wider text-muted-foreground">PORTFOLIO TOTAL</p>
                        <div className="mt-1 flex items-end justify-between gap-2">
                          <p className="text-2xl font-semibold tracking-tight">
                            {currency.format(portfolioTotal.current_value ?? 0)}
                          </p>
                          {portfolioTotal.today_move_percent !== null ? (
                            <span className={portfolioTotal.today_move_percent >= 0 ? "text-sm text-emerald-600" : "text-sm text-red-600"}>
                              {portfolioTotal.today_move_percent >= 0 ? "+" : ""}{portfolioTotal.today_move_percent.toFixed(1)}% today
                            </span>
                          ) : (
                            <span className="text-sm text-muted-foreground">today's move n/a</span>
                          )}
                        </div>
                        {portfolioTotal.today_move_usd !== null && (
                          <p className={portfolioTotal.today_move_usd >= 0 ? "mt-1 text-sm text-emerald-600" : "mt-1 text-sm text-red-600"}>
                            {portfolioTotal.today_move_usd >= 0 ? "+" : ""}{currency.format(portfolioTotal.today_move_usd)} today
                          </p>
                        )}
                        <p className={(portfolioTotal.profit_loss ?? 0) >= 0 ? "mt-1 text-xs text-emerald-600/80" : "mt-1 text-xs text-red-600/80"}>
                          {(portfolioTotal.profit_loss ?? 0) >= 0 ? "+" : ""}{currency.format(portfolioTotal.profit_loss ?? 0)} total P&amp;L ({portfolioChangePercent.toFixed(1)}%)
                        </p>
                        <p className="mt-4 text-[11px] leading-snug text-muted-foreground">
                          Not financial advice — figures are informational only, based on your logged purchases and current market prices.
                        </p>
                      </>
                    )}

                    <div className="mt-6 flex flex-wrap gap-2">
                      {PORTFOLIO_CHART_OPTIONS.map((option) => (
                        <Button
                          key={option.type}
                          size="sm"
                          variant={portfolioChartType === option.type ? "default" : "outline"}
                          onClick={() => setPortfolioChartType(option.type)}
                        >
                          {option.label}
                        </Button>
                      ))}
                    </div>
                    <div className="mt-3 flex h-44 items-center justify-center overflow-hidden rounded-lg border bg-muted/30">
                      {portfolioChartLoading && <p className="text-sm text-muted-foreground">Building chart…</p>}
                      {portfolioChartError && <p className="px-4 text-center text-sm text-destructive">{portfolioChartError}</p>}
                      {portfolioChart && !portfolioChartLoading && !portfolioChartError && (
                        <Plot
                          data={portfolioChart.chart.data as never}
                          layout={{
                            ...portfolioChart.chart.layout,
                            autosize: true,
                            paper_bgcolor: "rgba(0,0,0,0)",
                            plot_bgcolor: "rgba(0,0,0,0)",
                            margin: { l: 40, r: 12, t: 32, b: 32 },
                            font: { size: 11 },
                            showlegend: false,
                          } as never}
                          config={{ displayModeBar: false, responsive: true }}
                          useResizeHandler
                          style={{ width: "100%", height: "100%" }}
                        />
                      )}
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      className="mt-2 w-full"
                      disabled={!portfolioChart || portfolioChartLoading}
                      onClick={pinPortfolioChart}
                    >
                      Pin this chart
                    </Button>

                    {pinnedCharts.length > 0 && (
                      <div className="mt-6 space-y-4">
                        <p className="text-xs font-medium tracking-wider text-muted-foreground">PINNED CHARTS</p>
                        {pinnedCharts.map((pinned) => (
                          <div key={pinned.id} className="rounded-lg border p-2">
                            <div className="flex items-center justify-between gap-2">
                              <p className="truncate text-xs font-medium">{pinned.title}</p>
                              <Button variant="ghost" size="icon-sm" aria-label="Unpin chart" onClick={() => unpinChart(pinned.id)}>
                                <Trash2 className="size-3.5" />
                              </Button>
                            </div>
                            <div className="mt-1 h-36 overflow-hidden">
                              <Plot
                                data={pinned.chart.data as never}
                                layout={{
                                  ...pinned.chart.layout,
                                  autosize: true,
                                  paper_bgcolor: "rgba(0,0,0,0)",
                                  plot_bgcolor: "rgba(0,0,0,0)",
                                  margin: { l: 32, r: 8, t: 24, b: 24 },
                                  font: { size: 9 },
                                  showlegend: false,
                                } as never}
                                config={{ displayModeBar: false, responsive: true }}
                                useResizeHandler
                                style={{ width: "100%", height: "100%" }}
                              />
                            </div>
                          </div>
                        ))}
                      </div>
                    )}

                    <p className="mt-6 text-xs font-medium tracking-wider text-muted-foreground">HOLDINGS</p>
                    <div className="mt-3 space-y-4">
                      {portfolioHoldings.map((holding) => (
                        <div key={holding.coin} className="grid grid-cols-[auto_1fr_auto] items-center gap-3">
                          <div className="grid size-8 place-items-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                            {holding.coin.slice(0, 1).toUpperCase()}
                          </div>
                          <div className="min-w-0">
                            <p className="truncate text-sm font-medium">{holding.coin.toUpperCase()}</p>
                            <p className="truncate text-xs text-muted-foreground">{holding.amount.toLocaleString(undefined, { maximumFractionDigits: 6 })} {holding.coin.toUpperCase()}</p>
                          </div>
                          <div className="w-24 text-right">
                            <p className="text-sm font-medium">
                              {holding.current_value !== null ? currency.format(holding.current_value) : "—"}
                            </p>
                            <div className="mt-1 h-1 overflow-hidden rounded-full bg-muted">
                              <div
                                className="h-full rounded-full bg-primary"
                                style={{ width: `${Math.min(holding.portfolio_weight_percent ?? 0, 100)}%` }}
                              />
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </section>
            </div>
          )}
        </aside>
      </div>

      {customChartOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <Card className="flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden p-0">
            <div className="flex items-center justify-between border-b p-4">
              <h2 className="text-lg font-semibold">Make your own graph</h2>
              <Button variant="ghost" size="icon-sm" aria-label="Close" onClick={closeCustomChartModal}>
                ✕
              </Button>
            </div>

            <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
              <div>
                <p className="text-xs font-medium tracking-wider text-muted-foreground">DATAFRAME</p>
                {dataframeLoading && <p className="mt-2 text-sm text-muted-foreground">Loading your data…</p>}
                {dataframeError && <p className="mt-2 text-sm text-destructive">{dataframeError}</p>}
                {dataframeInfo && (
                  <>
                    <p className="mt-2 text-sm">
                      <span className="font-medium">df</span> — portfolio, {dataframeInfo.row_count} row
                      {dataframeInfo.row_count === 1 ? "" : "s"}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {dataframeInfo.columns.map((column) => (
                        <code key={column} className="rounded bg-muted px-1.5 py-0.5 text-xs">
                          {column}
                        </code>
                      ))}
                    </div>
                  </>
                )}
              </div>

              <div>
                <p className="text-xs font-medium tracking-wider text-muted-foreground">ASK AI</p>
                <div className="mt-2 flex gap-2">
                  <Input
                    value={customChartPrompt}
                    onChange={(event) => setCustomChartPrompt(event.target.value)}
                    placeholder="e.g. show my allocation as a donut chart"
                    disabled={customChartGenerating}
                  />
                  <Button
                    onClick={generateChartWithAI}
                    disabled={customChartGenerating || !customChartPrompt.trim() || !dataframeInfo}
                  >
                    {customChartGenerating ? "Generating…" : "Generate"}
                  </Button>
                </div>
              </div>

              {customChartGenerated && (
                <div>
                  <p className="text-xs font-medium tracking-wider text-muted-foreground">CODE</p>
                  <textarea
                    value={customChartCode}
                    onChange={(event) => setCustomChartCode(event.target.value)}
                    rows={6}
                    spellCheck={false}
                    className="mt-2 w-full rounded-lg border bg-background p-3 font-mono text-xs"
                    placeholder='fig = px.bar(df, x="coin", y="current_value")'
                  />
                  <p className="mt-1 text-[11px] text-muted-foreground">
                    Generated by AI — tweak it and hit Run to re-render. Only pandas (pd) and
                    plotly.express/graph_objects (px/go) are available — no imports, files, or
                    network calls. Assign your chart to a variable named <code>fig</code>.
                  </p>
                </div>
              )}

              <div className="flex gap-2">
                <Button
                  onClick={() => runCustomChart(customChartCode)}
                  disabled={
                    !customChartGenerated || customChartRunning || !customChartCode.trim() || !dataframeInfo
                  }
                >
                  {customChartRunning ? "Running…" : "Run"}
                </Button>
                <Button variant="outline" onClick={pinCustomChart} disabled={!customChartResult}>
                  Pin to dashboard
                </Button>
              </div>

              {customChartError && <p className="text-sm text-destructive">{customChartError}</p>}

              <div className="flex h-64 items-center justify-center overflow-hidden rounded-lg border bg-muted/30">
                {!customChartResult && !customChartError && (
                  <p className="text-sm text-muted-foreground">
                    Describe a chart above and hit Generate to see it here.
                  </p>
                )}
                {customChartResult && (
                  <Plot
                    data={customChartResult.chart.data as never}
                    layout={{
                      ...customChartResult.chart.layout,
                      autosize: true,
                      paper_bgcolor: "rgba(0,0,0,0)",
                      plot_bgcolor: "rgba(0,0,0,0)",
                      margin: { l: 45, r: 20, t: 40, b: 40 },
                      font: { size: 11 },
                    } as never}
                    config={{ displayModeBar: false, responsive: true }}
                    useResizeHandler
                    style={{ width: "100%", height: "100%" }}
                  />
                )}
              </div>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}