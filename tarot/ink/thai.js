/* Nocturne Thai motifs — ลายรดน้ำ (gold leaf on black lacquer), drawn in code.
   กนกเปลว (flame), ก้านขด (scroll), ประจำยาม (4-petal flower), โบสถ์ + เจดีย์ silhouettes.
   Pure canvas functions: ThaiArt.<fn>(ctx, ...). No sacred yantra script is used anywhere. */
(function(){
const GOLD=['#f3dc9a','#d7b25e','#a8823a'];
function goldFill(g,x,y,r){const gr=g.createLinearGradient(x-r,y-r,x+r,y+r);gr.addColorStop(0,GOLD[0]);gr.addColorStop(.5,GOLD[1]);gr.addColorStop(1,GOLD[2]);return gr}
function mulberry(a){return function(){a|=0;a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296}}

/* กนกเปลว: flame leaf with a hooked tip; base at (0,0) pointing up (-y), length L, width w. dir=±1 mirrors the hook */
function flame(g,x,y,L,w,ang=0,dir=1,alpha=1,lacquer='#0b0809'){
 g.save();g.translate(x,y);g.rotate(ang);g.scale(dir,1);g.globalAlpha*=alpha;
 g.beginPath();g.moveTo(0,0);
 g.bezierCurveTo(w*.95,-L*.12,w*.9,-L*.55,w*.25,-L*.82);
 g.bezierCurveTo(w*.05,-L*.93,-w*.1,-L*1.02,-w*.42,-L*.98);   // tip hooks back
 g.bezierCurveTo(-w*.22,-L*.9,-w*.12,-L*.84,-w*.2,-L*.74);
 g.bezierCurveTo(-w*.55,-L*.55,-w*.62,-L*.2,0,0);g.closePath();
 g.fillStyle=goldFill(g,0,-L/2,L/2);g.fill();
 /* lacquer lines scratched into the gold = the ลายรดน้ำ look */
 g.strokeStyle=lacquer;g.lineWidth=Math.max(.8,w*.07);g.lineCap='round';
 g.beginPath();g.moveTo(w*.05,-L*.08);g.bezierCurveTo(w*.35,-L*.3,w*.3,-L*.55,w*.05,-L*.72);g.stroke();
 g.beginPath();g.moveTo(-w*.1,-L*.12);g.bezierCurveTo(-w*.3,-L*.3,-w*.28,-L*.5,-w*.12,-L*.62);g.stroke();
 g.restore()}
/* กนกสามตัว: one tall flame flanked by two small ones leaning out */
function kanok3(g,x,y,L,ang=0,alpha=1){flame(g,x,y,L*.62,L*.24,ang-.55,-1,alpha);flame(g,x,y,L*.62,L*.24,ang+.55,1,alpha);flame(g,x,y,L,L*.34,ang,1,alpha)}
/* ก้านขด: a spiral stem with flames sprouting outward */
function scroll(g,x,y,R,turns=1.6,dir=1,ang=0,alpha=1,seed=1){const r=mulberry(seed);g.save();g.translate(x,y);g.rotate(ang);g.scale(dir,1);g.globalAlpha*=alpha;
 const pts=[];const N=90;for(let i=0;i<=N;i++){const t=i/N,a=t*turns*Math.PI*2,rr=R*(1-t*.82);pts.push([Math.cos(a)*rr,Math.sin(a)*rr,a,rr])}
 g.strokeStyle=GOLD[1];g.lineWidth=Math.max(1.2,R*.045);g.lineCap='round';g.beginPath();pts.forEach(([px,py],i)=>i?g.lineTo(px,py):g.moveTo(px,py));g.stroke();
 for(let i=6;i<N-4;i+=9){const [px,py,a,rr]=pts[i];const L=rr*.42+R*.05;flame(g,px,py,L,L*.34,a+Math.PI*.5+ (r()-.5)*.2,1,1)}
 /* the spiral ends in a curl bud */
 const [ex,ey]=pts[N];g.fillStyle=GOLD[0];g.beginPath();g.arc(ex,ey,R*.06,0,7);g.fill();g.restore()}
/* ประจำยาม: 4 pointed petals + 4 small diagonals + centre, in a diamond */
function prachayam(g,x,y,s,alpha=1,frame=true){g.save();g.translate(x,y);g.globalAlpha*=alpha;const fg=goldFill(g,0,0,s);
 for(let k=0;k<4;k++){g.save();g.rotate(k*Math.PI/2);g.beginPath();g.moveTo(0,-s*.18);g.bezierCurveTo(s*.3,-s*.35,s*.18,-s*.75,0,-s*.92);g.bezierCurveTo(-s*.18,-s*.75,-s*.3,-s*.35,0,-s*.18);g.fillStyle=fg;g.fill();
  g.rotate(Math.PI/4);g.beginPath();g.moveTo(0,-s*.2);g.quadraticCurveTo(s*.14,-s*.4,0,-s*.55);g.quadraticCurveTo(-s*.14,-s*.4,0,-s*.2);g.fill();g.restore()}
 g.beginPath();g.arc(0,0,s*.2,0,7);g.fillStyle=GOLD[0];g.fill();g.beginPath();g.arc(0,0,s*.1,0,7);g.fillStyle='#0b0809';g.fill();
 if(frame){g.strokeStyle=GOLD[1];g.lineWidth=Math.max(.8,s*.05);g.beginPath();g.moveTo(0,-s*1.1);g.lineTo(s*1.1,0);g.lineTo(0,s*1.1);g.lineTo(-s*1.1,0);g.closePath();g.stroke()}
 g.restore()}
/* a ring of flames radiating from a circle (halo / ลายรัศมี) */
function flameRing(g,x,y,R,n,L,alpha=1){for(let i=0;i<n;i++){const a=i/n*Math.PI*2;flame(g,x+Math.cos(a)*R,y+Math.sin(a)*R,L,L*.32,a+Math.PI/2,i%2?1:-1,alpha)}}
/* โบสถ์ silhouette (front view): bottom centre (x,y), width W. Steep concave หน้าบัน, stepped ปีกนก skirts with
   upturned หางหงส์ eaves, a tall ช่อฟ้า at the apex and ใบระกา teeth down the gable. */
function ubosot(g,x,y,W,fill='#050405',line='rgba(215,178,94,.6)'){g.save();g.translate(x,y);g.lineJoin='round';
 const plat=W*.05,wall=W*.17,wt=-(plat+wall),H=W*.9;
 const shape=f=>{g.beginPath();f();g.closePath();g.fillStyle=fill;g.fill();g.strokeStyle=line;g.lineWidth=Math.max(1,W*.004);g.stroke()};
 /* platform + walls */
 shape(()=>{g.moveTo(-W*.5,0);g.lineTo(W*.5,0);g.lineTo(W*.46,-plat);g.lineTo(-W*.46,-plat)});
 shape(()=>{g.moveTo(-W*.3,-plat);g.lineTo(W*.3,-plat);g.lineTo(W*.3,wt);g.lineTo(-W*.3,wt)});
 g.strokeStyle=line;g.lineWidth=Math.max(1,W*.003);[-.22,-.11,.11,.22].forEach(k=>{g.beginPath();g.moveTo(W*k,-plat);g.lineTo(W*k,wt);g.stroke()});
 /* two tiers of skirts each side, lowest widest; eave tips flick up */
 [[.5,.02,.2],[.42,.13,.16]].forEach(([half,lift,rise])=>{const yb=wt-H*lift,yt=yb-H*rise;
  for(const d of [-1,1])shape(()=>{g.moveTo(d*W*.16,yt);g.quadraticCurveTo(d*W*(half*.62),yt+H*rise*.55,d*W*half,yb);
   g.quadraticCurveTo(d*W*(half+.035),yb-H*.025,d*W*(half+.05),yb-H*.07);g.quadraticCurveTo(d*W*(half+.01),yb-H*.01,d*W*(half-.03),yb+H*.012);g.lineTo(d*W*.16,yb+H*.012)})});
 /* main gable: concave sides meeting at a high apex */
 const gb=wt-H*.12,ap=gb-H*.62,gw=W*.24;
 shape(()=>{g.moveTo(-gw,gb);g.quadraticCurveTo(-W*.05,gb-H*.16,0,ap);g.quadraticCurveTo(W*.05,gb-H*.16,gw,gb)});
 /* gold หน้าบัน outline inside the gable */
 g.strokeStyle=line;g.beginPath();g.moveTo(-gw*.72,gb-H*.02);g.quadraticCurveTo(-W*.035,gb-H*.15,0,ap+H*.1);g.quadraticCurveTo(W*.035,gb-H*.15,gw*.72,gb-H*.02);g.closePath();g.stroke();
 /* ใบระกา teeth along both gable edges */
 for(const d of [-1,1])for(let i=1;i<9;i++){const t=i/9;const px=d*(gw*(1-t)*(1-t)+W*.05*2*t*(1-t)*0),py=gb+(ap-gb)*t;const qx=d*(gw*Math.pow(1-t,1.6));
  shape(()=>{g.moveTo(qx,py);g.lineTo(qx+d*W*.028,py-H*.012);g.lineTo(qx+d*W*.006,py+H*.022)})}
 /* ช่อฟ้า: slender hook rising from the apex; หางหงส์ at the gable feet */
 shape(()=>{g.moveTo(-W*.008,ap+H*.03);g.quadraticCurveTo(-W*.01,ap-H*.08,W*.03,ap-H*.13);g.quadraticCurveTo(W*.045,ap-H*.1,W*.03,ap-H*.085);g.quadraticCurveTo(W*.008,ap-H*.06,W*.01,ap+H*.03)});
 for(const d of [-1,1])shape(()=>{g.moveTo(d*gw,gb);g.quadraticCurveTo(d*(gw+W*.03),gb-H*.02,d*(gw+W*.035),gb-H*.08);g.quadraticCurveTo(d*(gw+W*.01),gb-H*.03,d*(gw-W*.02),gb+H*.01)});
 /* door + windows glow */
 g.fillStyle='rgba(243,200,120,.22)';g.fillRect(-W*.04,-plat-wall*.82,W*.08,wall*.82);[-.165,.165].forEach(k=>g.fillRect(W*k-W*.022,-plat-wall*.7,W*.044,wall*.38));
 g.restore()}
/* เจดีย์ทรงระฆัง */
function chedi(g,x,y,H,fill='#050405',line='rgba(215,178,94,.55)'){const W=H*.42;g.save();g.translate(x,y);g.beginPath();
 g.moveTo(-W*.5,0);g.lineTo(W*.5,0);g.lineTo(W*.42,-H*.06);g.lineTo(W*.34,-H*.1);g.lineTo(W*.36,-H*.16);
 g.bezierCurveTo(W*.36,-H*.34,W*.2,-H*.44,W*.1,-H*.46);g.lineTo(W*.12,-H*.5);g.lineTo(W*.06,-H*.52);
 for(let i=0;i<6;i++){g.lineTo(W*(.055-i*.006),-H*(.56+i*.05));g.lineTo(W*(.045-i*.006),-H*(.58+i*.05))}
 g.lineTo(0,-H);
 for(let i=5;i>=0;i--){g.lineTo(-W*(.045-i*.006),-H*(.58+i*.05));g.lineTo(-W*(.055-i*.006),-H*(.56+i*.05))}
 g.lineTo(-W*.06,-H*.52);g.lineTo(-W*.12,-H*.5);g.lineTo(-W*.1,-H*.46);g.bezierCurveTo(-W*.2,-H*.44,-W*.36,-H*.34,-W*.36,-H*.16);
 g.lineTo(-W*.34,-H*.1);g.lineTo(-W*.42,-H*.06);g.closePath();g.fillStyle=fill;g.fill();g.strokeStyle=line;g.lineWidth=1.2;g.stroke();g.restore()}
/* lacquer ground: warm black with faint grain */
function lacquer(g,W,H,cx,cy,seed=3){const gr=g.createRadialGradient(cx,cy,0,cx,cy,Math.hypot(W,H)*.7);gr.addColorStop(0,'#241826');gr.addColorStop(.45,'#120c12');gr.addColorStop(1,'#060405');g.fillStyle=gr;g.fillRect(0,0,W,H);
 const r=mulberry(seed);g.save();g.globalAlpha=.05;g.strokeStyle='#caa46a';g.lineWidth=.6;for(let i=0;i<W*H/9000;i++){const x=r()*W,y=r()*H;g.beginPath();g.moveTo(x,y);g.lineTo(x+(r()-.5)*30,y+(r()-.5)*4);g.stroke()}g.restore()}
/* thin double gold frame with ประจำยาม in the corners */
function frame(g,W,H,m,s=10,alpha=.8){g.save();g.globalAlpha*=alpha;g.strokeStyle=GOLD[1];g.lineWidth=1.2;g.strokeRect(m,m,W-2*m,H-2*m);g.globalAlpha*=.6;g.strokeRect(m+5,m+5,W-2*m-10,H-2*m-10);g.restore();
 [[m,m],[W-m,m],[m,H-m],[W-m,H-m]].forEach(([x,y])=>prachayam(g,x,y,s,alpha))}
/* chain of ประจำยาม along a line */
function chain(g,x0,y0,x1,y1,s,gap,alpha=1){const L=Math.hypot(x1-x0,y1-y0),n=Math.max(1,Math.floor(L/gap));for(let i=0;i<=n;i++){const t=i/n;prachayam(g,x0+(x1-x0)*t,y0+(y1-y0)*t,s,alpha,false)}}
window.ThaiArt={GOLD,goldFill,flame,kanok3,scroll,prachayam,flameRing,ubosot,chedi,lacquer,frame,chain,mulberry};
})();
