// SPDX-License-Identifier: GPL-3.0-or-later
(() => {
  'use strict';
  const root=document.getElementById('trap-rail-demo');
  const ui={view:'portal',slot:0,coop:false,page:'display',snapshot:null,dirty:false,sequence:-1};
  const slotNames={0:'Player 1',3:'Player 2',1:'Trap',2:'Item'};
  const images=new Map();let bridge=null;let previous='';
  const search=root.querySelector('[data-search]');const message=root.querySelector('[data-message]');
  const icon=()=>window.lucide?.createIcons({attrs:{width:18,height:18}});
  const collection=kind=>ui.snapshot?.collections?.[String(kind)]||[];
  const selected=kind=>collection(kind).find(item=>(item.state&2)!==0);
  const kind=()=>ui.slot===3?0:ui.slot;
  const send=(verb,...args)=>bridge?.command([verb,...args].join(' '));
  function portrait(cell){
    const image=document.createElement('img');image.alt='';
    if(cell<0){image.hidden=true;return image;}
    if(images.has(cell))image.src=images.get(cell);
    else if(bridge)bridge.portrait(cell,value=>{if(value){images.set(cell,value);image.src=value;}else image.hidden=true;});
    return image;
  }
  function button(className,label){const result=document.createElement('button');result.type='button';result.className=className+' cursor-interaction';if(label)result.setAttribute('aria-label',label);return result;}
  function slots(){
    const strip=root.querySelector('.slot-strip');strip.replaceChildren();strip.classList.toggle('coop',ui.coop);
    for(const slot of ui.coop?[0,3,1,2]:[0,1,2]){
      const item=selected(slot);const card=button('slot',slotNames[slot]+': '+(item?.name||'Empty'));card.setAttribute('aria-pressed',String(ui.slot===slot));
      let cell=item?.portrait??-1;if(slot===1&&item&&cell<0)cell=ui.snapshot?.elements?.[item.element]?.portrait??-1;
      if(cell>=0)card.append(portrait(cell));else{const empty=document.createElement('span');empty.className='empty';empty.innerHTML='<i data-lucide="orbit" aria-hidden="true"></i>';card.append(empty);}
      const label=document.createElement('span');label.textContent=slotNames[slot];const name=document.createElement('span');name.className='slot-name';name.textContent=item?.name||'Empty';card.append(label,name);
      card.onclick=()=>{ui.slot=slot;search.value='';root.querySelector('.figure-creator').hidden=true;render();};strip.append(card);
    }
    root.querySelector('[data-coop]').textContent=ui.coop?'− Remove player 2':'+ Add player 2';
    root.querySelector('[data-remove]').textContent=ui.slot===1?'Eject trap':ui.slot===2?'Remove item':'Remove figure';
  }
  function traps(){
    const elementGrid=root.querySelector('.element-grid');elementGrid.replaceChildren();
    const current=selected(1);
    for(const element of ui.snapshot?.elements||[]){
      const card=button('element-button','Place empty '+element.name+' trap');card.setAttribute('aria-pressed',String(current?.capture===0&&current.element===element.index));card.append(portrait(element.portrait));
      const label=document.createElement('span');label.textContent=element.name;card.append(label);card.onclick=()=>send('portal',12,element.index);elementGrid.append(card);
    }
    const grid=root.querySelector('.capture-list');grid.replaceChildren();
    const captures=collection(1).filter(item=>(item.state&1)&&item.capture!==0).sort((a,b)=>a.element-b.element||a.index-b.index);
    for(const item of captures){
      const card=button('capture-tile','Insert '+item.detail+' trap: '+item.name);card.setAttribute('aria-pressed',String(!!(item.state&2)));
      const image=portrait(item.portrait>=0?item.portrait:ui.snapshot.elements[item.element]?.portrait??-1);image.className='villain-portrait';
      const label=document.createElement('span');label.className='villain-name';label.textContent=item.name;
      const element=document.createElement('span');element.className='villain-element';element.append(portrait(ui.snapshot.elements[item.element]?.portrait??-1));const text=document.createElement('span');text.textContent=item.detail;element.append(text);card.append(image,label,element);card.onclick=()=>send('portal',1,item.index);grid.append(card);
    }
    if(!captures.length){const empty=document.createElement('p');empty.className='no-results';empty.textContent='Captured villains appear here after an in-game capture.';grid.append(empty);}
  }
  function figures(){
    const category=kind();const list=collection(ui.slot).filter(item=>item.name.toLowerCase().includes(search.value.trim().toLowerCase()));
    root.querySelector('[data-collection-title]').textContent=category===2?'Choose an item':'Choose a Skylander';root.querySelector('[data-current-slot]').textContent=slotNames[ui.slot];search.placeholder=category===2?'Search items…':'Search Skylanders…';
    const grid=root.querySelector('.portrait-grid');grid.replaceChildren();
    for(const item of list){const card=button('figure','Place '+item.name+' in '+slotNames[ui.slot]);card.setAttribute('aria-pressed',String(!!(item.state&2)));card.append(portrait(item.portrait));const label=document.createElement('span');label.textContent=item.name;card.append(label);
      if(item.state&2){const check=document.createElement('span');check.className='selected-mark';check.innerHTML='<i data-lucide="check" aria-hidden="true"></i>';card.append(check);}
      card.onclick=()=>send('portal',category===2?8:ui.slot===3?6:0,item.index);grid.append(card);}
    if(!list.length){const empty=document.createElement('p');empty.className='no-results';empty.textContent='Create or import a figure to start your collection.';grid.append(empty);}
    const selector=root.querySelector('#trap-create-character');const saved=selector.value;selector.replaceChildren();
    for(const item of ui.snapshot?.creation||[]){if(item.kind!==category)continue;const option=document.createElement('option');option.value=String(item.index);option.textContent=item.name;selector.append(option);}if([...selector.options].some(option=>option.value===saved))selector.value=saved;
    root.querySelector('.figure-creator h3').textContent=category===2?'Create an item':'Create a Skylander';root.querySelector('[data-add]').textContent=category===2?'Create item':'Create figure';
  }
  function render(){
    const focused=document.activeElement?.getAttribute('aria-label');
    root.querySelector('.portal-panel').hidden=ui.view!=='portal';root.querySelector('.settings-panel').hidden=ui.view!=='settings';
    root.querySelectorAll('[data-view]').forEach(node=>{const active=node.dataset.view===ui.view&&(!node.dataset.page||node.dataset.page===ui.page);node.classList.toggle('is-current',active);node.setAttribute('aria-expanded',String(active));});
    root.querySelectorAll('[data-settings-page]').forEach(node=>node.hidden=node.dataset.settingsPage!==ui.page);
    root.querySelector('[data-setting-title]').textContent={display:'Display',controls:'Controls',audio:'Audio'}[ui.page];
    const old=root.querySelector('[data-setting-icon]');const next=document.createElement('i');next.dataset.settingIcon='';next.dataset.lucide={display:'monitor',controls:'gamepad-2',audio:'volume-2'}[ui.page];next.setAttribute('aria-hidden','true');old.replaceWith(next);
    slots();const isTrap=ui.slot===1;
    root.querySelector('.trap-browser').hidden=!isTrap;root.querySelector('.portrait-grid').hidden=isTrap;root.querySelector('.search').hidden=isTrap;root.querySelector('.collection-actions').hidden=isTrap;root.querySelector('.section-title').hidden=isTrap;
    if(isTrap)traps();else figures();message.textContent=ui.snapshot?.status||'Waiting for the game…';icon();
    if(focused){const match=[...root.querySelectorAll('button')].find(node=>node.getAttribute('aria-label')===focused);match?.focus({preventScroll:true});}
  }
  function initializeSettings(settings){
    if(ui.dirty)return;
    for(const [id,key] of [['trap-demo-res','resolution'],['trap-demo-quality','quality'],['trap-demo-fps','framePolicy'],['trap-demo-pad','layout'],['trap-demo-glyphs','glyphs']])root.querySelector('#'+id).selectedIndex=settings[key]??0;
    root.querySelector('.check input').checked=!!settings.fullscreen;root.querySelector('#trap-demo-audio').value=String(settings.volume??30);root.querySelector('[data-volume]').textContent=(settings.volume??30)+'%';
  }
  function receive(text){
    let snapshot;try{snapshot=JSON.parse(text);}catch{return;}if(snapshot.version!==1)return;
    if(snapshot.collections){const comparable=JSON.stringify([snapshot.collections,snapshot.elements,snapshot.creation,snapshot.status]);ui.snapshot=snapshot;if(comparable!==previous){previous=comparable;ui.coop=ui.coop||!!selected(3);render();}initializeSettings(snapshot.settings||{});}
    if(snapshot.inputSequence!==ui.sequence){ui.sequence=snapshot.inputSequence;for(const key of snapshot.keys||[])if(key>0)navigate(key);}
  }
  function navigate(key){
    if(key===6){send('close');return;}if(key===5){if(document.activeElement instanceof HTMLButtonElement)document.activeElement.click();else document.activeElement?.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));return;}
    const nodes=[...root.querySelectorAll('button,input,select')].filter(node=>!node.disabled&&node.getClientRects().length);
    if(!nodes.length)return;const active=document.activeElement;if(!nodes.includes(active)){nodes[0].focus();return;}
    const rect=active.getBoundingClientRect();const x=rect.x+rect.width/2,y=rect.y+rect.height/2;let best=null,score=Infinity;
    for(const node of nodes){if(node===active)continue;const r=node.getBoundingClientRect();const dx=r.x+r.width/2-x,dy=r.y+r.height/2-y;const forward=key===1?-dy:key===2?dy:key===3?-dx:dx;if(forward<4)continue;const cross=key<3?Math.abs(dx):Math.abs(dy);const candidate=forward+cross*2.5;if(candidate<score){best=node;score=candidate;}}
    best?.focus();best?.scrollIntoView({block:'nearest',inline:'nearest'});
  }
  root.querySelectorAll('[data-view]').forEach(node=>node.onclick=()=>{ui.view=node.dataset.view;if(node.dataset.page)ui.page=node.dataset.page;render();});
  root.querySelectorAll('[data-close]').forEach(node=>node.onclick=()=>{ui.view='none';render();});
  root.querySelector('[data-coop]').onclick=()=>{ui.coop=!ui.coop;if(ui.coop)ui.slot=3;else{send('portal',7,0);if(ui.slot===3)ui.slot=0;}render();};
  root.querySelector('[data-remove]').onclick=()=>send('portal',ui.slot===1?4:ui.slot===2?9:ui.slot===3?7:3,0);
  root.querySelector('[data-add]').onclick=()=>{const panel=root.querySelector('.figure-creator');panel.hidden=!panel.hidden;};
  root.querySelector('[data-import]').onclick=()=>bridge?.importFigure(ui.slot===3?1:0);
  root.querySelector('[data-create-figure]').onclick=()=>{const choice=Number(root.querySelector('#trap-create-character').value);if(Number.isInteger(choice)&&choice>=0){send('portal',ui.slot===3?10:5,choice);root.querySelector('.figure-creator').hidden=true;}};
  search.oninput=()=>{figures();icon();};
  root.querySelectorAll('.settings-panel input,.settings-panel select').forEach(node=>node.addEventListener('change',()=>ui.dirty=true));
  root.querySelector('#trap-demo-fps').onchange=event=>{ui.dirty=true;send('fps',event.target.selectedIndex);};
  root.querySelector('#trap-demo-audio').oninput=event=>{ui.dirty=true;root.querySelector('[data-volume]').textContent=event.target.value+'%';send('volume',event.target.value);};
  root.querySelector('[data-apply]').onclick=()=>send('settings',root.querySelector('#trap-demo-res').selectedIndex,root.querySelector('#trap-demo-quality').selectedIndex,Number(root.querySelector('.check input').checked),Number(ui.snapshot?.settings?.counter??true),root.querySelector('#trap-demo-pad').selectedIndex,root.querySelector('#trap-demo-glyphs').selectedIndex);
  document.addEventListener('keydown',event=>{if(['Escape','F6','Insert'].includes(event.key)){event.preventDefault();send('close');return;}const keys={ArrowUp:1,ArrowDown:2,ArrowLeft:3,ArrowRight:4};if(keys[event.key]&&!(event.target instanceof HTMLInputElement)&&!(event.target instanceof HTMLSelectElement)){event.preventDefault();navigate(keys[event.key]);}});
  window.portalReceive=receive;window.portalNavigate=navigate;
  icon();
  new QWebChannel(qt.webChannelTransport,channel=>{bridge=channel.objects.portal;bridge.changed.connect(receive);bridge.ready();bridge.snapshot(receive);});
})();
