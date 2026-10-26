// Local-only review overlay: generated blog output + unchanged main-site assets.
const http=require('http'),fs=require('fs'),path=require('path');
const mime={'.html':'text/html; charset=utf-8','.css':'text/css','.js':'text/javascript','.webp':'image/webp','.avif':'image/avif','.png':'image/png','.jpg':'image/jpeg','.svg':'image/svg+xml','.woff2':'font/woff2','.xml':'application/xml'};
function server({blog,site}){const BLOG=path.resolve(blog),SITE=path.resolve(site);return http.createServer(async(req,res)=>{
 try{
  if(!['GET','HEAD'].includes(req.method)){res.writeHead(405);return res.end();}
  let name=decodeURIComponent(new URL(req.url,'http://localhost').pathname),root=name.startsWith('/blog/')?BLOG:SITE;
  if(name.startsWith('/blog/'))name=name.slice(5);
  if(name.endsWith('/'))name+='index.html';
  const file=path.resolve(root,'.'+name);if(!file.startsWith(root+path.sep)){res.writeHead(403);return res.end();}
  let body=await fs.promises.readFile(file);
  if(file.endsWith('.html'))body=Buffer.from(body.toString().replace(/https:\/\/zero2one\.sa(?=\/assets\/)/g,''));
  res.writeHead(200,{'Content-Type':mime[path.extname(file)]||'application/octet-stream','Cache-Control':'no-store'});res.end(req.method==='HEAD'?undefined:body);
 }catch(e){res.writeHead(e.code==='ENOENT'?404:400);res.end('Not found');}
});}
module.exports={server};
if(require.main===module){
 if(!process.argv[2]||!process.argv[3])throw new Error('Usage: node tools/preview_article_review.js BLOG_OUTPUT SITE_CHECKOUT [PORT]');
 server({blog:process.argv[2],site:process.argv[3]}).listen(Number(process.argv[4]||8767),'127.0.0.1',()=>console.log('Blog review: http://127.0.0.1:'+(process.argv[4]||8767)+'/blog/ar/best-digital-marketing-agency-in-saudi-arabia/'));
}
