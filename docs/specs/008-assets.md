# 008 — Asset pipeline

**Phase 5** · depends on 002, 003 · ADR-0003

Resize on download, discard originals, deduplicate by content hash.

---

## 1. Flow

```
1. Page worker extracts image URLs, resolves to absolute,
   inserts asset_queue rows, and moves on. It never blocks on an image.
2. Asset worker claims a row, acquires AssetGate for the host (spec 002 §6).
3. Fetch bytes.
4. Hash the raw bytes (sha256).
     ├ hash exists in `assets` → link observation_assets, done.
     │                            No decode, no write.
     └ new → continue
5. Decode with Pillow. Resize to fit the configured box (default 1200×1200),
   DOWNSCALE ONLY — an image already smaller is stored as-is.
6. Encode WebP quality 82; JPEG fallback on failure.
7. Write /data/assets/<hash[0:2]>/<hash[2:4]>/<hash>.webp, insert `assets`,
   link `observation_assets`.
```

**Hash before decode.** Decoding is the expensive step and most re-crawls
return identical bytes, so hashing first makes a repeat crawl nearly free on
the image path.

**Two-level directory sharding.** A flat directory with hundreds of thousands
of files degrades on every filesystem; two hex levels gives 65,536 buckets.

**Content-addressed paths.** The same product image used across several pages
is stored once and its path is derivable from the hash without a database
lookup.

## 2. Limits and safety

| Guard | Value | Why |
| --- | --- | --- |
| Max download | 20 MB | A mis-selected `<a href>` to a PDF or video |
| Content-type allowlist | `image/*` only | Verify the **bytes**, not the header |
| Max dimensions | 10,000 px either side | Decompression bombs |
| `Image.MAX_IMAGE_PIXELS` | set explicitly | Pillow's own bomb guard |
| Timeout | 30 s | |
| Attempts | 3, then `failed` | |

Verify the real format by sniffing bytes. A `Content-Type: image/jpeg` on an
HTML error page is common and must not reach Pillow as trusted input.

## 3. Hosts and politeness

Image hosts are usually a CDN on a different host from the page
(`cdn.shopify.com`, Cloudinary). They are gated by `AssetGate` per host at
`asset_concurrency` (default 5) with a 200 ms gap — **not** by the page
domain's gate.

If the asset host *is* the page host, the same loose asset limit still
applies. This is deliberate: an image is a static byte range costing the
origin almost nothing, and six concurrent fetches is what a real browser does
(ADR-0003).

A 429 from an asset host backs that host off in-process. It does not pause the
domain and does not stop page crawling.

## 4. Scale

At the onboarding pace (2–3 domains at a time) this is small. At the
1,200-domain end state assume roughly 20,000 products × 6 images × ~150 KB
post-resize ≈ **18 GB**, with dedupe typically removing 10–20%.

Budget disk accordingly; do not over-engineer for it now. A pre-run free-space
check refuses to start below a threshold, and the HTML purge sweep runs first.

**Originals are discarded** per the operator's requirement. If a different box
size is ever wanted, that means a re-crawl — which is why the box should be
set generously once rather than tuned often.

## 5. Acceptance

- [ ] The same image on two pages is stored once and linked twice.
- [ ] A re-crawl returning identical bytes performs no decode and no write.
- [ ] A 40 MB file is rejected before download completes.
- [ ] An HTML page served as `image/jpeg` is rejected without reaching Pillow.
- [ ] A 600×400 source is stored at 600×400, not upscaled to the box.
- [ ] A slow asset host does not reduce page throughput (measured).
- [ ] Asset queue depth above threshold slows page claiming (spec 002 §7).
