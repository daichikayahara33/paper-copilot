export default {
  async fetch(request) {
    // Handle CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
          'Access-Control-Allow-Headers': 'Content-Type, x-s2-key',
          'Access-Control-Max-Age': '86400',
        },
      });
    }

    const url = new URL(request.url);
    const s2Url = 'https://api.semanticscholar.org/graph/v1' + url.pathname + url.search;

    // Forward S2 API key if provided
    const reqHeaders = { 'User-Agent': 'PaperCopilot/1.0' };
    const s2Key = request.headers.get('x-s2-key');
    if (s2Key) {
      reqHeaders['x-api-key'] = s2Key;
    }

    // Forward POST body for batch endpoint
    const fetchOpts = { headers: reqHeaders, method: request.method };
    if (request.method === 'POST') {
      reqHeaders['Content-Type'] = 'application/json';
      fetchOpts.body = await request.text();
    }

    const resp = await fetch(s2Url, fetchOpts);

    const headers = new Headers(resp.headers);
    headers.set('Access-Control-Allow-Origin', '*');

    return new Response(resp.body, {
      status: resp.status,
      headers,
    });
  },
};
