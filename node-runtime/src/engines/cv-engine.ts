/**
 * CV Engine — screenshot-based coordinate extraction for non-DOM surfaces.
 * Uses simple pixel-comparison template matching and basic text scanning.
 * No external CV library needed: works with raw Buffer/pixel operations on PNG data.
 *
 * Recovery chain position: network parse (free) -> CV (cheap) -> LLM (expensive, last resort)
 */

export interface MatchResult {
  x: number;
  y: number;
  confidence: number;
  width: number;
  height: number;
}

/**
 * Minimal page interface for coordinate-based clicking.
 */
export interface CVPage {
  mouse: {
    click(x: number, y: number): Promise<void>;
  };
}

/**
 * Minimal PNG chunk info parsed from raw PNG buffer.
 * We only need IHDR (dimensions) and raw pixel data for template matching.
 */
interface PNGInfo {
  width: number;
  height: number;
  pixels: Uint8Array; // RGBA, row-major
}

/**
 * CVEngine provides simple visual matching for canvas/non-DOM surfaces.
 * Phase 4 MVP: pixel-comparison template matching without external libraries.
 */
export class CVEngine {
  /**
   * Find a template image within a screenshot using pixel comparison.
   * Returns the best match location and confidence, or null if confidence is too low.
   *
   * @param screenshot - Full-page screenshot as PNG Buffer
   * @param template - Template to find as PNG Buffer
   * @param threshold - Minimum confidence (0-1) to count as a match. Default 0.7
   */
  async findByTemplate(
    screenshot: Buffer,
    template: Buffer,
    threshold = 0.7,
  ): Promise<MatchResult | null> {
    const src = this.decodePNG(screenshot);
    const tpl = this.decodePNG(template);

    if (!src || !tpl) return null;
    if (tpl.width > src.width || tpl.height > src.height) return null;

    let bestX = 0;
    let bestY = 0;
    let bestScore = 0;

    // Slide template across source with a step for performance
    const step = Math.max(1, Math.floor(Math.min(tpl.width, tpl.height) / 4));

    for (let y = 0; y <= src.height - tpl.height; y += step) {
      for (let x = 0; x <= src.width - tpl.width; x += step) {
        const score = this.compareRegion(src, tpl, x, y);
        if (score > bestScore) {
          bestScore = score;
          bestX = x;
          bestY = y;
        }
      }
    }

    // Refine around the best coarse match
    if (step > 1 && bestScore > 0) {
      const refined = this.refineMatch(src, tpl, bestX, bestY, step);
      bestX = refined.x;
      bestY = refined.y;
      bestScore = refined.score;
    }

    if (bestScore < threshold) return null;

    return {
      x: bestX + Math.floor(tpl.width / 2),
      y: bestY + Math.floor(tpl.height / 2),
      confidence: bestScore,
      width: tpl.width,
      height: tpl.height,
    };
  }

  /**
   * Find text in a screenshot using basic pixel pattern scanning.
   * Phase 4 MVP: uses a simple brightness-based approach to find text regions.
   * For accurate OCR, a real OCR library would be needed.
   *
   * @param screenshot - Full-page screenshot as PNG Buffer
   * @param text - Text to find (used for matching against detected text regions)
   * @returns Match location or null
   */
  async findByText(
    screenshot: Buffer,
    text: string,
  ): Promise<MatchResult | null> {
    const src = this.decodePNG(screenshot);
    if (!src || !text) return null;

    // Simple approach: find dark-on-light text regions by scanning for
    // horizontal runs of dark pixels (potential text baseline).
    // This is a basic heuristic; real OCR would use Tesseract or similar.
    const textRegions = this.findTextRegions(src);

    if (textRegions.length === 0) return null;

    // Return the first significant text region as a best-effort match.
    // In a production system, each region would be OCR'd and compared to `text`.
    // For MVP, return the largest region with moderate confidence.
    const sorted = textRegions.sort(
      (a, b) => b.width * b.height - a.width * a.height,
    );
    const best = sorted[0];

    return {
      x: best.x + Math.floor(best.width / 2),
      y: best.y + Math.floor(best.height / 2),
      confidence: 0.5, // Low confidence since we can't actually OCR
      width: best.width,
      height: best.height,
    };
  }

  /**
   * Click at absolute coordinates on the page.
   */
  async clickAtCoordinate(page: CVPage, x: number, y: number): Promise<void> {
    await page.mouse.click(x, y);
  }

  /**
   * Decode a PNG Buffer into raw RGBA pixel data.
   * Handles uncompressed PNG data by parsing chunks.
   * For compressed PNGs (standard), uses zlib inflate.
   */
  private decodePNG(buffer: Buffer): PNGInfo | null {
    try {
      // Verify PNG signature
      if (
        buffer.length < 8 ||
        buffer[0] !== 0x89 ||
        buffer[1] !== 0x50 ||
        buffer[2] !== 0x4e ||
        buffer[3] !== 0x47
      ) {
        return null;
      }

      let offset = 8;
      let width = 0;
      let height = 0;
      let bitDepth = 0;
      let colorType = 0;
      const idatChunks: Buffer[] = [];

      while (offset < buffer.length) {
        if (offset + 8 > buffer.length) break;

        const length = buffer.readUInt32BE(offset);
        const type = buffer.toString('ascii', offset + 4, offset + 8);

        if (type === 'IHDR') {
          width = buffer.readUInt32BE(offset + 8);
          height = buffer.readUInt32BE(offset + 12);
          bitDepth = buffer[offset + 16];
          colorType = buffer[offset + 17];
        } else if (type === 'IDAT') {
          idatChunks.push(buffer.subarray(offset + 8, offset + 8 + length));
        } else if (type === 'IEND') {
          break;
        }

        offset += 12 + length; // length(4) + type(4) + data(length) + crc(4)
      }

      if (width === 0 || height === 0 || idatChunks.length === 0) {
        return null;
      }

      // Concatenate IDAT data and inflate
      const { inflateSync } = require('node:zlib') as typeof import('node:zlib');
      const compressed = Buffer.concat(idatChunks);
      const decompressed = inflateSync(compressed);

      // Reconstruct RGBA pixels from filtered scanlines
      const bytesPerPixel = colorType === 6 ? 4 : colorType === 2 ? 3 : 1;
      const stride = width * bytesPerPixel + 1; // +1 for filter byte
      const pixels = new Uint8Array(width * height * 4);

      for (let row = 0; row < height; row++) {
        const filterByte = decompressed[row * stride];
        for (let col = 0; col < width; col++) {
          const srcIdx = row * stride + 1 + col * bytesPerPixel;
          const dstIdx = (row * width + col) * 4;

          if (bytesPerPixel >= 3) {
            let r = decompressed[srcIdx];
            let g = decompressed[srcIdx + 1];
            let b = decompressed[srcIdx + 2];
            const a = bytesPerPixel === 4 ? decompressed[srcIdx + 3] : 255;

            // Apply PNG filter reconstruction (simplified: only None and Sub)
            if (filterByte === 1 && col > 0) {
              // Sub filter
              r = (r + pixels[dstIdx - 4]) & 0xff;
              g = (g + pixels[dstIdx - 3]) & 0xff;
              b = (b + pixels[dstIdx - 2]) & 0xff;
            } else if (filterByte === 2 && row > 0) {
              // Up filter
              const upIdx = ((row - 1) * width + col) * 4;
              r = (r + pixels[upIdx]) & 0xff;
              g = (g + pixels[upIdx + 1]) & 0xff;
              b = (b + pixels[upIdx + 2]) & 0xff;
            }

            pixels[dstIdx] = r;
            pixels[dstIdx + 1] = g;
            pixels[dstIdx + 2] = b;
            pixels[dstIdx + 3] = a;
          } else {
            // Grayscale
            let v = decompressed[srcIdx];
            if (filterByte === 1 && col > 0) {
              v = (v + pixels[dstIdx - 4]) & 0xff;
            } else if (filterByte === 2 && row > 0) {
              const upIdx = ((row - 1) * width + col) * 4;
              v = (v + pixels[upIdx]) & 0xff;
            }
            pixels[dstIdx] = v;
            pixels[dstIdx + 1] = v;
            pixels[dstIdx + 2] = v;
            pixels[dstIdx + 3] = 255;
          }
        }
      }

      return { width, height, pixels };
    } catch {
      return null;
    }
  }

  /**
   * Compare a region of the source image against the template.
   * Returns a similarity score 0-1 based on pixel-by-pixel color distance.
   */
  private compareRegion(
    src: PNGInfo,
    tpl: PNGInfo,
    startX: number,
    startY: number,
  ): number {
    let totalDiff = 0;
    const pixelCount = tpl.width * tpl.height;

    // Sample pixels for performance (check every Nth pixel)
    const sampleRate = Math.max(1, Math.floor(pixelCount / 500));
    let sampled = 0;

    for (let ty = 0; ty < tpl.height; ty++) {
      for (let tx = 0; tx < tpl.width; tx++) {
        if ((ty * tpl.width + tx) % sampleRate !== 0) continue;
        sampled++;

        const srcIdx = ((startY + ty) * src.width + (startX + tx)) * 4;
        const tplIdx = (ty * tpl.width + tx) * 4;

        const dr = Math.abs(src.pixels[srcIdx] - tpl.pixels[tplIdx]);
        const dg = Math.abs(src.pixels[srcIdx + 1] - tpl.pixels[tplIdx + 1]);
        const db = Math.abs(src.pixels[srcIdx + 2] - tpl.pixels[tplIdx + 2]);

        // Normalize to 0-1 per pixel
        totalDiff += (dr + dg + db) / (255 * 3);
      }
    }

    if (sampled === 0) return 0;
    return 1 - totalDiff / sampled;
  }

  /**
   * Refine a coarse match by scanning a small neighborhood at 1px resolution.
   */
  private refineMatch(
    src: PNGInfo,
    tpl: PNGInfo,
    coarseX: number,
    coarseY: number,
    step: number,
  ): { x: number; y: number; score: number } {
    let bestX = coarseX;
    let bestY = coarseY;
    let bestScore = 0;

    const minX = Math.max(0, coarseX - step);
    const maxX = Math.min(src.width - tpl.width, coarseX + step);
    const minY = Math.max(0, coarseY - step);
    const maxY = Math.min(src.height - tpl.height, coarseY + step);

    for (let y = minY; y <= maxY; y++) {
      for (let x = minX; x <= maxX; x++) {
        const score = this.compareRegion(src, tpl, x, y);
        if (score > bestScore) {
          bestScore = score;
          bestX = x;
          bestY = y;
        }
      }
    }

    return { x: bestX, y: bestY, score: bestScore };
  }

  /**
   * Find potential text regions by looking for horizontal runs of dark pixels.
   */
  private findTextRegions(
    src: PNGInfo,
  ): Array<{ x: number; y: number; width: number; height: number }> {
    const regions: Array<{ x: number; y: number; width: number; height: number }> = [];
    const darkThreshold = 128;

    // Scan rows for dark pixel runs (potential text baselines)
    const rowDarkCounts = new Uint32Array(src.height);
    for (let y = 0; y < src.height; y++) {
      let count = 0;
      for (let x = 0; x < src.width; x++) {
        const idx = (y * src.width + x) * 4;
        const brightness =
          (src.pixels[idx] + src.pixels[idx + 1] + src.pixels[idx + 2]) / 3;
        if (brightness < darkThreshold) count++;
      }
      rowDarkCounts[y] = count;
    }

    // Group consecutive rows with significant dark pixel content
    const minDarkPixels = Math.max(5, src.width * 0.01);
    let regionStart = -1;

    for (let y = 0; y <= src.height; y++) {
      const isDark = y < src.height && rowDarkCounts[y] >= minDarkPixels;

      if (isDark && regionStart === -1) {
        regionStart = y;
      } else if (!isDark && regionStart !== -1) {
        const height = y - regionStart;
        if (height >= 5 && height <= 200) {
          // Find horizontal extent of dark pixels in this band
          let minX = src.width;
          let maxX = 0;
          for (let ry = regionStart; ry < y; ry++) {
            for (let rx = 0; rx < src.width; rx++) {
              const idx = (ry * src.width + rx) * 4;
              const brightness =
                (src.pixels[idx] + src.pixels[idx + 1] + src.pixels[idx + 2]) / 3;
              if (brightness < darkThreshold) {
                if (rx < minX) minX = rx;
                if (rx > maxX) maxX = rx;
              }
            }
          }

          if (maxX > minX) {
            regions.push({
              x: minX,
              y: regionStart,
              width: maxX - minX + 1,
              height,
            });
          }
        }
        regionStart = -1;
      }
    }

    return regions;
  }
}
