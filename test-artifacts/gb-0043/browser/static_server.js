// 无依赖静态服务 + /api 代理，复刻 nginx 行为
const http=require('http');const fs=require('fs');const path=require('path');
const ROOT=path.resolve(__dirname,'..','..','..','frontend');const PORT=8022;const API='http://127.0.0.1:8011';
const TYPES={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json'};
http.createServer((req,res)=>{
  if(req.url.startsWith('/api/')){
    const target=API+req.url.slice(4);
    const proxy=http.request(target,{method:req.method,headers:req.headers},r=>{res.writeHead(r.statusCode,r.headers);r.pipe(res)});
    proxy.on('error',()=>{res.writeHead(502);res.end('backend unavailable')});
    req.pipe(proxy);return;
  }
  let urlPath=req.url.split('?')[0];if(urlPath==='/')urlPath='/index.html';
  const file=path.join(ROOT,urlPath);
  fs.readFile(file,(err,data)=>{
    if(err){fs.readFile(path.join(ROOT,'index.html'),(e2,idx)=>{res.writeHead(200,{'Content-Type':'text/html'});res.end(idx)});return}
    res.writeHead(200,{'Content-Type':TYPES[path.extname(file)]||'application/octet-stream'});res.end(data);
  });
}).listen(PORT,()=>console.log('frontend on '+PORT));
