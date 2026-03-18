import { Resvg, initWasm } from "@resvg/resvg-wasm";
import wasmModule from "@resvg/resvg-wasm/index_bg.wasm";

let wasmReady = false;

const APP_URL = "https://daichikayahara33.github.io/paper-copilot/";
const S2_API = "https://api.semanticscholar.org/graph/v1";

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    _s2Key = env.S2_API_KEY || "";

    if (!wasmReady) {
      await initWasm(wasmModule);
      wasmReady = true;
    }

    if (url.pathname === "/" && request.method === "GET") {
      return new Response("Paper Copilot Slack Bot is running.");
    }

    // Slack slash command
    if (url.pathname === "/slack" && request.method === "POST") {
      const formData = await request.formData();
      const text = formData.get("text") || "";
      const responseUrl = formData.get("response_url");

      if (!text.trim()) {
        return jsonResponse({ text: "Usage: /papers <keyword>\nExample: /papers VLA" });
      }

      const { mode, keyword } = parseInput(text.trim());
      ctx.waitUntil(handleQuery(env, keyword, null, responseUrl, mode));

      return jsonResponse({
        response_type: "in_channel",
        text: `🔍 Searching papers for "${keyword}"...`,
      });
    }

    // Slack Events API
    if (url.pathname === "/events" && request.method === "POST") {
      const body = await request.json();

      if (body.type === "url_verification") {
        return jsonResponse({ challenge: body.challenge });
      }

      if (body.type === "event_callback" && body.event?.type === "app_mention") {
        const keyword = body.event.text.replace(/<@[A-Z0-9]+>/g, "").trim();
        const channel = body.event.channel;
        const botToken = env.SLACK_BOT_TOKEN;

        if (keyword && botToken) {
          const parsed = parseInput(keyword);
          ctx.waitUntil(handleQuery(env, parsed.keyword, channel, null, parsed.mode));
        }
        return new Response("ok");
      }

      return new Response("ok");
    }

    // Direct graph image endpoint
    if (url.pathname === "/graph.png") {
      const query = url.searchParams.get("q");
      if (!query) return new Response("Missing ?q=", { status: 400 });
      const papers = await searchPapersWithRefs(query);
      const png = generateGraphPNG(papers, query);
      return new Response(png, { headers: { "Content-Type": "image/png" } });
    }

    return new Response("Not found", { status: 404 });
  },
};

// Parse "list VLA" → { mode: "list", keyword: "VLA" }
// Parse "VLA" → { mode: "graph", keyword: "VLA" }
function parseInput(text) {
  if (text.startsWith("list ")) {
    return { mode: "list", keyword: text.slice(5).trim() };
  }
  return { mode: "graph", keyword: text };
}

async function handleQuery(env, query, channel, responseUrl, mode = "graph") {
  const botToken = env.SLACK_BOT_TOKEN;
  const pageUrl = `${APP_URL}?q=${encodeURIComponent(query)}&fresh=1`;

  try {
    const papers = await searchPapersWithRefs(query);

    if (!papers.length) {
      const msg = `No papers found for "${query}".`;
      if (channel && botToken) await postSlackChat(botToken, channel, msg);
      else if (responseUrl) await sendSlackMessage(responseUrl, { response_type: "in_channel", text: msg });
      return;
    }

    if (mode === "list") {
      // Text list mode
      await sendListResult(papers, query, pageUrl, channel, responseUrl, botToken);
    } else {
      // Graph image mode
      await sendGraphResult(env, papers, query, pageUrl, channel, responseUrl, botToken);
    }

  } catch (e) {
    const errMsg = `❌ Error: ${e.message}`;
    if (channel && botToken) await postSlackChat(botToken, channel, errMsg);
    else if (responseUrl) await sendSlackMessage(responseUrl, { response_type: "in_channel", text: errMsg });
  }
}

async function sendGraphResult(env, papers, query, pageUrl, channel, responseUrl, botToken) {
  const pngBuffer = generateGraphPNG(papers, query);

  if (channel && botToken) {
    await uploadSlackImage(botToken, channel, pngBuffer, query, pageUrl);
  } else if (responseUrl) {
    await sendSlackMessage(responseUrl, {
      response_type: "in_channel",
      text: `📊 Paper Citation Graph: "${query}"`,
      blocks: [
        {
          type: "section",
          text: { type: "mrkdwn", text: `📊 *Paper Citation Graph: "${query}"*\n<${pageUrl}|🔗 Open interactive graph>` },
        },
        {
          type: "image",
          image_url: `https://paper-copilot-slack.d-kayahara33.workers.dev/graph.png?q=${encodeURIComponent(query)}`,
          alt_text: `Paper graph for ${query}`,
        },
      ],
    });
  }
}

async function sendListResult(papers, query, pageUrl, channel, responseUrl, botToken) {
  const blocks = [
    {
      type: "section",
      text: { type: "mrkdwn", text: `📊 *Paper Citation Graph: "${query}"*` },
    },
    {
      type: "actions",
      elements: [
        {
          type: "button",
          text: { type: "plain_text", text: "🔗 Open Interactive Graph" },
          url: pageUrl,
          action_id: "open_graph",
        },
      ],
    },
    { type: "divider" },
  ];

  for (let i = 0; i < Math.min(10, papers.length); i++) {
    const p = papers[i];
    const authors = p.authors.slice(0, 3).join(", ");
    const arxivLink = p.arxivId ? ` | <https://arxiv.org/abs/${p.arxivId}|arXiv>` : "";
    blocks.push({
      type: "section",
      text: {
        type: "mrkdwn",
        text: `*${i + 1}. ${p.title}*\n${authors} (${p.year}) · Cited: ${p.cited}${arxivLink}`,
      },
    });
  }

  if (papers.length > 10) {
    blocks.push({
      type: "context",
      elements: [{ type: "mrkdwn", text: `+${papers.length - 10} more papers. <${pageUrl}|View all in graph>` }],
    });
  }

  const text = `📊 *Paper Citation Graph: "${query}"*\n<${pageUrl}|🔗 Open interactive graph>`;

  if (channel && botToken) {
    await fetch("https://slack.com/api/chat.postMessage", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": `Bearer ${botToken}` },
      body: JSON.stringify({ channel, text, blocks }),
    });
  } else if (responseUrl) {
    await sendSlackMessage(responseUrl, { response_type: "in_channel", text, blocks });
  }
}

// ── Graph Generation ──

function generateGraphPNG(papers, query) {
  const W = 1200, H = 800;

  // Run force simulation
  const nodes = papers.map((p, i) => ({
    x: W / 2 + (Math.random() - 0.5) * 400,
    y: H / 2 + (Math.random() - 0.5) * 300,
    vx: 0, vy: 0,
    paper: p,
    r: 6 + Math.min(20, Math.sqrt(p.cited) * 0.5),
  }));

  // Build edges (citation links within our set)
  const idToIdx = {};
  nodes.forEach((n, i) => { idToIdx[n.paper.id] = i; });
  const edges = [];
  for (const n of nodes) {
    for (const refId of (n.paper.references || [])) {
      if (idToIdx[refId] !== undefined) {
        edges.push([nodes.indexOf(n), idToIdx[refId]]);
      }
    }
  }

  // Force simulation (200 iterations)
  for (let iter = 0; iter < 200; iter++) {
    const alpha = 0.3 * (1 - iter / 200);

    // Repulsion
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        let dx = nodes[j].x - nodes[i].x;
        let dy = nodes[j].y - nodes[i].y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 1) d2 = 1;
        let f = 2000 / d2;
        let fx = dx / Math.sqrt(d2) * f;
        let fy = dy / Math.sqrt(d2) * f;
        nodes[i].vx -= fx * alpha;
        nodes[i].vy -= fy * alpha;
        nodes[j].vx += fx * alpha;
        nodes[j].vy += fy * alpha;
      }
    }

    // Edge attraction
    for (const [si, ti] of edges) {
      let dx = nodes[ti].x - nodes[si].x;
      let dy = nodes[ti].y - nodes[si].y;
      let d = Math.sqrt(dx * dx + dy * dy) || 1;
      let f = (d - 100) * 0.01 * alpha;
      let fx = dx / d * f, fy = dy / d * f;
      nodes[si].vx += fx; nodes[si].vy += fy;
      nodes[ti].vx -= fx; nodes[ti].vy -= fy;
    }

    // Center gravity
    for (const n of nodes) {
      n.vx += (W / 2 - n.x) * 0.005 * alpha;
      n.vy += (H / 2 - n.y) * 0.005 * alpha;
      n.vx *= 0.85; n.vy *= 0.85;
      n.x += n.vx; n.y += n.vy;
      // Clamp
      n.x = Math.max(60, Math.min(W - 60, n.x));
      n.y = Math.max(40, Math.min(H - 60, n.y));
    }
  }

  // Year-based color
  function yearToColor(year) {
    if (!year) return "#666";
    const minY = 2000, maxY = 2026;
    const t = Math.max(0, Math.min(1, (year - minY) / (maxY - minY)));
    const r = Math.round(40 + t * 215);
    const g = Math.round(60 + (t < 0.5 ? t * 2 * 180 : (1 - t) * 2 * 180 + 40));
    const b = Math.round(180 - t * 160);
    return `rgb(${r},${g},${b})`;
  }

  // Generate SVG
  let svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}">`;
  svg += `<rect width="${W}" height="${H}" fill="#0f0f1a"/>`;

  // Title
  svg += `<text x="${W/2}" y="30" text-anchor="middle" fill="#e0e0f0" font-family="Arial,sans-serif" font-size="18" font-weight="bold">Paper Copilot — "${escXml(query)}"</text>`;

  // Edges
  for (const [si, ti] of edges) {
    svg += `<line x1="${nodes[si].x}" y1="${nodes[si].y}" x2="${nodes[ti].x}" y2="${nodes[ti].y}" stroke="rgba(140,180,255,0.3)" stroke-width="1"/>`;
  }

  // Nodes + labels
  for (const n of nodes) {
    const color = yearToColor(n.paper.year);
    svg += `<circle cx="${n.x}" cy="${n.y}" r="${n.r}" fill="${color}" stroke="#222" stroke-width="1.5"/>`;
    // Label
    const last = n.paper.authors[0] ? n.paper.authors[0].split(" ").pop() : "?";
    const suffix = n.paper.authors.length > 1 ? " et al." : "";
    const label = `${last}${suffix} ${n.paper.year || ""}`;
    svg += `<text x="${n.x + n.r + 4}" y="${n.y + 4}" fill="#ccc" font-family="Arial,sans-serif" font-size="10">${escXml(label)}</text>`;
  }

  // Year legend
  const legendX = 20, legendY = H - 60;
  svg += `<rect x="${legendX}" y="${legendY}" width="180" height="50" rx="6" fill="rgba(26,26,46,0.9)"/>`;
  svg += `<text x="${legendX + 10}" y="${legendY + 16}" fill="#888" font-family="Arial,sans-serif" font-size="10">Year</text>`;
  for (let i = 0; i <= 4; i++) {
    const yr = 2010 + i * 4;
    const cx = legendX + 15 + i * 35;
    svg += `<circle cx="${cx}" cy="${legendY + 32}" r="5" fill="${yearToColor(yr)}"/>`;
    svg += `<text x="${cx}" y="${legendY + 45}" text-anchor="middle" fill="#888" font-family="Arial,sans-serif" font-size="8">${yr}</text>`;
  }

  // Paper count
  svg += `<text x="${W - 20}" y="${H - 10}" text-anchor="end" fill="#555" font-family="Arial,sans-serif" font-size="10">${nodes.length} papers</text>`;

  svg += `</svg>`;

  // Convert SVG to PNG
  const resvg = new Resvg(svg, { fitTo: { mode: "width", value: W } });
  const pngData = resvg.render();
  return pngData.asPng();
}

function escXml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// ── S2 API ──

let _s2Key = "";
async function s2Fetch(url) {
  const headers = { "User-Agent": "PaperCopilot/1.0" };
  if (_s2Key) headers["x-api-key"] = _s2Key;
  for (let attempt = 0; attempt < 5; attempt++) {
    const resp = await fetch(url, { headers });
    if (resp.ok) return resp;
    if (resp.status === 429) {
      await new Promise(r => setTimeout(r, (attempt + 1) * 3000));
      continue;
    }
    throw new Error(`S2 API error: ${resp.status}`);
  }
  throw new Error("S2 API rate limited. Try again later.");
}

async function searchPapersWithRefs(query) {
  // Step 1: Search
  const fields = "paperId,title,authors,abstract,year,venue,externalIds,citationCount";
  const searchUrl = `${S2_API}/paper/search?query=${encodeURIComponent(query)}&limit=20&fields=${fields}`;
  const resp = await s2Fetch(searchUrl);
  const data = await resp.json();
  const seeds = (data.data || []).map(parsePaper);

  if (!seeds.length) return [];

  // Step 2: Batch fetch references
  const batchFields = "paperId,title,authors,abstract,year,venue,externalIds,citationCount,references";
  const batchUrl = `${S2_API}/paper/batch?fields=${batchFields}`;
  const batchHeaders = { "User-Agent": "PaperCopilot/1.0", "Content-Type": "application/json" };
  if (_s2Key) batchHeaders["x-api-key"] = _s2Key;

  const batchResp = await fetch(batchUrl, {
    method: "POST",
    headers: batchHeaders,
    body: JSON.stringify({ ids: seeds.map(s => s.id) }),
  });

  if (batchResp.ok) {
    const batchData = await batchResp.json();
    for (const d of batchData) {
      if (!d || !d.paperId) continue;
      const seed = seeds.find(s => s.id === d.paperId);
      if (seed) seed.references = (d.references || []).filter(r => r && r.paperId).map(r => r.paperId);
    }
  }

  return seeds.sort((a, b) => b.cited - a.cited);
}

function parsePaper(d) {
  const authors = (d.authors || []).map(a => a.name).filter(Boolean);
  const extIds = d.externalIds || {};
  return {
    id: d.paperId || "",
    title: d.title || "",
    authors,
    abstract: d.abstract || "",
    year: d.year || 0,
    venue: d.venue || "",
    cited: d.citationCount || 0,
    arxivId: extIds.ArXiv || "",
    references: [],
  };
}

// ── Slack ──

async function postSlackChat(token, channel, text) {
  await fetch("https://slack.com/api/chat.postMessage", {
    method: "POST",
    headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
    body: JSON.stringify({ channel, text }),
  });
}

async function uploadSlackImage(token, channel, pngBuffer, query, pageUrl) {
  // Step 1: Get upload URL
  const getUrlResp = await fetch("https://slack.com/api/files.getUploadURLExternal", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded", "Authorization": `Bearer ${token}` },
    body: `filename=paper-graph-${encodeURIComponent(query)}.png&length=${pngBuffer.byteLength}`,
  });
  const urlData = await getUrlResp.json();

  if (!urlData.ok) {
    // Fallback: post text
    await postSlackChat(token, channel, `📊 *Paper Citation Graph: "${query}"*\n<${pageUrl}|🔗 Open interactive graph>`);
    return;
  }

  // Step 2: Upload
  await fetch(urlData.upload_url, {
    method: "POST",
    headers: { "Content-Type": "image/png" },
    body: pngBuffer,
  });

  // Step 3: Complete and share
  await fetch("https://slack.com/api/files.completeUploadExternal", {
    method: "POST",
    headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
    body: JSON.stringify({
      files: [{ id: urlData.file_id, title: `Paper Graph: ${query}` }],
      channel_id: channel,
      initial_comment: `📊 *Paper Citation Graph: "${query}"*\n<${pageUrl}|🔗 Open interactive graph>`,
    }),
  });
}

async function sendSlackMessage(responseUrl, body) {
  await fetch(responseUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function jsonResponse(data) {
  return new Response(JSON.stringify(data), {
    headers: { "Content-Type": "application/json" },
  });
}
