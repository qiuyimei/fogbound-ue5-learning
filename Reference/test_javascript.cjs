// 可选：node Reference/test_javascript.cjs。与 UE 导出的地图逐格比对。
const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');
const F=require('../Learning/algorithms.js');
const samples=JSON.parse(fs.readFileSync(path.join(__dirname,'../Learning/Data/ue_seed_samples.json'),'utf8'));
for(const sample of samples){const result=F.generate(sample.seed);assert.deepEqual(result.walls,sample.walls);assert.deepEqual(result.supplies,sample.supplies);assert.deepEqual(result.explored,sample.explored);assert.ok(F.bfs(result.walls,F.START).path.length);}
assert.equal(F.next(20,1),-1);assert.equal(F.next(21,3),-1);
const s={...F.generate(1),state:1,player:F.START,elapsed:0,cooldown:0,edits:0};s.walls=Array(F.W*F.H).fill(1);s.supplies=Array(F.W*F.H).fill(0);s.explored=Array(F.W*F.H).fill(1);
for(let x=1;x<20;x++)s.walls[21+x]=0;for(let y=1;y<16;y++)s.walls[y*21+19]=0;
const before=s.walls.slice();assert.equal(F.edit(s,28).accepted,false);assert.deepEqual(before,s.walls);assert.equal(s.cooldown,0);
console.log('JavaScript checks passed: 8 UE seed fixtures, row bounds, BFS and edit rollback.');
