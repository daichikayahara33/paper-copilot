export default {
  async fetch(request, env) {
    const url = new URL(request.url);

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

    // OpenAI proxy: POST /openai/chat/completions
    if (url.pathname.startsWith('/openai/')) {
      const openaiKey = env.OPENAI_API_KEY || '';
      if (!openaiKey) {
        return corsJson({ error: 'OpenAI API key not configured' }, 500);
      }

      const openaiPath = url.pathname.replace('/openai/', '');
      const openaiUrl = `https://api.openai.com/v1/${openaiPath}`;

      const resp = await fetch(openaiUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${openaiKey}`,
        },
        body: await request.text(),
      });

      const headers = new Headers(resp.headers);
      headers.set('Access-Control-Allow-Origin', '*');
      return new Response(resp.body, { status: resp.status, headers });
    }

    // S2 API proxy
    const s2Url = 'https://api.semanticscholar.org/graph/v1' + url.pathname + url.search;

    const S2_KEY = 'n7fSfkv71U1BCQ2ucjW79KYGVMx2zFL5DPVrP7gj';
    const reqHeaders = { 'User-Agent': 'PaperCopilot/1.0' };
    const s2Key = request.headers.get('x-s2-key') || S2_KEY;
    if (s2Key) {
      reqHeaders['x-api-key'] = s2Key;
    }

    const fetchOpts = { headers: reqHeaders, method: request.method };
    if (request.method === 'POST') {
      reqHeaders['Content-Type'] = 'application/json';
      fetchOpts.body = await request.text();
    }

    const resp = await fetch(s2Url, fetchOpts);
    const headers = new Headers(resp.headers);
    headers.set('Access-Control-Allow-Origin', '*');

    return new Response(resp.body, { status: resp.status, headers });
  },
};

function corsJson(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      'Content-Type': 'application/json',
      'Access-Control-Allow-Origin': '*',
    },
  });
}
