// Cloudflare Worker — video proxy for HLS streams
// Deploy this as a separate Worker on your Cloudflare account
// It proxies HLS playlists and segments through Cloudflare's network

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const target = url.searchParams.get("url");
    if (!target) return new Response("Missing ?url=", { status: 400 });

    const headers = {
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
      "Referer": "https://megaplay.buzz/",
      "Origin": "https://megaplay.buzz",
    };

    const resp = await fetch(target, { headers });
    if (!resp.ok) return new Response(await resp.text(), { status: resp.status });

    const ct = resp.headers.get("content-type") || "";
    let body = await resp.text();

    // If it's a playlist (m3u8), rewrite segment URLs through this proxy
    if (ct.includes("m3u8") || target.includes(".m3u8")) {
      const baseUrl = target.substring(0, target.lastIndexOf("/") + 1);
      const proxyBase = `${url.origin}${url.pathname}`;

      body = body.split("\n").map(line => {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith("#")) return line;
        // Build absolute URL for relative paths
        const absUrl = trimmed.startsWith("http") ? trimmed : new URL(trimmed, baseUrl).href;
        return `${proxyBase}?url=${encodeURIComponent(absUrl)}`;
      }).join("\n");
    }

    return new Response(body, {
      headers: {
        "Content-Type": ct || "application/octet-stream",
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "public, max-age=3600",
      },
    });
  }
};
