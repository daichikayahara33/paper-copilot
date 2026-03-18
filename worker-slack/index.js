const APP_URL = "https://daichikayahara33.github.io/paper-copilot/";
const S2_API = "https://api.semanticscholar.org/graph/v1";

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    _s2Key = env.S2_API_KEY || "";

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

      ctx.waitUntil(handleQuery(env, text.trim(), null, responseUrl));

      return jsonResponse({
        response_type: "in_channel",
        text: `🔍 Searching papers for "${text.trim()}"...`,
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
          ctx.waitUntil(handleQuery(env, keyword, channel, null));
        }
        return new Response("ok");
      }

      return new Response("ok");
    }

    return new Response("Not found", { status: 404 });
  },
};

async function handleQuery(env, query, channel, responseUrl) {
  const botToken = env.SLACK_BOT_TOKEN;
  const pageUrl = `${APP_URL}?q=${encodeURIComponent(query)}&fresh=1`;

  try {
    // Search papers from S2 API
    const papers = await searchPapers(query);

    if (!papers.length) {
      const msg = `No papers found for "${query}".`;
      if (channel && botToken) await postSlackChat(botToken, channel, msg);
      else if (responseUrl) await sendSlackMessage(responseUrl, { response_type: "in_channel", text: msg });
      return;
    }

    // Build text summary
    const lines = papers.slice(0, 15).map((p, i) =>
      `${i + 1}. *${p.title}* (${p.year}) — cited: ${p.cited}\n    _${p.authors.slice(0, 3).join(", ")}_`
    );

    const text = `📊 *Paper Citation Graph: "${query}"*\n<${pageUrl}|🔗 Open interactive graph>\n\n${lines.join("\n\n")}`;

    // Build blocks
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

    // Add top papers
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

    if (channel && botToken) {
      await fetch("https://slack.com/api/chat.postMessage", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${botToken}` },
        body: JSON.stringify({ channel, text, blocks }),
      });
    } else if (responseUrl) {
      await sendSlackMessage(responseUrl, { response_type: "in_channel", text, blocks });
    }

  } catch (e) {
    const errMsg = `❌ Error: ${e.message}`;
    if (channel && botToken) await postSlackChat(botToken, channel, errMsg);
    else if (responseUrl) await sendSlackMessage(responseUrl, { response_type: "in_channel", text: errMsg });
  }
}

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

async function searchPapers(query) {
  const fields = "paperId,title,authors,abstract,year,venue,externalIds,citationCount";
  const url = `${S2_API}/paper/search?query=${encodeURIComponent(query)}&limit=20&fields=${fields}`;

  const resp = await s2Fetch(url);

  const data = await resp.json();
  return (data.data || []).map(d => {
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
    };
  }).sort((a, b) => b.cited - a.cited);
}

async function postSlackChat(token, channel, text) {
  await fetch("https://slack.com/api/chat.postMessage", {
    method: "POST",
    headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
    body: JSON.stringify({ channel, text }),
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
