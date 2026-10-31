/* 教学算法。可以由浏览器离线加载，也可在 Node.js 中运行验证。 */
(function(root){
  'use strict';
  const W=21,H=17,START=22,EXIT=334,DIRS=[[0,-1],[1,0],[0,1],[-1,0]];
  class Stream {
    constructor(seed){this.seed=seed>>>0;}
    int(low,high){this.seed=(Math.imul(this.seed,196314165)+907633515)>>>0;return low+Math.trunc(Math.fround((this.seed>>>9)/8388608*Math.fround(high-low+1)));}
  }
  function next(cell,dir,dist=1){const x=cell%W+DIRS[dir][0]*dist,y=Math.floor(cell/W)+DIRS[dir][1]*dist;return x>=0&&x<W&&y>=0&&y<H?y*W+x:-1;}
  function distance(a,b){return Math.abs(a%W-b%W)+Math.abs(Math.floor(a/W)-Math.floor(b/W));}
  function bfs(walls,start,goal=EXIT){
    const queue=[start],prev=new Int32Array(W*H).fill(-2);prev[start]=-1;let head=0;
    while(head<queue.length){const cell=queue[head++];if(cell===goal){const path=[];for(let p=goal;p!==-1;p=prev[p])path.push(p);return {path:path.reverse(),visited:head};}
      for(let d=0;d<4;d++){const n=next(cell,d);if(n>=0&&!walls[n]&&prev[n]===-2){prev[n]=cell;queue.push(n);}}
    }
    return {path:[],visited:head};
  }
  function generate(seed,withTrace=false){
    const rng=new Stream(seed),walls=Array(W*H).fill(1),supplies=Array(W*H).fill(0),explored=Array(W*H).fill(0),stack=[START],trace=[];walls[START]=0;
    while(stack.length){const cell=stack[stack.length-1],choices=[];
      for(let d=0;d<4;d++){const n=next(cell,d,2);if(n>=0&&n%W>0&&n%W<W-1&&Math.floor(n/W)>0&&Math.floor(n/W)<H-1&&walls[n])choices.push(n);}
      if(choices.length){const n=choices[rng.int(0,choices.length-1)],mid=(cell+n)/2;walls[n]=walls[mid]=0;stack.push(n);if(withTrace)trace.push({kind:'carve',cells:[mid,n],stack:stack.slice()});}
      else {stack.pop();if(withTrace)trace.push({kind:'backtrack',cells:[],stack:stack.slice()});}
    }
    const treeWalls=walls.slice();
    for(let i=0;i<46;i++){const y=rng.int(1,15),cell=rng.int(1,19)+W*y;const horizontal=!walls[cell-1]&&!walls[cell+1],vertical=!walls[cell-W]&&!walls[cell+W];if(walls[cell]&&(horizontal||vertical))walls[cell]=0;}
    for(let i=0;i<12;i++){const offset=rng.int(0,W*H-1);for(let j=0;j<W*H;j++){const cell=(j+offset)%(W*H);if(!walls[cell]&&!supplies[cell]&&cell!==EXIT&&distance(cell,START)>=5){supplies[cell]=1;break;}}}
    for(let i=0;i<W*H;i++)if(distance(i,START)<=2)explored[i]=1;
    return {seed,width:W,height:H,start:START,exit:EXIT,walls,supplies,explored,treeWalls,trace};
  }
  function radius(elapsed){return elapsed>=150?3:elapsed>=90?4:6;}
  function visibility(state,cell,controller){return state.explored[cell]?'known':controller&&distance(cell,state.player)<=radius(state.elapsed)?'preview':'unknown';}
  function edit(state,cell,eraseOnly=false){
    const reject=reason=>({accepted:false,reason,visited:0,path:[]});
    if(state.state!==1)return reject('对局未进行');
    if(cell<0||cell>=W*H)return reject('索引越界');
    if(state.cooldown>0)return reject('冷却中，点击“推进 3 秒”后再试');
    if(cell%W===0||cell%W===W-1||Math.floor(cell/W)===0||Math.floor(cell/W)===H-1)return reject('边界墙受保护');
    if(visibility(state,cell,true)==='unknown')return reject('黑色盲区禁止编辑');
    if(cell===START||cell===EXIT||distance(cell,state.player)<=1||state.supplies[cell])return reject('起终点、补给或玩家周围一格受保护');
    const old=state.walls[cell];if(eraseOnly&&!old)return reject('这里已经是通路');
    if(state.elapsed>=180&&!old)return reject('180 秒后只允许拆墙');
    state.walls[cell]=1-old;
    const search=bfs(state.walls,state.player);
    if(!search.path.length){state.walls[cell]=old;return {accepted:false,reason:'BFS 未找到出口通路，已回滚，未扣冷却',...search};}
    state.cooldown=state.elapsed>=120?5:2.8;state.edits++;
    return {accepted:true,reason:old?'拆墙成功，通路合法':'建墙成功，通路合法',...search};
  }
  const api={W,H,START,EXIT,Stream,next,distance,bfs,generate,radius,visibility,edit};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.FogStudy=api;
})(typeof globalThis!=='undefined'?globalThis:this);
