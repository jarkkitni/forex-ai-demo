/* Nocturne ink deck engine — brush-ink tarot faces drawn in code (brush engine from the brush-ink-film skill).
   Shared by ink/cards.html (static export) and the app (live brush reveal). Needs CARDS (cards.js).
   InkDeck.record(i) → {final, strokes}: the finished face plus every brush stroke in drawing order,
   so the app can replay the strokes and then fade in the washes, seal and title. */
(function(){
/* Nocturne ink deck — brush-ink tarot faces drawn in code (brush engine from the brush-ink-film skill).
   Pure function of card key + seed: renderCard(key) → canvas. Run render_cards.js to export webp. */
const W=600,H=1034;
const C={paper:'#ebe2cc',ink:'#16130f',red:'#b8321f',gold:'#b98f34',wash:'#3a352f'};
function mulberry(a){return function(){a|=0;a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296}}
const clamp=(x,a=0,b=1)=>Math.max(a,Math.min(b,x));
const lerp=(a,b,x)=>a+(b-a)*x;
function hash(n){const s=Math.sin(n*127.1+311.7)*43758.5453;return s-Math.floor(s)}
function vnoise(x,seed){const i=Math.floor(x),f=x-i,u=f*f*(3-2*f);return lerp(hash(i+seed*57.13),hash(i+1+seed*57.13),u)}
/* ---------- brush engine (from brush-ink-film) ---------- */
function sampleCR(ctrl,step){const out=[],P=[ctrl[0],...ctrl,ctrl[ctrl.length-1]];
 for(let i=1;i<P.length-2;i++){const p0=P[i-1],p1=P[i],p2=P[i+1],p3=P[i+2];const n=Math.max(2,Math.ceil(Math.hypot(p2[0]-p1[0],p2[1]-p1[1])/step));
  for(let j=0;j<n;j++){const t=j/n,t2=t*t,t3=t2*t;const f=(a,b,c,d)=>0.5*(2*b+(-a+c)*t+(2*a-5*b+4*c-d)*t2+(-a+3*b-3*c+d)*t3);out.push([f(p0[0],p1[0],p2[0],p3[0]),f(p0[1],p1[1],p2[1],p3[1])])}}
 out.push(ctrl[ctrl.length-1]);return out}
function makeStroke(ctrl,w,o={}){const seed=o.seed??((ctrl[0][0]*7+ctrl[0][1]*3+ctrl.length*101)|0);
 const pts=sampleCR(ctrl,o.step||3),N=pts.length,head=o.head??0.1,tail=o.tail??0.35,res=[];
 for(let i=0;i<N;i++){const a=pts[Math.max(0,i-1)],b=pts[Math.min(N-1,i+1)];let dx=b[0]-a[0],dy=b[1]-a[1];const L=Math.hypot(dx,dy)||1;dx/=L;dy/=L;
  const s=N>1?i/(N-1):0;let prof=Math.pow(Math.min(1,s/head),0.5)*Math.pow(Math.min(1,(1-s)/tail),0.8);
  prof=Math.max(prof,0.1)*(1+0.18*Math.exp(-Math.pow((s-0.06)/0.05,2)));prof*=0.84+0.32*vnoise(s*7,seed%997);
  res.push({x:pts[i][0],y:pts[i][1],nx:-dy,ny:dx,w:w*prof,s})}
 return {p:res,seed,w,dry:o.dry??0.55,n:o.bristles??Math.max(5,Math.min(18,Math.round(w/3)))}}
function edgePoly(ctx,P,k,sc){ctx.beginPath();for(let i=0;i<k;i++){const q=P[i];ctx.lineTo(q.x+q.nx*q.w*.5*sc,q.y+q.ny*q.w*.5*sc)}for(let i=k-1;i>=0;i--){const q=P[i];ctx.lineTo(q.x-q.nx*q.w*.5*sc,q.y-q.ny*q.w*.5*sc)}ctx.closePath()}
function drawStroke(ctx,S,p,col=C.ink,alpha=1){p=clamp(p);if(p<=0||alpha<=0)return;const P=S.p,k=Math.max(2,Math.min(P.length,Math.ceil(P.length*p)));
 ctx.save();ctx.fillStyle=col;ctx.strokeStyle=col;ctx.lineCap='round';ctx.lineJoin='round';
 ctx.globalAlpha=alpha*0.09;edgePoly(ctx,P,k,1.28);ctx.fill();ctx.globalAlpha=alpha*0.8;edgePoly(ctx,P,k,0.72);ctx.fill();
 const n=S.n;for(let b=0;b<n;b++){const o=-1+2*(b+0.5)/n,r=mulberry(S.seed*31+b)();ctx.lineWidth=Math.max(0.9,S.w/n*1.35*(0.6+r*0.8));ctx.globalAlpha=alpha*(0.5+0.45*r);
  ctx.beginPath();let pen=false;for(let i=0;i<k;i++){const q=P[i],dry=S.dry*(Math.pow(Math.abs(o),1.5)*0.75+q.s*q.s*0.85);
   if(vnoise(i*0.085+b*17.3,S.seed%991)>dry){const x=q.x+q.nx*o*q.w*.5,y=q.y+q.ny*o*q.w*.5;if(pen)ctx.lineTo(x,y);else{ctx.moveTo(x,y);pen=true}}else pen=false}ctx.stroke()}
 ctx.restore()}

/* ---------- drawing vocabulary ---------- */
let X,R,SEED=1,REC=null,PHASE=0;               // current ctx, rng, stroke-seed counter
const sd=()=>(SEED=(SEED*48271+13)%2147483647);
function st(pts,w,o={},col=C.ink,a=1){const S=makeStroke(pts,w,{seed:sd(),...o});if(REC)REC.push({S,col,a,clip:PHASE});drawStroke(X,S,1,col,a)}
function wash(x,y,rx,ry,col='22,19,15',a=.25){X.save();X.translate(x,y);X.scale(1,ry/rx);const g=X.createRadialGradient(0,0,0,0,0,rx);g.addColorStop(0,`rgba(${col},${a})`);g.addColorStop(.6,`rgba(${col},${a*.45})`);g.addColorStop(1,`rgba(${col},0)`);X.fillStyle=g;X.beginPath();X.arc(0,0,rx,0,7);X.fill();X.restore()}
function arcPts(cx,cy,rx,ry,a0,a1,n=14,jit=0){const p=[];for(let i=0;i<=n;i++){const a=lerp(a0,a1,i/n),j=1+(R()-.5)*jit;p.push([cx+Math.cos(a)*rx*j,cy+Math.sin(a)*ry*j])}return p}
function enso(cx,cy,r,w=14,col=C.ink,a=1,start){const s=start??(-1.9+R()*.4);st(arcPts(cx,cy,r,r,s,s+Math.PI*2*(0.86+R()*.06),22,.03),w,{head:.04,tail:.3,dry:.7},col,a)}
function ring(cx,cy,r,w=6,col=C.ink,a=1){st(arcPts(cx,cy,r,r,-1.6,-1.6+Math.PI*2.02,26,.01),w,{head:.02,tail:.08,dry:.4},col,a)}
function disc(cx,cy,r,col='184,50,31',a=.85){X.save();X.globalCompositeOperation='multiply';X.fillStyle=`rgba(${col},${a})`;X.beginPath();for(let i=0;i<=40;i++){const t=i/40*6.2832,rr=r*(1+(vnoise(i*.7,cx)-.5)*.06);X.lineTo(cx+Math.cos(t)*rr,cy+Math.sin(t)*rr)}X.fill();X.restore();wash(cx,cy,r*1.8,r*1.8,col,.12)}
function sun(cx,cy,r,rays=0){disc(cx,cy,r);for(let i=0;i<rays;i++){const a=i/rays*6.2832+R()*.1;st([[cx+Math.cos(a)*r*1.25,cy+Math.sin(a)*r*1.25],[cx+Math.cos(a)*r*(1.7+R()*.3),cy+Math.sin(a)*r*(1.7+R()*.3)]],5+R()*3,{head:.05,tail:.6},C.red,.8)}}
function moon(cx,cy,r,col=C.ink){st(arcPts(cx,cy,r,r,-2.2,1.9,16),r*.5,{head:.25,tail:.4,dry:.45},col,.9);wash(cx,cy,r*2.2,r*2.2,'80,80,90',.08)}
function spark(x,y,r,col=C.gold,a=1){st([[x,y-r],[x,y+r]],r*.35,{head:.4,tail:.4,dry:.2},col,a);st([[x-r,y],[x+r,y]],r*.35,{head:.4,tail:.4,dry:.2},col,a)}
function star8(x,y,r,col=C.gold){for(let i=0;i<4;i++){const a=i*Math.PI/4;const L=i%2?r*.65:r;st([[x-Math.cos(a)*L,y-Math.sin(a)*L],[x+Math.cos(a)*L,y+Math.sin(a)*L]],r*.22,{head:.45,tail:.45,dry:.2},col,.95)}wash(x,y,r*1.6,r*1.6,'185,143,52',.18)}
function ripples(y,x0,x1,n=4,gap=16,a=.7){for(let i=0;i<n;i++){const yy=y+i*gap,ind=(R()*.2)*(x1-x0);st([[x0+ind,yy],[lerp(x0,x1,.5),yy+(R()-.5)*4],[x1-ind*.5,yy]],3+R()*2,{head:.2,tail:.4,dry:.8},C.ink,a*(1-i*.15))}}
function hills(base,amp,seed,a=.28,blur=3,x0=40,x1=560){X.save();X.filter=`blur(${blur}px)`;X.beginPath();X.moveTo(x0,base+60);for(let x=x0;x<=x1;x+=6)X.lineTo(x,base-amp*(Math.pow(vnoise(x/120,seed),1.6)*.85+vnoise(x/30,seed+1)*.15));X.lineTo(x1,base+60);X.closePath();const g=X.createLinearGradient(0,base-amp,0,base+60);g.addColorStop(0,`rgba(22,19,15,${a})`);g.addColorStop(1,'rgba(22,19,15,0)');X.fillStyle=g;X.fill();X.restore()}
function ground(y,x0=70,x1=530,w=6){st([[x0,y+(R()-.5)*6],[lerp(x0,x1,.5),y],[x1,y+(R()-.5)*6]],w,{head:.05,tail:.5,dry:.9})}
function cloud(x,y,s,a=.7){st(arcPts(x,y,s,s*.55,Math.PI,Math.PI*2.1,10),s*.18,{head:.1,tail:.5,dry:.7},C.ink,a);st(arcPts(x+s*.9,y+s*.1,s*.7,s*.45,Math.PI*1.05,Math.PI*2.05,8),s*.15,{tail:.6,dry:.7},C.ink,a*.9)}
/* robed figure (sumi-e): feet at (x,y), height h */
function figure(x,y,h,o={}){const pose=o.pose||'stand',d=o.dir||1,col=o.col||C.ink,sit=o.sit,lean=(o.lean||0)*h;
 const hr=h*.068,hy=y-h+hr*1.1,ny=y-h*.8,hem=sit?y-h*.3:y;
 /* robe silhouette: soft ink fill + dry contour */
 const L=[x-h*.1,ny+h*.02],Rt=[x+h*.1,ny+h*.02],hr2=[x+d*h*.05+lean+h*.21,hem],hl=[x+d*h*.05+lean-h*.2,hem];
 X.save();const g=X.createLinearGradient(0,ny,0,hem);g.addColorStop(0,'rgba(22,19,15,.9)');g.addColorStop(1,'rgba(22,19,15,.5)');X.fillStyle=g;X.beginPath();X.moveTo(L[0],L[1]);
 X.quadraticCurveTo(x-h*.03,ny-h*.05,Rt[0],Rt[1]);X.quadraticCurveTo(x+h*.16+lean*.5,lerp(ny,hem,.55),hr2[0],hr2[1]);X.quadraticCurveTo(x+lean,hem+h*.03,hl[0],hl[1]);X.quadraticCurveTo(x-h*.15+lean*.5,lerp(ny,hem,.55),L[0],L[1]);X.fill();X.restore();
 st([Rt,[x+h*.16+lean*.5,lerp(ny,hem,.55)],hr2],h*.035,{head:.05,tail:.4,dry:.8},col,.9);st([L,[x-h*.15+lean*.5,lerp(ny,hem,.55)],hl],h*.03,{head:.05,tail:.4,dry:.85},col,.8);
 st([[x+d*h*.02,ny+h*.1],[x+d*h*.05+lean*.4,lerp(ny,hem,.6)]],h*.02,{head:.2,tail:.5,dry:.4},C.paper,.5);
 if(o.sash!==false)st([[x-h*.1,lerp(ny,hem,.34)],[x+h*.11,lerp(ny,hem,.32)]],h*.03,{head:.1,tail:.3,dry:.3},o.sashCol||C.red,.8);
 if(sit){X.save();X.fillStyle='rgba(22,19,15,.5)';X.beginPath();X.moveTo(x-h*.2,hem);X.quadraticCurveTo(x+d*h*.12,hem-h*.08,x+d*h*.32,hem+h*.02);X.lineTo(x+d*h*.3,y);X.lineTo(x-h*.22,y);X.closePath();X.fill();X.restore();st([[x-h*.22,y],[x+d*h*.32,y]],h*.035,{head:.05,tail:.3,dry:.7},col,.9)}
 /* head + topknot */
 X.save();X.fillStyle='rgba(22,19,15,.92)';X.beginPath();X.arc(x,hy,hr,0,7);X.fill();X.beginPath();X.arc(x-d*hr*.2,hy-hr*1.15,hr*.45,0,7);X.fill();X.restore();
 const sh=[x+d*h*.06,ny+h*.06],arm=(tx,ty)=>{st([sh,[lerp(sh[0],tx,.5)+d*h*.03,lerp(sh[1],ty,.5)],[tx,ty]],h*.075,{head:.1,tail:.25,dry:.6},col,.95);X.save();X.fillStyle='rgba(22,19,15,.9)';X.beginPath();X.arc(tx,ty,h*.022,0,7);X.fill();X.restore()};
 const sh2=[x-d*h*.07,ny+h*.06],arm2=(tx,ty)=>st([sh2,[lerp(sh2[0],tx,.5)-d*h*.02,lerp(sh2[1],ty,.5)],[tx,ty]],h*.07,{head:.1,tail:.25,dry:.6},col,.9);
 let hand;
 if(pose==='raise'){arm(x+d*h*.2,ny-h*.26);hand=[x+d*h*.2,ny-h*.26]}
 else if(pose==='both'){arm(x+h*.22,ny-h*.24);arm2(x-h*.22,ny-h*.24);hand=[x+h*.22,ny-h*.24]}
 else if(pose==='out'){arm(x+d*h*.32,ny+h*.1);hand=[x+d*h*.32,ny+h*.1]}
 else if(pose==='pour'){arm(x+d*h*.28,ny+h*.02);arm2(x-d*h*.24,ny+h*.1);hand=[x+d*h*.28,ny+h*.02]}
 else if(pose==='wai'){arm(x+d*h*.05,ny+h*.02);hand=[x,ny]}
 else{arm(x+d*h*.1,ny+h*.34);hand=[x+d*h*.1,ny+h*.34]}
 return {head:[x,hy],hand}}
function crown(x,y,s,col=C.gold){st([[x-s,y],[x+s,y]],s*.3,{head:.2,tail:.2,dry:.3},col);for(let i=-2;i<=2;i++)st([[x+i*s*.4,y],[x+i*s*.32,y-s*(1.1-Math.abs(i)*.25)]],s*.18,{head:.1,tail:.6},col);spark(x,y-s*1.35,s*.3,col)}
function chada(x,y,s,col=C.gold){for(let i=0;i<4;i++){const w=s*(1-i*.2),yy=y-i*s*.38;st([[x-w,yy],[x+w,yy]],s*.22,{head:.2,tail:.2,dry:.3},col)}st([[x,y-s*1.2],[x,y-s*2.2]],s*.18,{head:.1,tail:.7},col);spark(x,y-s*2.3,s*.25,col)}
function bamboo(x,y0,y1,w=12,leaf=true){const n=Math.max(3,Math.round((y0-y1)/70));for(let i=0;i<n;i++){const a=lerp(y0,y1,i/n)-3,b=lerp(y0,y1,(i+1)/n)+3,dx=(R()-.5)*3;st([[x,a],[x+dx,b]],w,{head:.05,tail:.08,dry:.45});st([[x-w*.7,b+2],[x+w*.7,b+3]],w*.35,{head:.2,tail:.2},C.ink,.9)}
 if(leaf)for(let i=0;i<3;i++){const yy=lerp(y0,y1,.35+i*.22),d=i%2?1:-1;st([[x,yy],[x+d*w*2.4,yy-w*.9],[x+d*w*4.2,yy-w*.3]],w*.55,{head:.05,tail:.7,dry:.3})}}
function cup(x,y,s,col=C.ink){st(arcPts(x,y-s*.35,s*.62,s*.5,.1,Math.PI-.1,10),s*.16,{head:.1,tail:.3,dry:.5},col);st([[x-s*.64,y-s*.4],[x+s*.64,y-s*.38]],s*.08,{head:.05,tail:.2},col,.9);st([[x,y+s*.12],[x,y+s*.36]],s*.1,{head:.1,tail:.2},col);st([[x-s*.3,y+s*.4],[x+s*.3,y+s*.4]],s*.1,{head:.1,tail:.3},col);wash(x,y-s*.35,s*.5,s*.18,'185,143,52',.35)}
function sword(x,y,len,ang=-Math.PI/2,s=1,col=C.ink){const c=Math.cos(ang),si=Math.sin(ang),px=-si,py=c;
 st([[x,y],[x+c*len,y+si*len]],10*s,{head:.02,tail:.45,dry:.35},col);st([[x+c*len*.16-px*16*s,y+si*len*.16-py*16*s],[x+c*len*.16+px*16*s,y+si*len*.16+py*16*s]],7*s,{head:.2,tail:.2},col);st([[x,y],[x-c*20*s,y-si*20*s]],9*s,{head:.1,tail:.1},C.red,.9)}
function coin(x,y,r){wash(x,y,r*1.1,r*1.1,'185,143,52',.55);ring(x,y,r,Math.max(3,r*.14),C.ink,.95);const q=r*.26;st([[x-q,y-q],[x+q,y-q],[x+q,y+q],[x-q,y+q],[x-q,y-q-2]],Math.max(2,r*.1),{head:.05,tail:.1,dry:.2})}
function wand(x,y,len,ang=-Math.PI/2+.1,w=11){const c=Math.cos(ang),s=Math.sin(ang);st([[x,y],[x+c*len*.5,y+s*len*.5],[x+c*len,y+s*len]],w,{head:.05,tail:.1,dry:.45});for(let i=1;i<4;i++){const px=x+c*len*i/4,py=y+s*len*i/4;st([[px-s*w*.7,py+c*w*.7],[px+s*w*.7,py-c*w*.7]],w*.35,{head:.2,tail:.2})}
 const tx=x+c*len,ty=y+s*len;st([[tx,ty],[tx+18,ty-14],[tx+34,ty-8]],w*.5,{head:.05,tail:.7},C.ink,.9);spark(tx-4,ty-12,6,C.red)}
function lotus(x,y,s,red=true){for(let i=-2;i<=2;i++){const a=i*.42;st([[x,y],[x+Math.sin(a)*s*.55,y-Math.cos(a)*s*.5],[x+Math.sin(a)*s*.9,y-Math.cos(a)*s*1.05]],s*.22,{head:.3,tail:.45,dry:.3},C.ink,.85);if(red)st([[x+Math.sin(a)*s*.82,y-Math.cos(a)*s*.95],[x+Math.sin(a)*s*.92,y-Math.cos(a)*s*1.08]],s*.12,{head:.3,tail:.4},C.red,.9)}st([[x-s*.9,y+4],[x+s*.9,y+4]],s*.12,{tail:.5})}
function tree(x,y,h,bare=false){st([[x,y],[x-6,y-h*.45],[x+10,y-h*.8],[x+4,y-h]],h*.08,{head:.05,tail:.3,dry:.6});st([[x-4,y-h*.5],[x-h*.3,y-h*.72],[x-h*.42,y-h*.7]],h*.035,{tail:.7});st([[x+8,y-h*.72],[x+h*.34,y-h*.9]],h*.03,{tail:.7});
 if(!bare)for(let i=0;i<14;i++){const lx=x+(R()-.5)*h*.8,ly=y-h*.62-R()*h*.45;st([[lx,ly],[lx+8+R()*6,ly-4-R()*6]],7+R()*6,{head:.4,tail:.5,dry:.2},C.ink,.75)}}
function pillar(x,y0,y1,w,a=1){st([[x,y0],[x,y1]],w,{head:.03,tail:.05,dry:.5},C.ink,a);st([[x-w*.8,y1],[x+w*.8,y1]],w*.5,{head:.1,tail:.1},C.ink,a);st([[x-w*.8,y0],[x+w*.8,y0]],w*.5,{head:.1,tail:.1},C.ink,a)}
function gable(x,y,w){st([[x-w,y],[x,y-w*.55],[x+w,y]],12,{head:.05,tail:.1});st([[x-w*.7,y+20],[x,y-w*.55+26],[x+w*.7,y+20]],8,{head:.05,tail:.1},C.ink,.8);st([[x,y-w*.55],[x-6,y-w*.55-26],[x+10,y-w*.55-36]],7,{tail:.7},C.gold);st([[x-w,y],[x-w-18,y-16]],7,{tail:.6},C.gold);st([[x+w,y],[x+w+18,y-16]],7,{tail:.6},C.gold)}
function bird(x,y,s){st([[x-s,y-s*.3],[x-s*.3,y],[x,y-s*.1]],s*.18,{tail:.5});st([[x,y-s*.1],[x+s*.4,y-s*.1],[x+s,y-s*.5]],s*.18,{tail:.6})}
function chain(x0,y0,x1,y1){for(let i=0;i<=6;i++){const t=i/6;ring(lerp(x0,x1,t),lerp(y0,y1,t),5,2.4,C.ink,.8)}}

/* ---------- card frame + labels ---------- */
let PAPER;
function makePaper(){const c=document.createElement('canvas');c.width=W;c.height=H;const g=c.getContext('2d');g.fillStyle=C.paper;g.fillRect(0,0,W,H);
 const id=g.getImageData(0,0,W,H),d=id.data,r=mulberry(11);for(let i=0;i<d.length;i+=4){const n=(r()-.5)*7;d[i]+=n;d[i+1]+=n;d[i+2]+=n*.8}g.putImageData(id,0,0);
 g.strokeStyle='rgba(90,70,40,0.06)';g.lineWidth=1;for(let i=0;i<260;i++){const x=r()*W,y=r()*H,a=r()*6.28,l=10+r()*40;g.beginPath();g.moveTo(x,y);g.quadraticCurveTo(x+Math.cos(a+.5)*l*.5,y+Math.sin(a+.5)*l*.5,x+Math.cos(a)*l,y+Math.sin(a)*l);g.stroke()}
 const RD=Math.hypot(W/2,H/2),v=g.createRadialGradient(W/2,H/2,RD*.4,W/2,H/2,RD*1.03);v.addColorStop(0,'rgba(60,40,15,0)');v.addColorStop(1,'rgba(60,40,15,0.2)');g.fillStyle=v;g.fillRect(0,0,W,H);return c}
function frame(){const m=26;st([[m,m+4],[W-m,m]],5,{head:.02,tail:.1,dry:.9},C.ink,.85);st([[W-m,m-2],[W-m+2,H-m]],5,{head:.02,tail:.1,dry:.9},C.ink,.85);st([[W-m,H-m],[m,H-m+2]],5,{head:.02,tail:.1,dry:.9},C.ink,.85);st([[m+2,H-m],[m,m]],5,{head:.02,tail:.1,dry:.9},C.ink,.85);
 const k=38;X.save();X.strokeStyle='rgba(185,143,52,.8)';X.lineWidth=1.5;X.strokeRect(k,k,W-2*k,H-2*k);X.restore();
 [[k,k],[W-k,k],[k,H-k],[W-k,H-k]].forEach(([x,y])=>{X.save();X.fillStyle=C.gold;X.translate(x,y);X.rotate(Math.PI/4);X.fillRect(-5,-5,10,10);X.restore()})}
const THD='๐๑๒๓๔๕๖๗๘๙';const thNum=n=>String(n).split('').map(d=>THD[d]).join('');
function seal(x,y,txt,s=1){const w=64*s,h=64*s,r=mulberry(txt.length*31+7);X.save();X.translate(x,y);X.rotate(-.04);X.globalCompositeOperation='multiply';X.fillStyle='rgba(184,50,31,.92)';X.beginPath();
 [[-w/2,-h/2],[w/2,-h/2],[w/2,h/2],[-w/2,h/2]].forEach(([px,py],i,a)=>{const n=a[(i+1)%4];for(let k=0;k<8;k++){const u=k/8;X.lineTo(lerp(px,n[0],u)+(r()-.5)*3,lerp(py,n[1],u)+(r()-.5)*3)}});X.closePath();X.fill();
 X.globalCompositeOperation='source-over';X.fillStyle=C.paper;X.textAlign='center';X.textBaseline='middle';let fs=40*s;X.font=`500 ${fs}px Kanit`;while(X.measureText(txt).width>w*.78&&fs>12){fs-=2;X.font=`500 ${fs}px Kanit`}X.fillText(txt,0,3*s);
 X.strokeStyle=C.paper;X.lineWidth=2;X.strokeRect(-w/2+6*s,-h/2+6*s,w-12*s,h-12*s);X.globalCompositeOperation='destination-out';for(let i=0;i<60;i++){X.globalAlpha=.3+r()*.7;X.beginPath();X.arc((r()-.5)*w,(r()-.5)*h,r()*r()*2.6,0,6.3);X.fill()}X.restore()}
const ROMAN=["0","I","II","III","IV","V","VI","VII","VIII","IX","X","XI","XII","XIII","XIV","XV","XVI","XVII","XVIII","XIX","XX","XXI"];
function labels(card,top){X.save();X.textAlign='center';X.fillStyle=C.ink;X.font='700 30px Cinzel';X.letterSpacing='6px';X.fillText(top,W/2+3,88);X.letterSpacing='0px';
 st([[W/2-40,104],[W/2+40,104]],3,{head:.3,tail:.3,dry:.3},C.gold,.9);
 let fs=64;X.font=`700 ${fs}px Charmonman`;while(X.measureText(card.th).width>440&&fs>34){fs-=2;X.font=`700 ${fs}px Charmonman`}
 X.fillStyle=C.ink;X.fillText(card.th,W/2,H-150);
 X.font='500 20px Cinzel';X.letterSpacing='4px';X.fillStyle=C.red;let en=card.en.toUpperCase();let fe=20;while(X.measureText(en).width>440&&fe>12){fe-=1;X.font=`500 ${fe}px Cinzel`}X.fillText(en,W/2+2,H-108);X.restore()}

/* shared atmosphere: sky wash, far mountains, gold flecks — every face gets depth */
function atmos(idx){const r=mulberry(idx*13+5);wash(300,170,340,140,'58,53,47',.10);hills(700+r()*40,90+r()*60,idx+40,.12,6);
 for(let i=0;i<18;i++){X.save();X.globalAlpha=.25+r()*.4;X.fillStyle=C.gold;X.beginPath();X.arc(60+r()*480,130+r()*600,r()*2.2+.4,0,7);X.fill();X.restore()}}
/* ---------- major arcana scenes (art window ≈ x 60..540, y 130..800) ---------- */
const MAJ=[
()=>{hills(760,150,3);sun(430,250,52,10);st([[70,720],[230,700],[330,690],[400,712]],14,{tail:.2});st([[400,712],[412,800]],10,{tail:.6});figure(300,690,230,{pose:'raise',dir:1});wand(250,560,130,-2.1,8);lotus(360,690,26);bird(150,230,30);bird(200,280,20)},
()=>{st(arcPts(255,230,48,34,0,6.28,18),10,{tail:.1});st(arcPts(345,230,48,34,Math.PI,Math.PI*3,18),10,{tail:.1});figure(300,640,270,{pose:'raise'});st([[110,690],[490,690]],14,{tail:.1});wand(140,680,90,-1.4,7);cup(240,665,46);sword(360,680,90,-1.35,.7);coin(455,650,26);lotus(300,760,34)},
()=>{pillar(150,720,220,26);pillar(450,720,220,14,.55);X.save();X.globalAlpha=.9;X.font='700 30px Cinzel';X.fillStyle=C.paper;X.textAlign='center';X.fillText('B',150,430);X.restore();wash(300,450,150,230,'40,40,70',.12);figure(300,700,260,{sit:true,pose:'wai'});moon(300,740,30,C.ink);st(arcPts(300,330,120,40,Math.PI,Math.PI*2,10),5,{tail:.4},C.gold,.8);spark(300,250,14)},
()=>{hills(690,110,7,.2);sun(440,260,40);figure(300,720,260,{sit:true,pose:'out'});crown(300,500,20);for(let i=0;i<6;i++)star8(210+i*36,470-(i%2)*14,7);for(let i=0;i<7;i++){const x=100+i*60;st([[x,790],[x+8,700]],6,{tail:.6});st([[x+8,700],[x+16,690]],10,{head:.4},C.gold,.9)}lotus(130,720,30)},
()=>{hills(560,220,4,.35,2);st([[170,760],[170,430],[430,430],[430,760]],18,{head:.02,tail:.05});figure(300,740,260,{sit:true,pose:'raise'});chada(300,500,22);st([[160,430],[130,390],[150,360]],10,{tail:.6},C.gold);st([[440,430],[470,390],[450,360]],10,{tail:.6},C.gold);st([[90,780],[510,780]],12)},
()=>{gable(300,330,190);pillar(160,760,380,16);pillar(440,760,380,16);figure(300,720,270,{pose:'raise'});spark(300,410,10,C.gold);figure(200,780,120,{pose:'wai',dir:1});figure(400,780,120,{pose:'wai',dir:-1})},
()=>{sun(300,240,60,14);figure(210,760,260,{pose:'out',dir:1});figure(390,760,260,{pose:'out',dir:-1});tree(110,760,260);st([[300,560],[300,470]],3,{},C.red,.7);wash(300,520,60,60,'184,50,31',.15);st([[90,780],[510,780]],10)},
()=>{star8(300,210,16);st(arcPts(300,420,160,60,Math.PI,Math.PI*2,12),10,{tail:.2});st([[140,420],[140,640],[460,640],[460,420]],14,{tail:.05});figure(300,560,220,{pose:'raise'});enso(170,700,56,12);enso(430,700,56,12);wash(210,760,60,26,'22,19,15',.35);wash(390,760,60,26,'22,19,15',.12);st([[80,780],[520,780]],8)},
()=>{st(arcPts(265,220,40,28,0,6.28,16),8);st(arcPts(335,220,40,28,Math.PI,Math.PI*3,16),8);figure(220,760,280,{pose:'out'});for(let i=0;i<9;i++){const a=-2.6+i*.32;st([[380,560],[380+Math.cos(a)*110,560+Math.sin(a)*110]],16,{head:.1,tail:.7,dry:.7},C.gold,.9)}enso(380,560,60,16);st([[380,620],[430,760]],22,{tail:.4});st([[330,620],[330,760]],14,{tail:.4});lotus(470,770,26)},
()=>{hills(760,300,9,.35,2);figure(270,760,280,{pose:'out'});st([[330,480],[350,780]],7,{tail:.2});wash(390,470,70,70,'185,143,52',.5);star8(390,470,16);st([[380,440],[400,440],[400,500],[380,500],[380,440]],4,{},C.ink,.8);spark(470,200,6,C.ink);spark(140,240,5,C.ink)},
()=>{cloud(130,230,60);cloud(420,720,70);enso(300,470,190,22);ring(300,470,120,6);for(let i=0;i<8;i++){const a=i*Math.PI/4;st([[300+Math.cos(a)*30,470+Math.sin(a)*30],[300+Math.cos(a)*118,470+Math.sin(a)*118]],6,{head:.1,tail:.2})}coin(300,470,26);[[100,160],[500,160],[100,780],[500,780]].forEach(([x,y])=>star8(x,y,12))},
()=>{sun(300,300,110);sword(300,770,560,-Math.PI/2,1.4);st([[150,420],[450,420]],8,{tail:.1});st(arcPts(170,480,60,34,0,Math.PI,10),8);st(arcPts(430,480,60,34,0,Math.PI,10),8);st([[150,420],[170,480]],3,{},C.gold);st([[450,420],[430,480]],3,{},C.gold);st([[80,790],[520,790]],10)},
()=>{st([[160,200],[440,200]],22,{head:.02,tail:.05});st([[430,200],[440,790]],20,{tail:.1});st([[300,200],[300,300]],4);st([[300,300],[280,470]],40,{head:.1,tail:.1});st([[285,330],[230,420],[290,470]],12,{tail:.5});st([[300,330],[350,300],[330,260]],12,{tail:.6});enso(275,520,24,10);wash(275,530,70,70,'185,143,52',.55);for(let i=0;i<12;i++){const a=i/12*6.28;st([[275+Math.cos(a)*38,530+Math.sin(a)*38],[275+Math.cos(a)*58,530+Math.sin(a)*58]],4,{tail:.6},C.gold)}st([[90,790],[520,790]],10)},
()=>{sun(300,560,70);hills(600,40,13,.3,1);pillar(150,600,300,26);pillar(450,600,300,26);ripples(640,100,500,5,20);st([[210,700],[390,700]],9,{tail:.2});st([[230,700],[250,730],[350,730],[370,700]],7,{tail:.2});tree(110,230,150,true);lotus(300,800,40,false)},
()=>{sun(420,230,34,8);figure(300,760,300,{pose:'pour'});cup(240,540,46);cup(400,610,46);st([[250,500],[320,470],[395,560]],7,{head:.2,tail:.3,dry:.3},'#4a6a78',.8);ripples(780,100,500,2,14);st([[420,760],[440,640],[450,600]],5);lotus(470,780,24);lotus(130,780,24)},
()=>{wash(300,450,280,380,'22,19,15',.55);st([[220,300],[180,190],[210,140]],18,{tail:.7});st([[380,300],[420,190],[390,140]],18,{tail:.7});enso(300,330,80,20,C.ink);st([[270,320],[285,320]],8,{},C.red);st([[315,320],[330,320]],8,{},C.red);st([[160,500],[440,500]],14);figure(210,780,190,{pose:'stand',dir:1});figure(390,780,190,{pose:'stand',dir:-1});chain(300,500,215,620);chain(300,500,385,620)},
()=>{hills(800,90,15,.4,1);st([[230,790],[250,300],[350,300],[370,790]],18,{head:.03,tail:.05});crown(300,290,40,C.gold);st([[330,210],[300,210],[380,110]],1,{},C.gold,0);st([[470,120],[380,250],[430,260],[330,420]],10,{head:.05,tail:.4,dry:.2},C.gold);for(let i=0;i<10;i++)st([[180+R()*240,380+R()*200],[180+R()*240,420+R()*260]],4+R()*4,{tail:.7},C.red,.7);figure(150,560,120,{pose:'both'});figure(460,640,110,{pose:'both',dir:-1})},
()=>{star8(300,230,70);[[120,180],[480,170],[150,330],[450,320],[110,440],[490,430],[300,380]].forEach(([x,y])=>star8(x,y,14));figure(300,720,240,{pose:'pour',sit:true});cup(370,610,38);ripples(700,90,510,4,18);tree(480,700,150);bird(470,560,16)},
()=>{moon(300,260,90);wash(300,260,150,150,'80,80,110',.12);pillar(120,760,420,34);pillar(480,760,420,34);st([[300,800],[280,700],[320,600],[300,470]],8,{tail:.8,dry:.8});ripples(780,90,510,3,14);for(let i=0;i<9;i++){const a=R()*6.28;st([[300+Math.cos(a)*120,260+Math.sin(a)*120],[300+Math.cos(a)*170,260+Math.sin(a)*170]],3,{tail:.7},C.gold,.8)}},
()=>{sun(300,300,120,20);for(let i=0;i<5;i++){const x=110+i*95;st([[x,790],[x,640]],6,{tail:.3});enso(x,620,24,8,C.gold);X.fillStyle='rgba(22,19,15,.8)';X.beginPath();X.arc(x,620,9,0,7);X.fill()}figure(300,760,200,{pose:'both'});st([[80,790],[520,790]],10)},
()=>{cloud(240,190,70);cloud(380,170,60);st([[210,230],[300,330],[330,360]],10,{head:.05,tail:.1},C.gold);st(arcPts(340,370,30,20,0,6.28,10),6,{},C.gold);st([[300,330],[290,300]],3,{},C.red,.8);ripples(740,80,520,4,18);figure(170,720,170,{pose:'both'});figure(300,700,200,{pose:'both'});figure(430,720,170,{pose:'both'});for(let i=0;i<6;i++)st([[300,380+i],[160+i*56,560]],2,{},C.gold,.35)},
()=>{wash(300,470,200,290,'185,143,52',.22);const e=arcPts(300,470,170,260,-1.5,4.8,30);st(e,10,{tail:.1},C.ink);for(let i=0;i<24;i++){const p=e[i+2];if(!p)continue;st([[p[0],p[1]],[p[0]+(R()-.5)*20,p[1]-10-R()*10]],8,{head:.4,tail:.5,dry:.2},'#3d5a2e',.85)}figure(300,640,260,{pose:'both'});st(arcPts(300,470,90,160,.4,2.4,12),5,{tail:.5},C.red,.7);[[95,170],[505,170],[95,790],[505,790]].forEach(([x,y],i)=>i%2?coin(x,y,20):star8(x,y,14))}
];

/* ---------- minor arcana ---------- */
const LAY={1:[[300,440]],2:[[200,450],[400,450]],3:[[300,300],[180,560],[420,560]],4:[[190,310],[410,310],[190,590],[410,590]],5:[[180,290],[420,290],[300,450],[180,610],[420,610]],
 6:[[210,300],[390,300],[210,470],[390,470],[210,640],[390,640]],7:[[300,260],[200,390],[400,390],[300,470],[200,560],[400,560],[300,690]],8:[[200,280],[400,280],[200,410],[400,410],[200,540],[400,540],[200,670],[400,670]],
 9:[[180,300],[300,300],[420,300],[180,470],[300,470],[420,470],[180,640],[300,640],[420,640]],10:[[300,240],[190,330],[410,330],[190,450],[410,450],[300,380],[300,520],[190,570],[410,570],[300,680]]};
const SUIT={w:{draw:(x,y,s)=>wand(x-s*.1,y+s*.9,s*1.8,-Math.PI/2+.12,Math.max(9,s*.2)),bg:()=>{hills(790,200,21,.22,3);X.save();X.globalAlpha=.22;bamboo(78,800,300,10,true);bamboo(522,800,360,8,true);X.restore()}},
 c:{draw:(x,y,s)=>cup(x,y+s*.3,s*1.05),bg:()=>{wash(300,720,260,60,'60,90,110',.18);ripples(720,70,530,5,16,.45);lotus(110,760,22);lotus(490,740,18)}},
 s:{draw:(x,y,s)=>sword(x,y+s*.95,s*1.9,-Math.PI/2+.08,Math.max(.7,s/48)),bg:()=>{hills(780,260,55,.3,2);cloud(130,200,56,.45);cloud(440,240,44,.35)}},
 p:{draw:(x,y,s)=>coin(x,y,s*.62),bg:()=>{wash(300,440,260,300,'185,143,52',.14);st([[70,770],[530,770]],8,{tail:.5},C.ink,.6);tree(90,770,170);lotus(500,765,22,false)}}};
const SPECIAL={s03:()=>{X.save();X.globalCompositeOperation='multiply';X.fillStyle='rgba(184,50,31,.85)';X.beginPath();X.moveTo(300,620);X.bezierCurveTo(140,500,190,330,300,420);X.bezierCurveTo(410,330,460,500,300,620);X.fill();X.restore();cloud(140,260,60);ripples(700,120,480,3,14);for(let i=-1;i<=1;i++)sword(300+i*90,700,420,-Math.PI/2+i*.35,1)},
 s10:()=>{sun(300,700,70);hills(720,40,33,.3,1);st([[90,640],[510,640]],40,{head:.02,tail:.1});for(let i=0;i<10;i++)sword(130+i*38,640,300,-Math.PI/2+(i-4.5)*.03,.7)},
 c05:()=>{figure(300,760,300,{pose:'stand'});cup(170,690,50);cup(260,745,40);cup(420,700,50);cup(470,760,40);st([[160,700],[120,760]],8,{},C.red,.6);st([[250,752],[220,790]],8,{},C.red,.6);st([[430,700],[455,660]],1,{},C.ink,0)},
 p05:()=>{st([[160,210],[160,600],[440,600],[440,210]],8,{tail:.1});for(let i=0;i<5;i++)coin(210+(i%3)*90,280+Math.floor(i/3)*110,32);figure(230,790,170,{pose:'stand',dir:1});figure(380,790,150,{pose:'stand',dir:-1});for(let i=0;i<30;i++)spark(80+R()*440,120+R()*680,3,C.ink,.5)},
 c10:()=>{st(arcPts(300,560,230,330,Math.PI+.2,Math.PI*2-.2,20),26,{tail:.3},'#a07a3a',.55);for(let i=0;i<10;i++){const a=Math.PI+.35+i*(Math.PI-.7)/9;cup(300+Math.cos(a)*200,560+Math.sin(a)*290,34)}figure(250,780,160,{pose:'both'});figure(330,780,160,{pose:'both'});figure(410,790,90,{pose:'both'})}};
function court(r,suit){const s=SUIT[suit];X.save();X.globalAlpha=.6;s.bg();X.restore();if(r===11){hills(780,80,r*3+suit.charCodeAt(0),.25);figure(260,760,240,{pose:'raise'});s.draw(370,420,70)}
 else if(r===12){hills(800,70,r*5,.25);st([[120,700],[200,600],[340,590],[450,620]],60,{head:.2,tail:.3,dry:.8});st([[180,650],[150,790]],10);st([[240,640],[250,790]],10);st([[380,640],[360,790]],10);st([[430,630],[470,780]],10);st([[450,610],[500,540],[520,560]],30,{tail:.6});figure(300,600,210,{pose:'out'});s.draw(430,360,62)}
 else{const king=r===14;st([[150,790],[150,480],[450,480],[450,790]],16,{tail:.05},C.ink,.8);figure(300,770,280,{sit:true,pose:'out'});king?chada(300,530,24):crown(300,530,22);s.draw(430,420,70);if(!king)lotus(170,780,30)}}
function minor(card){const suit=card.img[0],rank=card.n,s=SUIT[suit];if(SPECIAL[card.img]){SPECIAL[card.img]();return}
 if(rank>10){court(rank,suit);return}s.bg();const pos=LAY[rank],sz=[0,150,110,95,85,75,70,64,58,56,52][rank];pos.forEach(([x,y])=>s.draw(x,y,sz));
 if(rank===1){wash(300,470,210,210,'185,143,52',.2);enso(300,470,200,16,C.ink,.5)}
 if(rank===9&&suit==='c')lotus(300,780,34);if(rank===6&&suit==='w')figure(300,800,130,{pose:'raise'})}

/* ---------- card back ---------- */
function drawBack(g){X=g;R=mulberry(99);SEED=4242;g.fillStyle='#14112a';g.fillRect(0,0,W,H);
 const gr=g.createRadialGradient(W/2,H*.45,20,W/2,H*.45,H*.7);gr.addColorStop(0,'#2b2560');gr.addColorStop(1,'#07060d');g.fillStyle=gr;g.fillRect(0,0,W,H);
 for(let i=0;i<220;i++){g.globalAlpha=.2+R()*.7;g.fillStyle='#f4ead0';g.beginPath();g.arc(R()*W,R()*H,R()*1.6+.3,0,7);g.fill()}g.globalAlpha=1;
 const m=26;[[[m,m],[W-m,m]],[[W-m,m],[W-m,H-m]],[[W-m,H-m],[m,H-m]],[[m,H-m],[m,m]]].forEach(p=>st(p,5,{head:.02,tail:.1,dry:.9},C.gold,.9));
 g.strokeStyle='rgba(185,143,52,.6)';g.lineWidth=1.5;g.strokeRect(40,40,W-80,H-80);
 enso(W/2,H/2,190,24,C.gold,.95);moon(W/2+10,H/2-10,70,'#efdcaa');star8(W/2+80,H/2-90,16,'#efdcaa');
 for(let i=0;i<8;i++){const a=i/8*6.2832;spark(W/2+Math.cos(a)*250,H/2+Math.sin(a)*250,6,C.gold,.8)}
 g.save();g.textAlign='center';g.fillStyle='#efdcaa';g.font='700 34px Cinzel';g.letterSpacing='14px';g.fillText('NOCTURNE',W/2+7,150);g.font='700 34px Charmonman';g.letterSpacing='0px';g.fillStyle='rgba(239,220,170,.8)';g.fillText('ไพ่ใต้แสงจันทร์',W/2,H-130);g.restore();
 seal(W/2,H-205,'จันทร์',.9)}

/* ---------- render ---------- */
function renderCard(idx){const c=document.createElement('canvas');c.width=W;c.height=H;const g=c.getContext('2d');X=g;
 if(idx==='back'){drawBack(g);return c}
 const card=CARDS[idx];R=mulberry(1000+idx*77);SEED=5000+idx*131;g.drawImage(PAPER,0,0);frame();
 const top=card.img[0]==='m'?ROMAN[card.n]:['','ACE','II','III','IV','V','VI','VII','VIII','IX','X','PAGE','KNIGHT','QUEEN','KING'][card.n];
 const A=document.createElement('canvas');A.width=W;A.height=H;X=A.getContext('2d');
 PHASE=1;X.save();X.beginPath();X.rect(40,112,W-80,700);X.clip();atmos(idx);
 if(card.img[0]==='m')MAJ[card.n]();else minor(card);X.restore();PHASE=0;
 /* fade the art out above the title: mask the layer (a flat paper overlay left a visible band) */
 X.globalCompositeOperation='destination-out';const fg=X.createLinearGradient(0,735,0,815);fg.addColorStop(0,'rgba(0,0,0,0)');fg.addColorStop(1,'rgba(0,0,0,1)');X.fillStyle=fg;X.fillRect(0,735,W,H-735);
 X=g;g.drawImage(A,0,0);
 labels(card,top);seal(W-100,H-100,card.img[0]==='m'?thNum(card.n):({w:'ไม้',c:'ถ้วย',s:'ดาบ',p:'เหรียญ'}[card.img[0]]),.8);return c}
let FONTS_OK=false;
const ready=(async()=>{try{await Promise.all(['700 64px Charmonman','700 30px Cinzel','500 20px Cinzel','500 40px Kanit'].map(f=>document.fonts.load(f,'กขABC๑')))}catch(e){}
 FONTS_OK=['Charmonman','Cinzel','Kanit'].every(f=>document.fonts.check(`20px ${f}`));PAPER=makePaper()})();
function record(idx){REC=[];try{const final=renderCard(idx);return{final,strokes:REC}}finally{REC=null}}
/* replay: draws the strokes one by one onto `canvas`, then cross-fades to the finished face. Returns a promise. */
function play(canvas,idx,dur=2300){const {final,strokes}=record(idx);const g=canvas.getContext('2d');canvas.width=W;canvas.height=H;
 const base=document.createElement('canvas');base.width=W;base.height=H;const b=base.getContext('2d');b.drawImage(PAPER,0,0);
 const wts=strokes.map(s=>Math.sqrt(s.S.p.length)+2),tot=wts.reduce((a,c)=>a+c,0),ink=dur*.82,fade=dur*.18;let acc=0;const t0s=wts.map(w=>{const t=acc;acc+=w/tot*ink;return t});
 const clip=(c)=>{c.beginPath();c.rect(40,112,W-80,700);c.clip()};let done=0;
 const drawS=(c,s,p)=>{c.save();if(s.clip)clip(c);drawStroke(c,s.S,p,s.col,s.a);c.restore()};
 return new Promise(res=>{const start=performance.now();
  function frame(now){const t=now-start;
   while(done<strokes.length&&t>=t0s[done]+wts[done]/tot*ink){drawS(b,strokes[done],1);done++}
   g.globalAlpha=1;g.drawImage(base,0,0);
   if(done<strokes.length){const p=(t-t0s[done])/(wts[done]/tot*ink);if(p>0)drawS(g,strokes[done],p)}
   const k=Math.max(0,Math.min(1,(t-ink)/fade));if(k>0){g.globalAlpha=k;g.drawImage(final,0,0);g.globalAlpha=1}
   if(t<dur)requestAnimationFrame(frame);else{g.drawImage(final,0,0);res()}}
  requestAnimationFrame(frame)})}
window.InkDeck={W,H,ready,get fontsOk(){return FONTS_OK},render:renderCard,record,play};
})();
