import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import zlib from "node:zlib";
import test from "node:test";

const webRoot = fileURLToPath(new URL("../", import.meta.url));

function decodeIndexedPng(filePath) {
  const data = fs.readFileSync(filePath);
  assert.deepEqual(data.subarray(0, 8), Buffer.from("89504e470d0a1a0a", "hex"));

  let offset = 8;
  let header;
  let transparency;
  const imageData = [];
  while (offset < data.length) {
    const length = data.readUInt32BE(offset);
    const type = data.toString("ascii", offset + 4, offset + 8);
    const chunk = data.subarray(offset + 8, offset + 8 + length);
    if (type === "IHDR") {
      header = {
        width: chunk.readUInt32BE(0),
        height: chunk.readUInt32BE(4),
        bitDepth: chunk[8],
        colorType: chunk[9],
        interlace: chunk[12],
      };
    } else if (type === "tRNS") {
      transparency = chunk;
    } else if (type === "IDAT") {
      imageData.push(chunk);
    }
    offset += 12 + length;
  }

  assert.deepEqual(header, {
    width: header.width,
    height: header.height,
    bitDepth: 8,
    colorType: 3,
    interlace: 0,
  });
  const inflated = zlib.inflateSync(Buffer.concat(imageData));
  const rows = [];
  let cursor = 0;
  let previous = Buffer.alloc(header.width);
  for (let y = 0; y < header.height; y += 1) {
    const filter = inflated[cursor++];
    const row = Buffer.alloc(header.width);
    for (let x = 0; x < header.width; x += 1) {
      let value = inflated[cursor++];
      const left = x > 0 ? row[x - 1] : 0;
      const above = previous[x];
      const upperLeft = x > 0 ? previous[x - 1] : 0;
      if (filter === 1) value = (value + left) & 0xff;
      else if (filter === 2) value = (value + above) & 0xff;
      else if (filter === 3) value = (value + Math.floor((left + above) / 2)) & 0xff;
      else if (filter === 4) {
        const estimate = left + above - upperLeft;
        const leftDistance = Math.abs(estimate - left);
        const aboveDistance = Math.abs(estimate - above);
        const upperLeftDistance = Math.abs(estimate - upperLeft);
        value = (value + (leftDistance <= aboveDistance && leftDistance <= upperLeftDistance ? left : aboveDistance <= upperLeftDistance ? above : upperLeft)) & 0xff;
      } else {
        assert.equal(filter, 0, `unsupported PNG filter ${filter}`);
      }
      row[x] = value;
    }
    rows.push(row);
    previous = row;
  }
  return { header, rows, transparency };
}

test("favicon link points to the square official BRIN mark asset", () => {
  const html = fs.readFileSync(path.join(webRoot, "index.html"), "utf8");
  const match = html.match(/<link rel="icon" type="image\/png" sizes="149x149" href="([^"]+)" \/>/);
  assert.ok(match, "index.html should declare the favicon");
  assert.equal(match[1], "/app/favicon-brin-mark-v1.png");

  const faviconPath = path.join(webRoot, "public", match[1].replace(/^\/app\//, ""));
  assert.ok(fs.existsSync(faviconPath), "favicon asset should exist in the Vite public directory");
  const favicon = decodeIndexedPng(faviconPath);
  assert.equal(favicon.header.width, favicon.header.height, "favicon must be square");
  assert.equal(favicon.header.width, 149);
  assert.ok(favicon.transparency, "favicon must retain transparent padding");
});

test("favicon pixels are an exact crop of the existing official logo mark", () => {
  const source = decodeIndexedPng(path.join(webRoot, "src", "assets", "brin-logo.png"));
  const favicon = decodeIndexedPng(path.join(webRoot, "public", "favicon-brin-mark-v1.png"));
  const sourceX = 6;
  const sourceY = 5;
  const sourceWidth = 147;
  const sourceHeight = 139;
  const destinationX = 1;
  const destinationY = 5;

  for (let y = 0; y < favicon.header.height; y += 1) {
    for (let x = 0; x < favicon.header.width; x += 1) {
      const insideMark = x >= destinationX && x < destinationX + sourceWidth && y >= destinationY && y < destinationY + sourceHeight;
      const actual = favicon.rows[y][x];
      const expected = insideMark ? source.rows[y - destinationY + sourceY][x - destinationX + sourceX] : 0;
      assert.equal(actual, expected, `favicon pixel mismatch at ${x},${y}`);
    }
  }
});
