const $=id=>document.getElementById(id);
const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const model={step:1,stage:'wizard',subject:'',layers:5,pointed:true,upload:null,worker:null,files:[],result:null,master:null,example:false};
let zoomSource={url:new URL('./examples/ginkgo/stacked_green.png',import.meta.url).href,name:'ginkgo-green-stack.png'};
const busy=()=>['preparing','exporting'].includes(model.stage);
const setStatus=text=>{$('status-pill').replaceChildren(Object.assign(document.createElement('i'),{}),document.createTextNode(text));};
function notice(message=''){$('notice').textContent=message;$('notice').hidden=!message;}
function stagePanels(show){
 for(const id of ['design-form','processing-panel','review-panel','download-panel'])$(id).hidden=id!==show;
 $('new-button').disabled=busy();$('example-button').disabled=busy();
 $('art-busy').hidden=!busy();
}
function setArt(url,label,alt,full=url,name='artwork.png'){
 $('main-art').src=url;$('main-art').alt=alt;$('art-label').textContent=label;
 zoomSource={url:full,name};
 $('art-stage').hidden=false;$('layers-view').hidden=true;$('checks-view').hidden=true;
}
function showStep(step){
 model.step=step;model.stage='wizard';notice();stagePanels('design-form');
 $('main').classList.remove('result-mode');$('results-tools').hidden=true;$('art-footer').hidden=false;
 $('breadcrumb-current').textContent='NEW LAYER SET';$('art-caption').hidden=false;
 document.querySelectorAll('.form-step').forEach(section=>section.hidden=section.id!==`step-${step}`);
 document.querySelectorAll('.stepper li').forEach((li,i)=>{li.classList.toggle('active',i+1===step);li.classList.toggle('done',i+1<step);});
 setStatus('Ready when you are');
 if(step===1)setArt('./assets/ginkgo-stack.png','THE GINKGO STUDY','Example green ginkgo layer stack',new URL('./examples/ginkgo/stacked_green.png',import.meta.url).href);
 if(step===2)$('layers').focus();
 if(step===3)refreshReference();
}
function worker(){
 if(model.worker)return model.worker;
 if(!window.Worker||!window.WebAssembly)throw new Error('This studio needs a modern desktop browser with WebAssembly support.');
 const current=new Worker(new URL('./worker.js',import.meta.url));
 current.onmessage=event=>{
  if(model.worker!==current)return;
  const data=event.data;
  if(data.type==='progress'&&busy())showProgress(data);
  if(data.type==='runtime-ready'&&!busy())setStatus('Drawing tools ready');
  if(data.type==='file'){
   const blob=new Blob([data.buffer],{type:data.file.mime});
   model.files.push({...data.file,url:URL.createObjectURL(blob),bytes:blob.size});
  }
  if(data.type==='master-ready')showMaster(data.data);
  if(data.type==='complete'){model.result=data.data;model.example=false;showResults();stopWorker();}
  if(data.type==='error')fail(data.message);
  if(data.type==='runtime-error'){if(busy())fail(data.message);else{stopWorker();setStatus('Drawing tools will retry');}}
 };
 current.onerror=event=>{if(model.worker===current)fail(event.message||'The drawing worker stopped unexpectedly.');};
 model.worker=current;return current;
}
function stopWorker(){if(model.worker){model.worker.onmessage=null;model.worker.onerror=null;model.worker.terminate();model.worker=null;}}
function releaseFiles(){model.files.forEach(file=>{if(file.url.startsWith('blob:'))URL.revokeObjectURL(file.url);});model.files=[];}
function file(kind,index){return model.files.find(item=>item.kind===kind&&(index===undefined||item.index===index));}
function showProgress({stage,current=0,total=1}){
 let label,width;const ratio=total?current/total:0;
 const exporting=model.stage==='exporting';
 if(stage==='runtime'){label=current===0?'Loading the drawing tools…':'Getting the graphics libraries ready…';width=4+ratio*12;}
 else if(stage==='trace'){label='Finding the flow of your reference…';width=18;}
 else if(stage==='curves'){label=`Building smooth components · ${current} of ${total}`;width=exporting?5+ratio*30:20+ratio*65;}
 else if(stage==='layers'){label=`Creating layer ${current} of ${total}…`;width=35+ratio*15;}
 else if(stage==='validate'){label=current===0?'Checking every exported layer…':'Checking structural widths and pointed tips…';width=current===0?55:72;}
 else if(stage==='previews'){label='Assembling the green stack…';width=87;}
 else if(stage==='package'){label='Packaging your cutting files…';width=95;}
 else{label='Preparing your design…';width=10;}
 $('progress-label').textContent=label;$('progress-bar').style.width=`${width}%`;
 setStatus(exporting?'Building your layer set':'Preparing your master');
}
function friendlyError(raw){
 if(/memory|out of bounds|allocation/i.test(raw))return'This design exceeded the browser’s available memory. Close other tabs or use a desktop browser, then try again.';
 if(/not enough|at most .*distinct|complete ornaments/i.test(raw))return'This artwork does not have enough separate detail for that many layers. Choose fewer layers and preview it again.';
 if(/disconnected|no separate artwork|source silhouette|reference skeleton/i.test(raw))return'This reference could not form a connected design. Please use a clear black-on-white ginkgo master with attached details.';
 if(/validation failed|failed required|not exactly|material-width backbones/i.test(raw))return'This design did not pass the cutting checks. Try a clearer reference or fewer layers. A failed set will not be offered for cutting.';
 if(/fetch|network|importScripts/i.test(raw))return'The drawing tools could not load. Check your connection and try again. Your image has not been uploaded.';
 return String(raw).split('\n').filter(Boolean).slice(-1)[0].replace(/^\w*Error:\s*/,'').slice(0,400);
}
function fail(raw){
 const wasExport=model.stage==='exporting';stopWorker();model.stage='wizard';showStep(wasExport?3:model.step);
 notice(friendlyError(raw));setStatus('Let’s try again');
}
function validateSubject(){
 const value=$('subject').value.trim();
 if(!value){notice('Start by naming your subject.');$('subject').focus();return false;}
 if(!/\b(ginkgo|gingko)\b/i.test(value)){notice('Ginkgo leaf is the currently available subject. Choose it to continue.');$('subject').focus();return false;}
 model.subject=value;return true;
}
function validateLayers(){
 const n=Number($('layers').value);
 if(!Number.isInteger(n)||n<2||n>12){notice('Choose a whole number from 2 to 12 layers.');$('layers').focus();return false;}
 model.layers=n;return true;
}
async function prepareMaster(){
 if(!validateSubject()||!validateLayers())return;
 const uploaded=document.querySelector('input[name=reference]:checked').value==='upload';
 if(uploaded&&!model.upload){notice('Choose a PNG or JPEG reference image first.');return;}
 model.pointed=document.querySelector('input[name=tips]:checked').value==='pointed';
 notice();releaseFiles();model.master=null;model.result=null;model.stage='preparing';
 stagePanels('processing-panel');$('processing-title').innerHTML='Finding the flow.<br>Keeping the detail.';
 $('progress-label').textContent='Getting the drawing tools ready…';$('progress-bar').style.width='3%';
 $('results-tools').hidden=true;$('art-footer').hidden=false;$('art-caption').hidden=true;
 try{
  const command={command:'prepare',subject:model.subject,layers:model.layers,pointed_tips:model.pointed};
  if(uploaded){command.buffer=await model.upload.arrayBuffer();worker().postMessage(command,[command.buffer]);}
  else worker().postMessage(command);
 }catch(error){fail(error.message);}
}
function showMaster(data){
 model.master=data;model.stage='review';stagePanels('review-panel');setStatus('Master ready for review');
 $('review-summary').innerHTML=`<div><dt>Subject</dt><dd>${escape(data.subject)}</dd></div><div><dt>Layers</dt><dd>${data.layers}</dd></div><div><dt>Tendril finish</dt><dd>${data.pointed_tips?'Fine points':'Rounded ends'}</dd></div><div><dt>Output</dt><dd>600 DPI · 11.5 in frame</dd></div>`;
 $('approve-button').firstChild.textContent=`Approve & build ${data.layers} layers `;
 setArt(file('master_preview').url,'YOUR MASTER · FOR REVIEW','Master artwork awaiting your visual review',file('master_full').url,'reviewed_master.png');
 $('art-caption').hidden=true;$('art-footer').hidden=true;
}
function approve(){
 if(model.stage!=='review'||!model.master)return;
 model.stage='exporting';stagePanels('processing-panel');
 $('processing-title').innerHTML='One master.<br>Every layer aligned.';
 $('progress-label').textContent='Building your layer set…';$('progress-bar').style.width='3%';
 try{worker().postMessage({command:'export'});}catch(error){fail(error.message);}
}
function showResults(){
 model.stage='results';stagePanels('download-panel');notice();$('main').classList.add('result-mode');
 $('breadcrumb-current').textContent=model.example?'GINKGO EXAMPLE':'YOUR LAYER SET';
 $('result-eyebrow').textContent=model.example?'THE GINKGO STUDY · EXAMPLE':'YOUR FINISHED SET';
 $('result-description').textContent=`${model.result.layers} separate layers, from rich detail to a simple outline. All derived from one master.`;
 const r=model.result.report;
 $('checks-summary').innerHTML=`<strong>✓ ${model.result.layers} layers passed the cutting checks</strong><span>Aligned · Symmetrical · Connected</span>${model.result.pointed_tips?'<br><span>Pointed-tip exception applied to decorative ends.</span>':''}`;
 const zip=file('bundle');$('download-zip').href=zip.url;$('download-zip').download=zip.name;
 $('download-report').href=file('report').url;$('download-report').download='validation_report.json';
 $('download-detail').textContent=`${zip.bytes?formatBytes(zip.bytes)+' · ':''}Separate PNGs, green preview & validation report.`;
 $('art-caption').hidden=true;$('art-footer').hidden=false;
 const shades=model.result.palette||['#123d24','#216b3a','#399750','#6bbc70','#a7dca0'];
 $('art-footer').querySelector('.palette').innerHTML=shades.filter(shade=>/^#[0-9a-f]{6}$/i.test(shade)).map(shade=>`<i style="--shade:${shade}"></i>`).join('');
 $('art-footer').querySelector('.palette').setAttribute('aria-label',`${model.result.layers} shades from bottom to top`);
 $('art-footer').lastElementChild.textContent=`${model.result.layers} layers${model.example?' · example':''}`;
 $('results-tools').hidden=false;setStatus(model.example?'Validated example':'Your set is ready');
 renderLayers();renderChecks();selectTab('stack');
}
function selectTab(tab){
 document.querySelectorAll('[data-tab]').forEach(button=>button.setAttribute('aria-selected',String(button.dataset.tab===tab)));
 $('art-stage').hidden=tab!=='stack';$('art-footer').hidden=tab!=='stack';$('layers-view').hidden=tab!=='layers';$('checks-view').hidden=tab!=='checks';
 if(tab==='stack')setArt(file('stack').url,'ASSEMBLED STACK · BOTTOM TO TOP',`Aligned ${model.result.layers}-layer ginkgo set in green shades`,file('stack_full').url,'stacked_green.png');
}
function renderLayers(){
 $('layers-view').replaceChildren();
 for(let i=1;i<=model.result.layers;i++){
  const png=file('layer',i),preview=file('layer_preview',i);const tile=document.createElement('div');tile.className='layer-tile';
  tile.innerHTML=`<button aria-label="Enlarge layer ${i}"><img loading="lazy" src="${preview?.url||png.url}" alt="Layer ${i} black-and-white cutting artwork"></button><div><span>Layer ${i}<small>${i===1?'BOTTOM · MOST DETAILED':i===model.result.layers?'TOP · OUTLINE':'MIDDLE LAYER'}</small></span><a href="${png.url}" download="${escape(png.name)}" aria-label="Download layer ${i} PNG">↓</a></div>`;
  tile.querySelector('button').onclick=()=>openImage(png.url,png.name);$('layers-view').append(tile);
 }
}
function renderChecks(){
 const r=model.result.report,rows=r.layers;
 const checks=[['Exact pixel alignment',rows.every(x=>x.containment_violations===0),'Every upper layer is an exact subset of the one beneath.'],
 ['Unchanged outline',rows.every(x=>x.missing_core_pixels===0),'Core geometry and scaling frame stay in the same coordinates.'],
 ['Vertical symmetry',rows.every(x=>x.symmetry_mismatched_pixels===0),'Zero mismatched pixels against a vertical mirror.'],
 ['One connected piece',rows.every(x=>x.artwork_connected_components===1),'No detached artwork islands; scaling frame excluded.'],
 ['Structural material width',rows.every(x=>x.structural_width_passed??(x.minimum_width_uncovered_pixels===0&&x.connected_backbones_after_19px_erosion===1)),'Bridges and load-bearing strokes meet the 1/16-inch minimum.'],
 ['Clean side rim',r.lateral_rim_audit_passed??true,'No unplanned side-rim slivers outside intentional join areas.']];
 $('checks-view').innerHTML='<h3>Checked, pixel by pixel.</h3>'+checks.map(([title,passed,description])=>`<div class="check-row"><span class="check-icon">${passed?'✓':'!'}</span><div>${title}<small>${description}</small></div></div>`).join('')+`<p class="checks-note">${model.result.pointed_tips?'Fine points are an explicit exception to the width minimum at decorative terminal ends. Structural bodies are checked separately. ':''}${r.reviewed_master_unchanged?'Your reviewed master stayed unchanged in the export. ':''}Use the 11.5-inch scaling frame when importing. Exclude that frame from cutting, and test your material and kerf.</p>`;
}
async function loadExample(){
 if(busy())return;notice();stopWorker();releaseFiles();
 const base=new URL('./examples/ginkgo/',import.meta.url);
 try{
  const response=await fetch(new URL('validation_report.json',base));if(!response.ok)throw new Error('The example could not load.');
  const report=await response.json();
  const add=(kind,name,index)=>model.files.push({kind,name,index,url:new URL(name,base).href});
  add('bundle','ginkgo_pointed_tips_5_layers.zip');add('stack','stacked_green_preview.png');add('stack_full','stacked_green.png');add('sheet','all_layers_preview.png');add('report','validation_report.json');
  for(let i=1;i<=5;i++){const suffix=i===1?'_bottom':i===5?'_top':'';add('layer',`layer_${String(i).padStart(2,'0')}${suffix}.png`,i);add('layer_preview',`layer_${String(i).padStart(2,'0')}${suffix}_preview.png`,i);}
  model.result={subject:'Ginkgo leaf',layers:5,pointed_tips:true,report};model.example=true;showResults();
 }catch(error){notice(error.message);}
}
function formatBytes(n){return n>1024*1024?`${(n/1024/1024).toFixed(1)} MB`:`${Math.round(n/1024)} KB`;}
function acceptUpload(upload){
 if(!upload)return;
 if(upload.size>20*1024*1024){model.upload=null;$('reference-file').value='';notice('Please choose an image smaller than 20 MB.');return;}
 if(!['image/png','image/jpeg'].includes(upload.type)&&!(/\.(png|jpe?g)$/i.test(upload.name))){model.upload=null;$('reference-file').value='';notice('Please use a PNG or JPEG image.');return;}
 model.upload=upload;$('upload-label').textContent=upload.name;notice();
 document.querySelector('input[name=reference][value=upload]').checked=true;refreshReference();
}
let referenceURL;
function refreshReference(){
 const uploaded=document.querySelector('input[name=reference]:checked').value==='upload';$('upload-area').hidden=!uploaded;
 if(uploaded&&model.upload){if(referenceURL)URL.revokeObjectURL(referenceURL);referenceURL=URL.createObjectURL(model.upload);setArt(referenceURL,'YOUR REFERENCE','Your uploaded reference image');}
 else setArt('./assets/ginkgo-stack.png','THE GINKGO STUDY','Example green ginkgo layer set',new URL('./examples/ginkgo/stacked_green.png',import.meta.url).href);
}
function newDesign(){if(busy())return;stopWorker();showStep(1);$('subject').focus();}
function openImage(url=zoomSource.url,name=zoomSource.name){$('dialog-art').src=url;$('dialog-download').href=url;$('dialog-download').download=name;$('image-dialog').showModal();}
$('design-form').onsubmit=event=>{
 event.preventDefault();notice();
 if(model.step===1&&validateSubject()){showStep(2);try{worker().postMessage({command:'warm'});}catch(error){notice(error.message);}}
 else if(model.step===2&&validateLayers())showStep(3);
 else if(model.step===3)prepareMaster();
};
document.querySelectorAll('[data-subject]').forEach(button=>button.onclick=()=>{$('subject').value=button.dataset.subject;$('subject').focus();notice();});
document.querySelectorAll('[data-back]').forEach(button=>button.onclick=()=>showStep(Number(button.dataset.back)));
$('less-layers').onclick=()=>$('layers').value=Math.max(2,(Number($('layers').value)||5)-1);
$('more-layers').onclick=()=>$('layers').value=Math.min(12,(Number($('layers').value)||5)+1);
document.querySelectorAll('input[name=reference]').forEach(input=>input.onchange=refreshReference);
document.querySelectorAll('input[name=tips]').forEach(input=>input.onchange=()=>{$('tip-note').textContent=input.value==='pointed'?'Fine decorative tips may taper below 1/16 in. Structural bridges keep their full minimum width.':'Every retained feature, including tendril ends, keeps the full minimum width.';});
$('reference-file').onchange=event=>acceptUpload(event.target.files[0]);
for(const type of ['dragenter','dragover'])$('upload-zone').addEventListener(type,event=>{event.preventDefault();$('upload-zone').classList.add('dragging');});
for(const type of ['dragleave','drop'])$('upload-zone').addEventListener(type,event=>{event.preventDefault();$('upload-zone').classList.remove('dragging');if(type==='drop')acceptUpload(event.dataTransfer.files[0]);});
$('approve-button').onclick=approve;$('adjust-button').onclick=()=>showStep(3);
$('cancel-button').onclick=()=>{stopWorker();model.stage='wizard';showStep(3);setStatus('Stopped · ready to adjust');};
$('new-button').onclick=newDesign;$('another-button').onclick=newDesign;$('example-button').onclick=loadExample;
document.querySelectorAll('[data-tab]').forEach(button=>button.onclick=()=>selectTab(button.dataset.tab));
$('zoom-button').onclick=()=>openImage();$('close-image').onclick=()=>$('image-dialog').close();
$('image-dialog').addEventListener('close',()=>$('dialog-art').removeAttribute('src'));
$('how-example-button').onclick=()=>{$('how-dialog').close();loadExample();};
$('how-button').onclick=()=>$('how-dialog').showModal();$('close-how').onclick=()=>$('how-dialog').close();
for(const id of ['image-dialog','how-dialog'])$(id).addEventListener('click',event=>{if(event.target===$(id))$(id).close();});
window.addEventListener('beforeunload',()=>{releaseFiles();stopWorker();});
