import puppeteer from "@cloudflare/puppeteer";

const APP_URL = "https://daichikayahara33.github.io/paper-copilot/";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // Health check
    if (url.pathname === "/" && request.method === "GET") {
      return new Response("Paper Copilot Slack Bot is running.");
    }

    // Slack slash command: POST /slack
    if (url.pathname === "/slack" && request.method === "POST") {
      const formData = await request.formData();
      const text = formData.get("text") || "";
      const responseUrl = formData.get("response_url");

      if (!text.trim()) {
        return jsonResponse({ text: "Usage: /papers <keyword>\nExample: /papers VLA" });
      }

      // Respond immediately (Slack requires <3s)
      // Then process asynchronously
      const ctx = env.ctx || { waitUntil: (p) => p };
      ctx.waitUntil(generateAndSend(env, text.trim(), responseUrl));

      return jsonResponse({
        response_type: "in_channel",
        text: `🔍 Searching papers for "${text.trim()}"... Graph will be posted shortly.`,
      });
    }

    // Direct screenshot endpoint: GET /screenshot?q=keyword
    if (url.pathname === "/screenshot") {
      const query = url.searchParams.get("q");
      if (!query) return new Response("Missing ?q= parameter", { status: 400 });

      const imageBuffer = await takeScreenshot(env, query);
      if (!imageBuffer) return new Response("Screenshot failed", { status: 500 });

      return new Response(imageBuffer, {
        headers: { "Content-Type": "image/png" },
      });
    }

    return new Response("Not found", { status: 404 });
  },
};

async function generateAndSend(env, query, responseUrl) {
  try {
    const imageBuffer = await takeScreenshot(env, query);
    if (!imageBuffer) {
      await sendSlackMessage(responseUrl, { text: "❌ Failed to generate graph." });
      return;
    }

    // Upload image to Slack via response_url with image
    // response_url doesn't support file upload, so we post a link instead
    const pageUrl = `${APP_URL}?q=${encodeURIComponent(query)}`;
    await sendSlackMessage(responseUrl, {
      response_type: "in_channel",
      text: `📊 Paper graph for "${query}"`,
      blocks: [
        {
          type: "section",
          text: {
            type: "mrkdwn",
            text: `📊 *Paper Citation Graph: "${query}"*\n<${pageUrl}|Open interactive graph>`,
          },
        },
        {
          type: "image",
          image_url: `https://paper-copilot-slack.d-kayahara33.workers.dev/screenshot?q=${encodeURIComponent(query)}`,
          alt_text: `Paper graph for ${query}`,
        },
      ],
    });
  } catch (e) {
    if (responseUrl) {
      await sendSlackMessage(responseUrl, { text: `❌ Error: ${e.message}` });
    }
  }
}

async function takeScreenshot(env, query) {
  let browser;
  try {
    browser = await puppeteer.launch(env.BROWSER);
    const page = await browser.newPage();
    await page.setViewport({ width: 1400, height: 900 });

    const pageUrl = `${APP_URL}?q=${encodeURIComponent(query)}`;
    await page.goto(pageUrl, { waitUntil: "networkidle0", timeout: 30000 });

    // Wait for graph to stabilize (papers to load + simulation to settle)
    await page.waitForTimeout(15000);

    // Screenshot the graph area
    const screenshot = await page.screenshot({ type: "png" });
    return screenshot;
  } catch (e) {
    console.error("Screenshot error:", e);
    return null;
  } finally {
    if (browser) await browser.close();
  }
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
