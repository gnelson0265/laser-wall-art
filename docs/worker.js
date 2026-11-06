/* The generator runs here, off the UI thread. References never leave this worker. */
let enginePromise, busy=false, session=0, currentWorkspace=null;
const send=(type,data={})=>postMessage({type,...data});
async function engine(){
 if(!enginePromise)enginePromise=(async()=>{
  send('progress',{stage:'runtime',current:0,total:3});
  importScripts('https://cdn.jsdelivr.net/pyodide/v0.28.3/full/pyodide.js');
  const py=await loadPyodide({indexURL:'https://cdn.jsdelivr.net/pyodide/v0.28.3/full/'});
  send('progress',{stage:'runtime',current:1,total:3});
  await py.loadPackage(['numpy','scipy','pillow']);
  const manifest=await (await fetch('./engine-manifest.json',{cache:'no-cache'})).json();
  const archive=await (await fetch('./engine.zip',{cache:'no-cache'})).arrayBuffer();
  const digest=[...new Uint8Array(await crypto.subtle.digest('SHA-256',archive))].map(x=>x.toString(16).padStart(2,'0')).join('');
  if(digest!==manifest.sha256)throw new Error('Engine integrity check failed. Refresh the page and try again.');
  py.unpackArchive(archive,'zip',{extractDir:'/home/pyodide'});
  py.FS.mkdirTree('/home/pyodide/studio');
  py.globals.set('studio_progress',(stage,current,total)=>send('progress',{stage:String(stage),current:Number(current),total:Number(total)}));
  py.setStdout({batched:line=>send('log',{message:line})});
  await py.runPythonAsync('from laser_art.studio import prepare, export\nimport json, pathlib, gc');
  send('runtime-ready');return py;
 })().catch(error=>{enginePromise=null;throw error;});
 return enginePromise;
}
function transferFile(py,file){
 const bytes=py.FS.readFile(file.path);
 const buffer=bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength);
 const {path,...publicFile}=file;
 send('file',{file:publicFile,buffer},[buffer]);
}
self.onmessage=async event=>{
 const data=event.data;
 if(data.command==='warm'){
  try{await engine();}catch(error){send('runtime-error',{message:String(error)});}return;
 }
 if(busy){send('error',{message:'A design is already being prepared.'});return;}
 busy=true;
 try{
  const py=await engine();
  if(data.command==='prepare'){
   const bytes=data.buffer?new Uint8Array(data.buffer):new Uint8Array(await (await fetch('./assets/ginkgo-master.png')).arrayBuffer());
   py.FS.writeFile('/home/pyodide/studio/input.png',bytes);
   currentWorkspace=`/home/pyodide/studio/design_${++session}`;
   py.globals.set('studio_config',JSON.stringify({subject:data.subject,layers:data.layers,pointed_tips:data.pointed_tips,workspace:currentWorkspace}));
   const result=JSON.parse(await py.runPythonAsync(`
cfg=json.loads(studio_config)
preview=prepare('/home/pyodide/studio/input.png',cfg['subject'],cfg['layers'],cfg['pointed_tips'],cfg['workspace'],studio_progress)
json.dumps(preview)
`));
   transferFile(py,{path:result.preview_path,name:'master_preview.png',mime:'image/png',kind:'master_preview'});
   transferFile(py,{path:result.master_path,name:'reviewed_master.png',mime:'image/png',kind:'master_full'});
   send('master-ready',{data:result});
  }else if(data.command==='export'){
   if(!currentWorkspace)throw new Error('Create a master preview first.');
   py.globals.set('studio_workspace',currentWorkspace);
   const result=JSON.parse(await py.runPythonAsync("json.dumps(export(studio_workspace,studio_progress))"));
   for(const file of result.files)transferFile(py,file);
   send('complete',{data:{subject:result.subject,layers:result.layers,pointed_tips:result.pointed_tips,report:result.report,palette:result.palette}});
  }else throw new Error('Unknown action.');
 }catch(error){send('error',{message:String(error),details:error.stack||''});}
 finally{busy=false;}
};
