export default {
  async fetch(request) {
    // Handle CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, {
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'GET, OPTIONS',
          'Access-Control-Allow-Headers': 'x-s2-key',
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

    const resp = await fetch(s2Url, { headers: reqHeaders });

    const headers = new Headers(resp.headers);
    headers.set('Access-Control-Allow-Origin', '*');

    return new Response(resp.body, {
      status: resp.status,
      headers,
    });
  },
};
