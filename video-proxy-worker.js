// Cloudflare Worker — HLS/Video proxy for blocked CDNs
// Deploy this on your Cloudflare account (free tier: 100k req/day)
// Then set CLOUDFLARE_WORKER_URL in your .env
//
// Usage:
//   ?url=https://uwucdn.top/.../master.m3u8
//   &referer=https://allmanga.to/&origin=https://allmanga.to
//
// It fetches the URL through Cloudflare's network (which can reach
// Cloudflare-protected CDNs that block datacenter IPs), rewrites
// HLS playlists to proxy segments through itself, and returns the content.

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const target = url.searchParams.get("url");
    if (!target) {
      return new Response(JSON.stringify({ error: "Missing ?url=" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    const referer = url.searchParams.get("referer") || "https://www.miruro.tv/";
    const origin = url.searchParams.get("origin") || "https://www.miruro.tv";

    const headers = {
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
      Referer: referer,
      Origin: origin,
      Accept: "*/*",
    };

    // Forward Range header if present (for byte-range requests)
    const range = request.headers.get("Range");
    if (range) headers["Range"] = range;

    try {
      const resp = await fetch(target, { headers });

      if (!resp.ok) {
        return new Response(await resp.text(), {
          status: resp.status,
          headers: { "Access-Control-Allow-Origin": "*" },
        });
      }

      const ct = resp.headers.get("content-type") || "";
      const isPlaylist = ct.includes("m3u8") || target.includes(".m3u8");

      // Pass through binary data (segments, keys, etc.) as-is
      if (!isPlaylist) {
        return new Response(resp.body, {
          headers: {
            "Content-Type": ct || "application/octet-stream",
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=86400",
            "Content-Length": resp.headers.get("content-length") || "",
          },
        });
      }

      // Rewrite HLS playlist — proxy all segment URLs through this Worker
      const body = await resp.text();
      const baseUrl = target.substring(0, target.lastIndexOf("/") + 1);
      const proxyBase = `${url.origin}${url.pathname}`;

      const rewritten = body.split("\n").map((line) => {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith("#")) return line;

        const absUrl = trimmed.startsWith("http")
          ? trimmed
          : new URL(trimmed, baseUrl).href;

        const params = new URLSearchParams({
          url: absUrl,
          referer,
          origin,
        });
        return `${proxyBase}?${params}`;
      }).join("\n");

      return new Response(rewritten, {
        headers: {
          "Content-Type": ct || "application/vnd.apple.mpegurl",
          "Access-Control-Allow-Origin": "*",
          "Cache-Control": "public, max-age=3600",
        },
      });
    } catch (err) {
      return new Response(JSON.stringify({ error: err.message }), {
        status: 502,
        headers: {
          "Content-Type": "application/json",
          "Access-Control-Allow-Origin": "*",
        },
      });
    }
  },
};
