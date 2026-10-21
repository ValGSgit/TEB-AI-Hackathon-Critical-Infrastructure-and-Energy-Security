// Regenerate data/world-50m.txt from Natural Earth borders: npm install world-atlas@2.0.2 topojson-client@3.1.0 && node world.js 50m
const topo = require('topojson-client');
const fs = require('fs');
const res = process.argv[2] || '50m';
const w = JSON.parse(fs.readFileSync(`node_modules/world-atlas/countries-${res}.json`));
const fc = topo.feature(w, w.objects.countries);
let d = '';
for (const f of fc.features) {
  const g = f.geometry;
  if (!g) continue;
  const polys = g.type === 'Polygon' ? [g.coordinates] : g.coordinates;
  for (const p of polys) for (const ring of p) {
    let s = '', n = 0, last = '', px = null;
    for (const [lo, la] of ring) {
      const x = Math.round((lo + 180) * 10), y = Math.round((90 - la) * 10);
      const k = x + ',' + y;
      if (k === last) continue;
      last = k;
      const jump = px !== null && Math.abs(x - px) > 1800;
      s += (n && !jump ? 'L' : 'M') + x + ' ' + y;
      px = x; n++;
    }
    if (n > 2) d += s + 'Z';
  }
}
fs.writeFileSync(require('path').join(__dirname, 'data', `world-${res}.txt`), d);
console.log(res, d.length);
