import { describe, it, expect, vi } from 'vitest';
import { CVEngine } from '../../src/engines/cv-engine.js';
import type { CVPage } from '../../src/engines/cv-engine.js';
import { deflateSync } from 'node:zlib';

function mockCVPage(): CVPage {
  return {
    mouse: {
      click: vi.fn().mockResolvedValue(undefined),
    },
  };
}

/**
 * Create a minimal valid PNG buffer with the given dimensions and solid color.
 * Uses no-filter (filter byte 0) scanlines for simplicity.
 */
function createPNG(
  width: number,
  height: number,
  color: { r: number; g: number; b: number; a?: number },
): Buffer {
  // PNG signature
  const signature = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

  // IHDR chunk
  const ihdrData = Buffer.alloc(13);
  ihdrData.writeUInt32BE(width, 0);
  ihdrData.writeUInt32BE(height, 4);
  ihdrData[8] = 8; // bit depth
  ihdrData[9] = 6; // color type: RGBA
  ihdrData[10] = 0; // compression
  ihdrData[11] = 0; // filter
  ihdrData[12] = 0; // interlace
  const ihdr = createChunk('IHDR', ihdrData);

  // Create raw pixel data with filter byte 0 (None) per row
  const rawData = Buffer.alloc(height * (1 + width * 4));
  for (let y = 0; y < height; y++) {
    const rowOffset = y * (1 + width * 4);
    rawData[rowOffset] = 0; // filter: None
    for (let x = 0; x < width; x++) {
      const pixelOffset = rowOffset + 1 + x * 4;
      rawData[pixelOffset] = color.r;
      rawData[pixelOffset + 1] = color.g;
      rawData[pixelOffset + 2] = color.b;
      rawData[pixelOffset + 3] = color.a ?? 255;
    }
  }

  const compressed = deflateSync(rawData);
  const idat = createChunk('IDAT', compressed);

  // IEND chunk
  const iend = createChunk('IEND', Buffer.alloc(0));

  return Buffer.concat([signature, ihdr, idat, iend]);
}

/**
 * Create a PNG with a colored rectangle at the given position.
 */
function createPNGWithRect(
  width: number,
  height: number,
  bgColor: { r: number; g: number; b: number },
  rect: { x: number; y: number; w: number; h: number; r: number; g: number; b: number },
): Buffer {
  const signature = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

  const ihdrData = Buffer.alloc(13);
  ihdrData.writeUInt32BE(width, 0);
  ihdrData.writeUInt32BE(height, 4);
  ihdrData[8] = 8;
  ihdrData[9] = 6; // RGBA
  ihdrData[10] = 0;
  ihdrData[11] = 0;
  ihdrData[12] = 0;
  const ihdr = createChunk('IHDR', ihdrData);

  const rawData = Buffer.alloc(height * (1 + width * 4));
  for (let y = 0; y < height; y++) {
    const rowOffset = y * (1 + width * 4);
    rawData[rowOffset] = 0; // filter: None
    for (let x = 0; x < width; x++) {
      const pixelOffset = rowOffset + 1 + x * 4;
      const inRect =
        x >= rect.x && x < rect.x + rect.w && y >= rect.y && y < rect.y + rect.h;
      rawData[pixelOffset] = inRect ? rect.r : bgColor.r;
      rawData[pixelOffset + 1] = inRect ? rect.g : bgColor.g;
      rawData[pixelOffset + 2] = inRect ? rect.b : bgColor.b;
      rawData[pixelOffset + 3] = 255;
    }
  }

  const compressed = deflateSync(rawData);
  const idat = createChunk('IDAT', compressed);
  const iend = createChunk('IEND', Buffer.alloc(0));

  return Buffer.concat([signature, ihdr, idat, iend]);
}

function createChunk(type: string, data: Buffer): Buffer {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length, 0);

  const typeBuffer = Buffer.from(type, 'ascii');
  const crcData = Buffer.concat([typeBuffer, data]);

  // Simple CRC32 (using node's zlib)
  const { crc32 } = require('node:zlib') as { crc32: (data: Buffer) => number };
  let crcValue: number;
  if (typeof crc32 === 'function') {
    crcValue = crc32(crcData);
  } else {
    // Fallback: compute CRC32 manually
    crcValue = computeCRC32(crcData);
  }
  const crcBuffer = Buffer.alloc(4);
  crcBuffer.writeUInt32BE(crcValue >>> 0, 0);

  return Buffer.concat([length, typeBuffer, data, crcBuffer]);
}

function computeCRC32(buf: Buffer): number {
  let crc = 0xffffffff;
  for (let i = 0; i < buf.length; i++) {
    crc ^= buf[i];
    for (let j = 0; j < 8; j++) {
      crc = crc & 1 ? (crc >>> 1) ^ 0xedb88320 : crc >>> 1;
    }
  }
  return crc ^ 0xffffffff;
}

describe('CVEngine', () => {
  describe('findByTemplate', () => {
    it('finds an exact match template in screenshot', async () => {
      const engine = new CVEngine();

      // Create a 20x20 screenshot with a 5x5 red square at position (8, 8)
      const screenshot = createPNGWithRect(
        20, 20,
        { r: 255, g: 255, b: 255 },
        { x: 8, y: 8, w: 5, h: 5, r: 255, g: 0, b: 0 },
      );

      // Template is just the 5x5 red square
      const template = createPNG(5, 5, { r: 255, g: 0, b: 0 });

      const result = await engine.findByTemplate(screenshot, template, 0.8);
      expect(result).not.toBeNull();
      if (result) {
        // Center of the match should be near (10, 10)
        expect(result.x).toBeGreaterThanOrEqual(8);
        expect(result.x).toBeLessThanOrEqual(13);
        expect(result.y).toBeGreaterThanOrEqual(8);
        expect(result.y).toBeLessThanOrEqual(13);
        expect(result.confidence).toBeGreaterThan(0.8);
        expect(result.width).toBe(5);
        expect(result.height).toBe(5);
      }
    });

    it('returns null when template not found (low confidence)', async () => {
      const engine = new CVEngine();

      // All-white screenshot
      const screenshot = createPNG(20, 20, { r: 255, g: 255, b: 255 });

      // All-red template (not present in screenshot)
      const template = createPNG(5, 5, { r: 255, g: 0, b: 0 });

      const result = await engine.findByTemplate(screenshot, template, 0.95);
      expect(result).toBeNull();
    });

    it('returns null for invalid PNG input', async () => {
      const engine = new CVEngine();
      const result = await engine.findByTemplate(
        Buffer.from('not a png'),
        Buffer.from('also not'),
      );
      expect(result).toBeNull();
    });

    it('returns null when template is larger than screenshot', async () => {
      const engine = new CVEngine();
      const small = createPNG(5, 5, { r: 0, g: 0, b: 0 });
      const big = createPNG(10, 10, { r: 0, g: 0, b: 0 });

      const result = await engine.findByTemplate(small, big);
      expect(result).toBeNull();
    });

    it('finds a matching solid color block', async () => {
      const engine = new CVEngine();

      // Screenshot: 10x10 white with 3x3 black square at (4,4)
      const screenshot = createPNGWithRect(
        10, 10,
        { r: 255, g: 255, b: 255 },
        { x: 4, y: 4, w: 3, h: 3, r: 0, g: 0, b: 0 },
      );

      // Template: 3x3 black
      const template = createPNG(3, 3, { r: 0, g: 0, b: 0 });

      const result = await engine.findByTemplate(screenshot, template, 0.7);
      expect(result).not.toBeNull();
      if (result) {
        expect(result.confidence).toBeGreaterThan(0.7);
      }
    });
  });

  describe('findByText', () => {
    it('finds text regions in a screenshot with dark pixels', async () => {
      const engine = new CVEngine();

      // Create screenshot with a dark text-like band
      const screenshot = createPNGWithRect(
        100, 50,
        { r: 255, g: 255, b: 255 },
        { x: 10, y: 20, w: 80, h: 10, r: 20, g: 20, b: 20 },
      );

      const result = await engine.findByText(screenshot, 'some text');
      expect(result).not.toBeNull();
      if (result) {
        expect(result.x).toBeGreaterThan(0);
        expect(result.y).toBeGreaterThan(0);
        // Low confidence since we can't actually OCR
        expect(result.confidence).toBeLessThanOrEqual(1);
      }
    });

    it('returns null for empty text', async () => {
      const engine = new CVEngine();
      const screenshot = createPNG(10, 10, { r: 255, g: 255, b: 255 });

      const result = await engine.findByText(screenshot, '');
      expect(result).toBeNull();
    });

    it('returns null for invalid PNG', async () => {
      const engine = new CVEngine();
      const result = await engine.findByText(Buffer.from('bad'), 'text');
      expect(result).toBeNull();
    });

    it('returns null for all-white image (no text regions)', async () => {
      const engine = new CVEngine();
      const screenshot = createPNG(50, 50, { r: 255, g: 255, b: 255 });

      const result = await engine.findByText(screenshot, 'some text');
      expect(result).toBeNull();
    });
  });

  describe('clickAtCoordinate', () => {
    it('clicks at the specified coordinates', async () => {
      const engine = new CVEngine();
      const page = mockCVPage();

      await engine.clickAtCoordinate(page, 150, 200);
      expect(page.mouse.click).toHaveBeenCalledWith(150, 200);
    });

    it('clicks at origin coordinates', async () => {
      const engine = new CVEngine();
      const page = mockCVPage();

      await engine.clickAtCoordinate(page, 0, 0);
      expect(page.mouse.click).toHaveBeenCalledWith(0, 0);
    });
  });
});
