// Headless assertions for islandComponents/wallTips logic (pure, no DOM).
// Mirrors the app's wall-lattice rules on a hand-built inside-cell grid.
function mkGrid(N){var cmap={};for(var r=0;r<N;r++)for(var c=0;c<N;c++)cmap[c+','+r]={col:c,row:r,inside:true,walls:{N:true,S:true,E:true,W:true}};return {cmap:cmap,N:N};}
function open(cmap,c,r,dir){var a=cmap[c+','+r];a.walls[dir]=false;var DV={N:[0,-1],S:[0,1],E:[1,0],W:[-1,0]},opp={N:'S',S:'N',E:'W',W:'E'};var b=cmap[(c+DV[dir][0])+','+(r+DV[dir][1])];if(b)b.walls[opp[dir]]=false;}
// ---- functions under test (copy of the app versions; keep in sync) ----
function _wallH(cmap,i,j){var b=cmap[i+','+j],a=cmap[i+','+(j-1)];var bIn=b&&b.inside,aIn=a&&a.inside;if(!bIn&&!aIn)return false;if(bIn&&aIn)return b.walls.N;return true;}
function _wallV(cmap,i,j){var rt=cmap[i+','+j],lf=cmap[(i-1)+','+j];var rIn=rt&&rt.inside,lIn=lf&&lf.inside;if(!rIn&&!lIn)return false;if(rIn&&lIn)return rt.walls.W;return true;}
function _allIn(cmap,i,j){var k=[cmap[(i-1)+','+(j-1)],cmap[i+','+(j-1)],cmap[(i-1)+','+j],cmap[i+','+j]];for(var t=0;t<4;t++)if(!(k[t]&&k[t].inside))return false;return true;}
function _frameVtx(cmap,i,j){var k=[cmap[(i-1)+','+(j-1)],cmap[i+','+(j-1)],cmap[(i-1)+','+j],cmap[i+','+j]],anyIn=false,anyOut=false;for(var t=0;t<4;t++){if(k[t]&&k[t].inside)anyIn=true;else anyOut=true;}return anyIn&&anyOut;}
function _bounds(cmap){var c0=1e9,c1=-1e9,r0=1e9,r1=-1e9;for(var key in cmap){var cl=cmap[key];if(!cl.inside)continue;if(cl.col<c0)c0=cl.col;if(cl.col>c1)c1=cl.col;if(cl.row<r0)r0=cl.row;if(cl.row>r1)r1=cl.row;}return {I0:c0,I1:c1+1,J0:r0,J1:r1+1};}
function islandComponents(cmap,N){var b=_bounds(cmap),I0=b.I0,I1=b.I1,J0=b.J0,J1=b.J1;
  function nbrs(i,j){var a=[];if(_wallH(cmap,i,j))a.push([i+1,j]);if(_wallH(cmap,i-1,j))a.push([i-1,j]);if(_wallV(cmap,i,j))a.push([i,j+1]);if(_wallV(cmap,i,j-1))a.push([i,j-1]);return a;}
  var vid=function(i,j){return i+'_'+j;},comp={},st=[];
  for(var i=I0;i<=I1;i++)for(var j=J0;j<=J1;j++)if(_frameVtx(cmap,i,j))st.push([i,j]);
  while(st.length){var p=st.pop(),id=vid(p[0],p[1]);if(comp[id]!==undefined)continue;comp[id]=-1;var ns=nbrs(p[0],p[1]);for(var k=0;k<ns.length;k++)if(comp[vid(ns[k][0],ns[k][1])]===undefined)st.push(ns[k]);}
  var out=[];
  for(var i=I0;i<=I1;i++)for(var j=J0;j<=J1;j++){if(!_allIn(cmap,i,j)||comp[vid(i,j)]!==undefined)continue;
    var q=[[i,j]],verts=[],edges=[];comp[vid(i,j)]=out.length;
    while(q.length){var p=q.pop();verts.push(p);var cand=[];
      if(_wallH(cmap,p[0],p[1]))cand.push([p[0]+1,p[1]]);if(_wallH(cmap,p[0]-1,p[1]))cand.push([p[0]-1,p[1]]);
      if(_wallV(cmap,p[0],p[1]))cand.push([p[0],p[1]+1]);if(_wallV(cmap,p[0],p[1]-1))cand.push([p[0],p[1]-1]);
      for(var k=0;k<cand.length;k++){var nb=cand[k];edges.push([p,nb]);if(comp[vid(nb[0],nb[1])]===undefined){comp[vid(nb[0],nb[1])]=out.length;q.push(nb);}}}
    out.push({verts:verts,edges:edges});}
  return out;}
function wallTips(cmap){var b=_bounds(cmap),out=[];
  for(var i=b.I0;i<=b.I1;i++)for(var j=b.J0;j<=b.J1;j++){if(!_allIn(cmap,i,j))continue;
    var e=0;if(_wallH(cmap,i,j))e++;if(_wallH(cmap,i-1,j))e++;if(_wallV(cmap,i,j))e++;if(_wallV(cmap,i,j-1))e++;
    if(e===1)out.push([i,j]);}
  return out;}
// ---- cases ----
function run(){
  // Case A: a 2x2 all-open pillar loop in the middle of a 5x5 -> exactly 1 island (1 vertex), 0 tips on it
  var g=mkGrid(5),cmap=g.cmap;
  open(cmap,1,1,'E');open(cmap,1,1,'S');open(cmap,2,1,'S');open(cmap,1,2,'E'); // ring c(1,1)
  // also open a path so the rest is connected-ish (not required for island detection)
  var comps=islandComponents(cmap,5);
  var pillars=comps.filter(function(c){return c.verts.length===1;});
  console.log('CASE A islands:',comps.length,'single-vertex:',pillars.length);
  if(pillars.length<1)throw new Error('expected a single-vertex pillar island');
  console.log('OK');
}
run();
