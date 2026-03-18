export default {
  async fetch(request) {
    // Handle CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'GET, OPTIONS',
          'Access-Control-Max-Age': '86400',
        },
      });
    }

    const url = new URL(request.url);
    // /paper/search?query=... -> https://api.semanticscholar.org/graph/v1/paper/search?query=...
    const s2Url = 'https://api.semanticscholar.org/graph/v1' + url.pathname + url.search;

    const resp = await fetch(s2Url, {
      headers: { 'User-Agent': 'PaperCopilot/1.0' },
    });

    const headers = new Headers(resp.headers);
    headers.set('Access-Control-Allow-Origin', '*');

    return new Response(resp.body, {
      status: resp.status,
      headers,
    });
  },
};
