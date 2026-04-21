const LINE_REPLY_ENDPOINT = "https://api.line.me/v2/bot/message/reply";

type PartRecord = Record<string, unknown>;
type SystemStatus = Record<string, unknown>;

function env(name: string): string {
  return Deno.env.get(name) ?? "";
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

function normalizeText(value: unknown): string {
  return String(value ?? "").trim();
}

function upper(value: unknown): string {
  return normalizeText(value).toUpperCase();
}

function bangkokToday(): string {
  const now = new Date();
  const bangkok = new Date(now.getTime() + 7 * 60 * 60 * 1000);
  return bangkok.toISOString().slice(0, 10);
}

function isTimestampFresh(timestampValue: unknown, staleSeconds = 180): boolean {
  const raw = normalizeText(timestampValue);
  if (!raw) return false;
  const normalized = raw.includes("T") ? raw : raw.replace(" ", "T");
  const hasTimezone = /(?:z|[+-]\d{2}:?\d{2})$/i.test(normalized);
  const parsed = new Date(hasTimezone ? normalized : `${normalized}+07:00`);
  if (Number.isNaN(parsed.getTime())) return false;
  return Math.abs(Date.now() - parsed.getTime()) <= staleSeconds * 1000;
}

async function verifyLineSignature(req: Request, rawBody: string): Promise<boolean> {
  const secret = env("LINE_CHANNEL_SECRET");
  if (!secret) return true;
  const signature = req.headers.get("x-line-signature") ?? "";
  if (!signature) return false;

  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const digest = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(rawBody));
  const expected = btoa(String.fromCharCode(...new Uint8Array(digest)));
  return signature === expected;
}

async function supabaseGet(pathAndQuery: string): Promise<unknown[]> {
  const baseUrl = (env("PROJECT_SUPABASE_URL") || env("SUPABASE_URL")).replace(/\/+$/, "");
  const key = env("PROJECT_SUPABASE_SERVICE_ROLE_KEY") || env("PROJECT_SUPABASE_ANON_KEY") || env("SUPABASE_SERVICE_ROLE_KEY") || env("SUPABASE_ANON_KEY");
  if (!baseUrl || !key) throw new Error("Supabase env is not configured.");

  const resp = await fetch(`${baseUrl}/rest/v1/${pathAndQuery}`, {
    headers: {
      apikey: key,
      authorization: `Bearer ${key}`,
    },
  });
  if (!resp.ok) throw new Error(`Supabase request failed: ${resp.status}`);
  const data = await resp.json();
  return Array.isArray(data) ? data : [];
}

function supabaseHeaders(extra: Record<string, string> = {}): HeadersInit {
  const key = env("PROJECT_SUPABASE_SERVICE_ROLE_KEY") || env("PROJECT_SUPABASE_ANON_KEY") || env("SUPABASE_SERVICE_ROLE_KEY") || env("SUPABASE_ANON_KEY");
  return {
    apikey: key,
    authorization: `Bearer ${key}`,
    ...extra,
  };
}

async function supabaseWrite(pathAndQuery: string, method: string, body?: unknown): Promise<Response> {
  const baseUrl = (env("PROJECT_SUPABASE_URL") || env("SUPABASE_URL")).replace(/\/+$/, "");
  if (!baseUrl) throw new Error("Supabase env is not configured.");
  const resp = await fetch(`${baseUrl}/rest/v1/${pathAndQuery}`, {
    method,
    headers: supabaseHeaders({
      "content-type": "application/json",
      prefer: "resolution=merge-duplicates",
    }),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`Supabase write failed: ${resp.status}`);
  return resp;
}

async function upsertSubscriber(userId: string, sourceType: string): Promise<void> {
  if (!userId) throw new Error("Missing LINE user id.");
  await supabaseWrite("line_subscribers?on_conflict=user_id", "POST", [{
    user_id: userId,
    source_type: sourceType || "user",
    subscribed: true,
    updated_at: new Date().toISOString(),
  }]);
}

async function unsubscribeSubscriber(userId: string): Promise<void> {
  if (!userId) throw new Error("Missing LINE user id.");
  await supabaseWrite(
    `line_subscribers?user_id=eq.${encodeURIComponent(userId)}`,
    "PATCH",
    { subscribed: false, updated_at: new Date().toISOString() },
  );
}

async function fetchSubscribers(): Promise<unknown[]> {
  return await supabaseGet(
    "line_subscribers?select=user_id,source_type,subscribed,updated_at&subscribed=eq.true&order=updated_at.desc",
  );
}

async function fetchLatestSystemStatus(): Promise<SystemStatus | null> {
  const select = encodeURIComponent("timestamp,printer_status,robot_status");
  const rows = await supabaseGet(
    `system_status?select=${select}&order=timestamp.desc&limit=1`,
  );
  return rows[0] as SystemStatus | undefined ?? null;
}

const partSelect = encodeURIComponent(
  "part_id,result,side1,side2,side3,record_timestamp,defect _s1,defect _s2,defect _s3,dimension of top,dimension of bottom,dimension of length,capture_s1,capture_s2,capture_s3",
);

async function fetchLatestPart(): Promise<PartRecord | null> {
  const rows = await supabaseGet(
    `part_records?select=${partSelect}&order=part_id.desc&limit=1`,
  );
  return rows[0] as PartRecord | undefined ?? null;
}

async function fetchPartById(partId: number): Promise<PartRecord | null> {
  const rows = await supabaseGet(
    `part_records?select=${partSelect}&part_id=eq.${partId}&limit=1`,
  );
  return rows[0] as PartRecord | undefined ?? null;
}

async function fetchTodayParts(): Promise<PartRecord[]> {
  const date = bangkokToday();
  const start = encodeURIComponent(`gte.${date} 00:00:00`);
  return await supabaseGet(
    `part_records?select=${partSelect}&record_timestamp=${start}&order=part_id.asc`,
  ) as PartRecord[];
}

async function fetchAllParts(): Promise<PartRecord[]> {
  return await supabaseGet(
    `part_records?select=${partSelect}&order=part_id.asc`,
  ) as PartRecord[];
}

async function replyLine(replyToken: string, messages: unknown[]): Promise<void> {
  const accessToken = env("LINE_CHANNEL_ACCESS_TOKEN");
  if (!accessToken) throw new Error("LINE_CHANNEL_ACCESS_TOKEN is not configured.");
  await fetch(LINE_REPLY_ENDPOINT, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({ replyToken, messages, notificationDisabled: false }),
  });
}

function flexReply(altText: string, contents: unknown): unknown[] {
  return [{ type: "flex", altText, contents }];
}

function textReply(text: string): unknown[] {
  return [{ type: "text", text }];
}

function statusFlex(snapshot: Record<string, string>): unknown {
  const overallOnline = snapshot.overall_status === "ONLINE";
  const accentColor = overallOnline ? "#10B981" : "#F59E0B";
  const overallSize = snapshot.overall_status.length <= 10 ? "xxl" : "xl";
  const row = (label: string, value: string) => ({
    type: "box",
    layout: "horizontal",
    spacing: "md",
    contents: [
      { type: "text", text: label, size: "sm", color: "#94A3B8", flex: 5 },
      {
        type: "text",
        text: value,
        size: "sm",
        weight: "bold",
        align: "end",
        color: value === "ONLINE" ? "#10B981" : "#EF4444",
        flex: 4,
      },
    ],
  });

  return {
    type: "bubble",
    size: "mega",
    header: {
      type: "box",
      layout: "vertical",
      backgroundColor: "#0F172A",
      paddingAll: "20px",
      contents: [
        { type: "text", text: "APE65 A1 STATUS", size: "xs", color: "#CBD5E1", weight: "bold" },
        { type: "text", text: snapshot.overall_status, margin: "md", size: overallSize, weight: "bold", color: accentColor, wrap: true },
        { type: "text", text: "Current system health", margin: "sm", size: "sm", color: "#94A3B8", wrap: true },
      ],
    },
    body: {
      type: "box",
      layout: "vertical",
      spacing: "md",
      paddingAll: "20px",
      contents: [
        row("Raspberry Pi", snapshot.pi_status),
        row("Bambu Lab A1", snapshot.bambu_status),
        row("TM Cobot", snapshot.cobot_status),
        row("Database", snapshot.database_status),
      ],
    },
  };
}

async function buildStatus(): Promise<unknown[]> {
  let latest: SystemStatus | null = null;
  let databaseStatus = "ONLINE";
  try {
    latest = await fetchLatestSystemStatus();
  } catch {
    databaseStatus = "OFFLINE";
  }

  const piStatus = latest && isTimestampFresh(latest.timestamp) ? "ONLINE" : "OFFLINE";
  const printer = upper(latest?.printer_status);
  const robot = upper(latest?.robot_status);
  const bambuOffline = ["", "DISCONNECTED", "UNKNOWN", "STALE", "CONNECTING", "CONFIG MISSING"].includes(printer) ||
    printer.startsWith("CONN ERROR") ||
    printer.startsWith("ERROR");
  const snapshot = {
    pi_status: piStatus,
    bambu_status: bambuOffline ? "OFFLINE" : "ONLINE",
    cobot_status: robot === "CONNECTED" ? "ONLINE" : "OFFLINE",
    database_status: databaseStatus,
    overall_status: "SYSTEM NOT READY",
  };
  snapshot.overall_status = Object.entries(snapshot)
    .filter(([key]) => key.endsWith("_status") && key !== "overall_status")
    .every(([, value]) => value === "ONLINE") ? "ONLINE" : "SYSTEM NOT READY";

  return flexReply("APE65 A1 STATUS", statusFlex(snapshot));
}

function summaryFlex(rows: PartRecord[], title = "APE65 A1 SUMMARY", subtitle = "Current production summary"): unknown {
  const total = rows.length;
  const good = rows.filter((row) => upper(row.result) === "GOOD").length;
  const ng = rows.filter((row) => upper(row.result) === "NG").length;
  const yieldPct = total > 0 ? (good / total) * 100 : 0;
  const accentColor = total > 0 && ng === 0 ? "#10B981" : total > 0 ? "#F59E0B" : "#64748B";
  const partIds = rows
    .map((row) => Number(row.part_id))
    .filter((partId) => Number.isFinite(partId) && partId > 0);
  const firstPartId = partIds.length ? Math.min(...partIds) : 0;
  const latestPartId = partIds.length ? Math.max(...partIds) : 0;
  const partRange = firstPartId > 0 && latestPartId > 0 ? `PART ${firstPartId} - PART ${latestPartId}` : "-";
  const latestRecord = rows
    .slice()
    .sort((a, b) => Number(b.part_id ?? 0) - Number(a.part_id ?? 0))[0];
  const latestRaw = normalizeText(latestRecord?.record_timestamp).replace("T", " ");
  const latestParts = latestRaw.split(/\s+/);
  const latestDate = latestParts[0] || "-";
  const latestTime = latestParts[1] || "-";
  const metricBox = (label: string, value: string, color: string) => ({
    type: "box",
    layout: "vertical",
    spacing: "xs",
    paddingAll: "12px",
    backgroundColor: "#111827",
    cornerRadius: "12px",
    contents: [
      { type: "text", text: label, size: "xs", color: "#94A3B8", weight: "bold" },
      { type: "text", text: value, size: "xl", weight: "bold", color },
    ],
  });
  const summaryRow = (label: string, value: string, color = "#111827", wrap = true, size = "sm") => ({
    type: "box",
    layout: "horizontal",
    spacing: "md",
    contents: [
      { type: "text", text: label, size: "sm", color: "#475569", flex: 5 },
      { type: "text", text: value, size, weight: "bold", align: "end", color, flex: 5, wrap },
    ],
  });

  return {
    type: "bubble",
    size: "mega",
    header: {
      type: "box",
      layout: "vertical",
      backgroundColor: "#0F172A",
      paddingAll: "20px",
      contents: [
        { type: "text", text: title, size: "xs", color: "#CBD5E1", weight: "bold" },
        { type: "text", text: `${yieldPct.toFixed(2)}%`, margin: "md", size: "xxl", weight: "bold", color: accentColor },
        { type: "text", text: subtitle, margin: "sm", size: "sm", color: "#94A3B8", wrap: true },
      ],
    },
    body: {
      type: "box",
      layout: "vertical",
      spacing: "md",
      paddingAll: "20px",
      contents: [
        {
          type: "box",
          layout: "horizontal",
          spacing: "md",
          contents: [
            metricBox("Total", String(total), "#E2E8F0"),
            metricBox("GOOD", String(good), "#10B981"),
            metricBox("NG", String(ng), "#EF4444"),
          ],
        },
        { type: "separator", margin: "md" },
        summaryRow("Latest Date", latestDate),
        summaryRow("Latest Time", latestTime),
        summaryRow("Part Range", partRange, "#111827", false, "xs"),
      ],
    },
  };
}

async function buildSummary(): Promise<unknown[]> {
  const rows = await fetchAllParts();
  return flexReply("APE65 A1 SUMMARY", summaryFlex(rows, "APE65 A1 SUMMARY", "Overall production summary"));
}

function partFlex(record: PartRecord, title = "APE65 A1 NOW", subtitle = "Latest inspection record"): unknown {
  const result = upper(record.result) || "-";
  const resultColor = result === "GOOD" ? "#10B981" : result === "NG" ? "#EF4444" : "#E2E8F0";
  const headerBg = result === "GOOD" ? "#14532D" : result === "NG" ? "#7F1D1D" : "#0F172A";
  const headerSub = result === "GOOD" ? "#BBF7D0" : result === "NG" ? "#FECACA" : "#CBD5E1";
  const headerHint = result === "GOOD" ? "#86EFAC" : result === "NG" ? "#FCA5A5" : "#94A3B8";
  const rawTime = normalizeText(record.record_timestamp).replace("T", " ");
  const timeParts = rawTime.split(/\s+/);
  const recordedDate = timeParts[0] || "-";
  const recordedTime = timeParts[1] || "-";
  const row = (label: string, value: unknown, color = "#0F172A") => ({
    type: "box",
    layout: "horizontal",
    spacing: "md",
    contents: [
      { type: "text", text: label, size: "sm", color: "#475569", flex: 4 },
      { type: "text", text: normalizeText(value) || "-", size: "sm", weight: "bold", align: "end", color, flex: 5, wrap: true },
    ],
  });
  const body: unknown[] = [
    row("Part ID", record.part_id),
    row("Result", result, resultColor),
    row("Side 1", record.side1, upper(record.side1).startsWith("NG") ? "#EF4444" : "#0F172A"),
    row("Side 2", record.side2, upper(record.side2).startsWith("NG") ? "#EF4444" : "#0F172A"),
    row("Side 3", record.side3, upper(record.side3).startsWith("NG") ? "#EF4444" : "#0F172A"),
  ];

  const defects = [
    ["Defect S1", record["defect _s1"]],
    ["Defect S2", record["defect _s2"]],
    ["Defect S3", record["defect _s3"]],
  ];
  if (defects.some(([, value]) => !["", "-"].includes(normalizeText(value)))) {
    body.push({ type: "separator", margin: "md" });
    for (const [label, value] of defects) {
      const text = normalizeText(value) || "-";
      body.push(row(label as string, text, !["", "-"].includes(text) ? "#EF4444" : "#0F172A"));
    }
  }

  const dims = [
    ["TOP", record["dimension of top"], 19.5],
    ["BOTTOM", record["dimension of bottom"], 24.5],
    ["LENGTH", record["dimension of length"], 90.0],
  ];
  if (dims.some(([, value]) => value !== null && value !== undefined)) {
    body.push({ type: "separator", margin: "md" });
    for (const [label, value, target] of dims) {
      const numeric = Number(value);
      const color = Number.isFinite(numeric) && Math.abs(numeric - Number(target)) > 0.3 ? "#EF4444" : "#0F172A";
      body.push(row(label as string, Number.isFinite(numeric) ? `${numeric.toFixed(2)} mm` : "-", color));
    }
  }

  body.push({ type: "separator", margin: "md" });
  body.push(row("Recorded Date", recordedDate));
  body.push(row("Recorded Time", recordedTime));

  const footer: unknown[] = [];
  for (const [label, key] of [["Side 1", "capture_s1"], ["Side 2", "capture_s2"], ["Side 3", "capture_s3"]]) {
    const url = normalizeText(record[key]);
    if (!url.startsWith("http://") && !url.startsWith("https://")) continue;
    footer.push({
      type: "button",
      style: "secondary",
      height: "sm",
      color: "#E2E8F0",
      flex: 1,
      action: { type: "uri", label, uri: url },
    });
  }

  const bubble: Record<string, unknown> = {
    type: "bubble",
    size: "mega",
    header: {
      type: "box",
      layout: "vertical",
      backgroundColor: headerBg,
      paddingAll: "20px",
      contents: [
        { type: "text", text: title, size: "xs", color: headerSub, weight: "bold" },
        { type: "text", text: `PART ${record.part_id ?? "-"}`, margin: "md", size: "xxl", weight: "bold", color: "#FFFFFF" },
        { type: "text", text: subtitle, margin: "sm", size: "sm", color: headerHint, wrap: true },
      ],
    },
    body: { type: "box", layout: "vertical", spacing: "md", paddingAll: "20px", contents: body },
  };
  if (footer.length) {
    bubble.footer = {
      type: "box",
      layout: "horizontal",
      spacing: "xs",
      paddingTop: "8px",
      paddingBottom: "16px",
      paddingStart: "20px",
      paddingEnd: "20px",
      contents: footer,
    };
  }
  return bubble;
}

function partNotFoundFlex(partId: number): unknown {
  return {
    type: "bubble",
    size: "mega",
    header: {
      type: "box",
      layout: "vertical",
      backgroundColor: "#334155",
      paddingAll: "20px",
      contents: [
        { type: "text", text: "APE65 A1 PART SEARCH", size: "xs", color: "#CBD5E1", weight: "bold" },
        { type: "text", text: `PART ${partId}`, margin: "md", size: "xxl", weight: "bold", color: "#FFFFFF" },
        { type: "text", text: "Inspection record not found", margin: "sm", size: "sm", color: "#CBD5E1", wrap: true },
      ],
    },
    body: {
      type: "box",
      layout: "vertical",
      paddingAll: "20px",
      contents: [
        {
          type: "box",
          layout: "vertical",
          paddingAll: "14px",
          backgroundColor: "#F8FAFC",
          cornerRadius: "12px",
          contents: [
            { type: "text", text: "No data available", size: "lg", weight: "bold", color: "#0F172A" },
            { type: "text", text: "Please check the Part ID and try again.", margin: "sm", size: "sm", color: "#64748B", wrap: true },
          ],
        },
      ],
    },
  };
}

function recentNotFoundFlex(): unknown {
  return {
    type: "bubble",
    size: "mega",
    header: {
      type: "box",
      layout: "vertical",
      backgroundColor: "#334155",
      paddingAll: "20px",
      contents: [
        { type: "text", text: "APE65 A1 RECENT", size: "xs", color: "#CBD5E1", weight: "bold" },
        { type: "text", text: "NO RECORD", margin: "md", size: "xxl", weight: "bold", color: "#FFFFFF" },
        { type: "text", text: "No inspection record found", margin: "sm", size: "sm", color: "#CBD5E1", wrap: true },
      ],
    },
    body: {
      type: "box",
      layout: "vertical",
      paddingAll: "20px",
      contents: [
        {
          type: "box",
          layout: "vertical",
          paddingAll: "14px",
          backgroundColor: "#F8FAFC",
          cornerRadius: "12px",
          contents: [
            { type: "text", text: "No data available", size: "lg", weight: "bold", color: "#0F172A" },
            { type: "text", text: "The system has not recorded any inspection part yet.", margin: "sm", size: "sm", color: "#64748B", wrap: true },
          ],
        },
      ],
    },
  };
}

function informationFlex(): unknown {
  const infoRow = (label: string, value: string, color = "#0F172A", wrap = true) => ({
    type: "box",
    layout: "vertical",
    spacing: "xs",
    contents: [
      { type: "text", text: label, size: "xs", color: "#64748B", weight: "bold" },
      { type: "text", text: value, size: "sm", color, weight: "bold", wrap },
    ],
  });
  const creatorRow = (text: string) => ({
    type: "text",
    text,
    size: "xxs",
    color: "#0F172A",
    weight: "bold",
    wrap: false,
    flex: 0,
  });

  return {
    type: "bubble",
    size: "mega",
    header: {
      type: "box",
      layout: "vertical",
      backgroundColor: "#0F172A",
      paddingAll: "20px",
      contents: [
        { type: "text", text: "APE65 A1 INFORMATION", size: "xs", color: "#CBD5E1", weight: "bold" },
        { type: "text", text: "PROJECT_APE01", margin: "md", size: "xxl", weight: "bold", color: "#FFFFFF" },
        { type: "text", text: "System information", margin: "sm", size: "sm", color: "#94A3B8", wrap: true },
      ],
    },
    body: {
      type: "box",
      layout: "vertical",
      spacing: "md",
      paddingAll: "20px",
      contents: [
        infoRow(
          "PROJECT NAME",
          "DEVELOPMENT OF AN AUTOMATED QUALITY INSPECTION SYSTEM FOR 3D PRINTING PROCESSES",
          "#0369A1",
        ),
        { type: "separator", margin: "md" },
        {
          type: "box",
          layout: "vertical",
          spacing: "xs",
          contents: [
            { type: "text", text: "CREATORS", size: "xs", color: "#64748B", weight: "bold" },
            creatorRow("1. 65070507601 KHWANKHAO KEAWDIAU"),
            creatorRow("2. 65070507626 JIRASAK SOMJIT"),
            creatorRow("3. 65070507647 TANANART WANGMOON"),
          ],
        },
        { type: "separator", margin: "md" },
        infoRow("ADVISOR", "ASST.PROF. NOPPADOL KUMANUVONG", "#B45309"),
        {
          type: "box",
          layout: "horizontal",
          spacing: "md",
          contents: [
            { type: "text", text: "Build", size: "sm", color: "#64748B", flex: 3 },
            { type: "text", text: "2026.06.02", size: "sm", color: "#0F172A", weight: "bold", align: "end", flex: 4 },
          ],
        },
      ],
    },
  };
}

function subscriptionFlex(title: string, message: string, active = true): unknown {
  const headerBg = active ? "#14532D" : "#7F1D1D";
  const eyebrow = active ? "#BBF7D0" : "#FECACA";
  const hint = active ? "#86EFAC" : "#FCA5A5";
  return {
    type: "bubble",
    size: "mega",
    header: {
      type: "box",
      layout: "vertical",
      backgroundColor: headerBg,
      paddingAll: "20px",
      contents: [
        { type: "text", text: "APE65 A1 ALERT SUBSCRIPTION", size: "xs", color: eyebrow, weight: "bold" },
        { type: "text", text: title, margin: "md", size: "xxl", weight: "bold", color: "#FFFFFF" },
        { type: "text", text: message, margin: "sm", size: "sm", color: hint, wrap: true },
      ],
    },
  };
}

async function buildSubscribers(): Promise<unknown[]> {
  const rows = await fetchSubscribers();
  return flexReply("APE65 A1 SUBSCRIBERS", {
    type: "bubble",
    size: "mega",
    header: {
      type: "box",
      layout: "vertical",
      backgroundColor: "#0F172A",
      paddingAll: "20px",
      contents: [
        { type: "text", text: "APE65 A1 SUBSCRIBERS", size: "xs", color: "#CBD5E1", weight: "bold" },
        { type: "text", text: String(rows.length), margin: "md", size: "xxl", weight: "bold", color: "#38BDF8" },
        { type: "text", text: "Active alert recipients", margin: "sm", size: "sm", color: "#94A3B8", wrap: true },
      ],
    },
  });
}

async function buildRecent(): Promise<unknown[]> {
  const record = await fetchLatestPart();
  if (!record) return flexReply("APE65 A1 RECENT no record", recentNotFoundFlex());
  return flexReply("APE65 A1 RECENT", partFlex(record, "APE65 A1 RECENT", "Latest inspection record"));
}

async function buildPart(partId: number): Promise<unknown[]> {
  const record = await fetchPartById(partId);
  if (!record) return flexReply(`APE65 A1 PART ${partId} not found`, partNotFoundFlex(partId));
  return flexReply(`APE65 A1 PART ${partId}`, partFlex(record, "APE65 A1 PART", `Inspection record for PART ${partId}`));
}

Deno.serve(async (req) => {
  if (req.method === "GET" || req.method === "HEAD" || req.method === "OPTIONS") {
    return jsonResponse({ success: true, message: "LINE bot ready" });
  }
  if (req.method !== "POST") return jsonResponse({ success: false, message: "Method not allowed" }, 405);

  const rawBody = await req.text();
  if (!(await verifyLineSignature(req, rawBody))) {
    return jsonResponse({ success: false, message: "Invalid signature" }, 403);
  }

  const payload = JSON.parse(rawBody || "{}");
  const events = Array.isArray(payload.events) ? payload.events : [];
  for (const event of events) {
    const replyToken = normalizeText(event?.replyToken);
    const text = normalizeText(event?.message?.text).toLowerCase();
    const source = event?.source ?? {};
    const sourceUserId = normalizeText(source?.userId);
    const sourceType = normalizeText(source?.type);
    if (!replyToken || event?.type !== "message" || event?.message?.type !== "text") continue;

    try {
      if (text === "status") {
        await replyLine(replyToken, await buildStatus());
      } else if (text === "summary") {
        await replyLine(replyToken, await buildSummary());
      } else if (text === "recent") {
        await replyLine(replyToken, await buildRecent());
      } else if (text === "information" || text === "info") {
        await replyLine(replyToken, flexReply("APE65 A1 INFORMATION", informationFlex()));
      } else if (text === "subscribe") {
        await upsertSubscriber(sourceUserId, sourceType);
        await replyLine(
          replyToken,
          flexReply(
            "APE65 A1 SUBSCRIBED",
            subscriptionFlex("SUBSCRIBED", "You will receive NG Alert and System Alert from APE65 A1.", true),
          ),
        );
      } else if (text === "unsubscribe") {
        await unsubscribeSubscriber(sourceUserId);
        await replyLine(
          replyToken,
          flexReply(
            "APE65 A1 UNSUBSCRIBED",
            subscriptionFlex("UNSUBSCRIBED", "You will no longer receive automatic alerts.", false),
          ),
        );
      } else if (text === "subscribers") {
        await replyLine(replyToken, await buildSubscribers());
      } else if (text.startsWith("part ")) {
        const partId = Number(text.slice(5).trim());
        if (Number.isInteger(partId) && partId > 0) {
          await replyLine(replyToken, await buildPart(partId));
        }
      }
    } catch (err) {
      console.error("LINE command failed", err);
      await replyLine(replyToken, textReply("APE65 A1\nCommand failed. Please try again."));
    }
  }

  return jsonResponse({ success: true });
});
