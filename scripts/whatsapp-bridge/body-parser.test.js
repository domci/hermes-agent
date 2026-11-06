import assert from 'node:assert/strict';
import http from 'node:http';
import { gzipSync } from 'node:zlib';
import { test } from 'node:test';
import express from 'express';

// Exercise the same parser as bridge.js without loading Baileys, pairing a
// device, reading session state, or contacting WhatsApp.
test('JSON parser survives trailing bytes after a compressed request', async () => {
  const app = express();
  app.use(express.json());
  app.post('/synthetic', (req, res) => res.json(req.body));
  app.use((error, req, res, next) => {
    res.status(error.status || 400).json({ error: 'invalid body' });
  });
  const server = http.createServer(app);
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  const send = (body, encoding) => new Promise((resolve, reject) => {
    const request = http.request({
      host: '127.0.0.1', port, path: '/synthetic', method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': body.length,
        ...(encoding ? { 'Content-Encoding': encoding } : {}) },
    }, (response) => {
      let text = '';
      response.setEncoding('utf8');
      response.on('data', (chunk) => { text += chunk; });
      response.on('end', () => resolve({ status: response.statusCode, text }));
    });
    request.setTimeout(3000, () => request.destroy(new Error('request timeout')));
    request.on('error', reject);
    request.end(body);
  });
  try {
    const valid = gzipSync(Buffer.from('{"synthetic":true}'));
    const compressed = await send(valid, 'gzip');
    assert.equal(compressed.status, 200);
    assert.deepEqual(JSON.parse(compressed.text), { synthetic: true });
    // Decoding may reject immediately or after the valid frame has completed;
    // either response is permitted, but the process must remain usable.
    await send(Buffer.concat([valid, Buffer.from([0]), Buffer.alloc(100 * 1024, 0x58)]), 'gzip');
    await new Promise((resolve) => setTimeout(resolve, 100));
    const healthy = await send(Buffer.from('{"alive":true}'));
    assert.equal(healthy.status, 200);
    assert.deepEqual(JSON.parse(healthy.text), { alive: true });
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});
