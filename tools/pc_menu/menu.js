// SPDX-License-Identifier: GPL-3.0-or-later
(() => {
  'use strict';
  const root=document.getElementById('trap-rail-demo');
  const ui={view:'portal',slot:0,coop:false,page:'display',snapshot:null,dirty:false,sequence:-1};
  const slotNames={0:'Player 1',3:'Player 2',1:'Trap',2:'Item',9:'Vehicle'};
  const images=new Map();let bridge=null;let previous='';
  let selectPopup=null;
  function closeSelect(){if(selectPopup){const select=selectPopup.select;selectPopup.node.remove();selectPopup=null;select.focus({preventScroll:true});}}
  function chooseSelect(){if(!selectPopup)return;const {select,index}=selectPopup;select.selectedIndex=index;select.dispatchEvent(new Event('change',{bubbles:true}));closeSelect();}
  function moveSelect(step){if(!selectPopup)return;const popup=selectPopup;popup.index=Math.max(0,Math.min(popup.select.options.length-1,popup.index+step));[...popup.node.children].forEach((node,index)=>node.setAttribute('aria-selected',String(index===popup.index)));popup.node.children[popup.index]?.scrollIntoView({block:'nearest'});}
  // Browser select popups are separate native windows. In embedded mode, draw
  // their option list in this same page so it is captured in the game texture.
  document.addEventListener('mousedown',event=>{
    if(!ui.snapshot?.embedded)return;
    const select=event.target.closest('select');
    if(!select){if(selectPopup&&!selectPopup.node.contains(event.target))closeSelect();return;}
    event.preventDefault();event.stopPropagation();
    const same=selectPopup?.select===select;closeSelect();if(same)return;
    select.focus();const node=document.createElement('div');node.className='embedded-options';node.setAttribute('role','listbox');
    const rect=select.getBoundingClientRect();node.style.left=rect.left+'px';node.style.width=rect.width+'px';
    for(const [index,option] of [...select.options].entries()){
      const item=document.createElement('button');item.type='button';item.textContent=option.text;item.setAttribute('role','option');item.setAttribute('aria-selected',String(index===select.selectedIndex));
      item.onclick=()=>{selectPopup.index=index;chooseSelect();};node.append(item);
    }
    root.append(node);const height=Math.min(node.scrollHeight,260);node.style.top=(rect.bottom+height<innerHeight-12?rect.bottom+4:Math.max(12,rect.top-height-4))+'px';
    selectPopup={node,select,index:select.selectedIndex};moveSelect(0);
  },true);
  const search=root.querySelector('[data-search]');const message=root.querySelector('[data-message]');
  const icon=()=>window.lucide?.createIcons({attrs:{width:18,height:18}});
  const collection=kind=>ui.snapshot?.collections?.[String(kind)]||[];
  const selected=kind=>collection(kind).find(item=>(item.state&2)!==0);
  const kind=()=>ui.slot===3?0:ui.slot;
  // SuperChargers has a vehicle slot (collection 9) in place of Trap Team's trap slot.
  const superchargers=()=>ui.snapshot?.title==='superchargers';
  const slotOrder=()=>superchargers()?(ui.coop?[0,3,9,2]:[0,9,2]):(ui.coop?[0,3,1,2]:[0,1,2]);
  const words=category=>category===2?['item','Choose an item','Search items…','Create an item','Create item']:category===9?['vehicle','Choose a vehicle','Search vehicles…','Create a vehicle','Create vehicle']:['figure','Choose a Skylander','Search Skylanders…','Create a Skylander','Create figure'];
  // Swapper halves share a player: state bit 4 marks the bottom half under the top.
  const isTop=item=>item?.detail==='Swapper top half';
  const halves=slot=>{const list=collection(slot);return {main:list.find(item=>(item.state&6)===2),bottom:list.find(item=>(item.state&4)!==0)};};
  const halfName=name=>name.replace(/ \((Top|Bottom)\)$/,'');
  const slotLabel=slot=>{if(slot!==0&&slot!==3)return selected(slot)?.name;const {main,bottom}=halves(slot);
    if(bottom)return (isTop(main)?halfName(main.name):'?')+' + '+halfName(bottom.name);return isTop(main)?halfName(main.name)+' + ?':main?.name;};
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
    for(const slot of slotOrder()){
      const item=slot===0||slot===3?halves(slot).main||halves(slot).bottom:selected(slot);const title=slotLabel(slot)||'Empty';const card=button('slot',slotNames[slot]+': '+title);card.setAttribute('aria-pressed',String(ui.slot===slot));
      let cell=item?.portrait??-1;if(slot===1&&item&&cell<0)cell=ui.snapshot?.elements?.[item.element]?.portrait??-1;
      if(cell>=0)card.append(portrait(cell));else{const empty=document.createElement('span');empty.className='empty';empty.innerHTML='<i data-lucide="orbit" aria-hidden="true"></i>';card.append(empty);}
      const label=document.createElement('span');label.textContent=slotNames[slot];const name=document.createElement('span');name.className='slot-name';name.textContent=title;card.append(label,name);
      card.onclick=()=>{ui.slot=slot;search.value='';root.querySelector('.figure-creator').hidden=true;render();};strip.append(card);
    }
    root.querySelector('[data-coop]').textContent=ui.coop?'− Remove player 2':'+ Add player 2';
    const player=ui.slot===0||ui.slot===3;const {main,bottom}=player?halves(ui.slot):{};const swapper=player&&(isTop(main)||!!bottom);
    root.querySelector('[data-remove]').textContent=ui.slot===1?'Eject trap':ui.slot===2?'Remove item':ui.slot===9?'Remove vehicle':swapper?'Remove swapper':'Remove figure';
    root.querySelector('[data-remove-top]').hidden=!(swapper&&isTop(main));root.querySelector('[data-remove-bottom]').hidden=!(swapper&&bottom);
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
    const text=words(category);root.querySelector('[data-collection-title]').textContent=text[1];root.querySelector('[data-current-slot]').textContent=slotNames[ui.slot];search.placeholder=text[2];
    const grid=root.querySelector('.portrait-grid');grid.replaceChildren();
    for(const item of list){const card=button('figure','Place '+item.name+' in '+slotNames[ui.slot]);card.setAttribute('aria-pressed',String(!!(item.state&2)));card.append(portrait(item.portrait));const label=document.createElement('span');label.textContent=item.detail.startsWith('Swapper ')?halfName(item.name):item.name;card.append(label);
      if(item.detail.startsWith('Swapper ')){const half=document.createElement('span');half.className='swapper-half';half.textContent=isTop(item)?'Top':'Bottom';card.append(half);}
      if(item.state&2){const check=document.createElement('span');check.className='selected-mark';check.innerHTML='<i data-lucide="check" aria-hidden="true"></i>';card.append(check);}
      card.onclick=()=>send('portal',category===9?17:category===2?8:ui.slot===3?6:0,item.index);grid.append(card);}
    if(!list.length){const empty=document.createElement('p');empty.className='no-results';empty.textContent='Create or import a '+text[0]+' to start your collection.';grid.append(empty);}
    const selector=root.querySelector('#trap-create-character');const saved=selector.value;selector.replaceChildren();
    for(const item of ui.snapshot?.creation||[]){if(item.kind!==category)continue;const option=document.createElement('option');option.value=String(item.index);option.textContent=item.name;selector.append(option);}if([...selector.options].some(option=>option.value===saved))selector.value=saved;
    root.querySelector('.figure-creator h3').textContent=text[3];root.querySelector('label[for="trap-create-character"]').textContent=category===9?'Vehicle':category===2?'Item':'Character';root.querySelector('[data-add]').textContent=text[4];
  }
  function render(){
    const focused=document.activeElement?.getAttribute('aria-label');
    root.querySelector('.portal-panel').hidden=ui.view!=='portal';root.querySelector('.settings-panel').hidden=ui.view!=='settings';
    root.querySelectorAll('[data-view]').forEach(node=>{const active=node.dataset.view===ui.view&&(!node.dataset.page||node.dataset.page===ui.page);node.classList.toggle('is-current',active);node.setAttribute('aria-expanded',String(active));});
    root.querySelectorAll('[data-settings-page]').forEach(node=>node.hidden=node.dataset.settingsPage!==ui.page);
    root.querySelector('[data-setting-title]').textContent={display:'Display',graphics:'Graphics',controls:'Controls',audio:'Audio'}[ui.page];
    const old=root.querySelector('[data-setting-icon]');const next=document.createElement('i');next.dataset.settingIcon='';next.dataset.lucide={display:'monitor',graphics:'sliders-horizontal',controls:'gamepad-2',audio:'volume-2'}[ui.page];next.setAttribute('aria-hidden','true');old.replaceWith(next);
    slots();const isTrap=ui.slot===1;
    root.querySelector('.trap-browser').hidden=!isTrap;root.querySelector('.portrait-grid').hidden=isTrap;root.querySelector('.search').hidden=isTrap;root.querySelector('.collection-actions').hidden=isTrap;root.querySelector('.section-title').hidden=isTrap;
    if(isTrap)traps();else figures();message.textContent=ui.snapshot?.status||'Waiting for the game…';icon();
    if(focused){const match=[...root.querySelectorAll('button')].find(node=>node.getAttribute('aria-label')===focused);if(match){match.focus({preventScroll:true});mark(match);}}
  }
  function initializeSettings(settings){
    if(ui.dirty)return;
    for(const [id,key] of [['trap-demo-res','resolution'],['trap-demo-quality','quality'],['trap-demo-fps','framePolicy'],['trap-demo-pad','layout'],['trap-demo-glyphs','glyphs']])root.querySelector('#'+id).selectedIndex=settings[key]??0;
    root.querySelector('#trap-demo-fullscreen').checked=!!settings.fullscreen;root.querySelector('#trap-demo-counter').checked=!!settings.counter;root.querySelector('#trap-demo-audio').value=String(settings.volume??30);root.querySelector('[data-volume]').textContent=(settings.volume??30)+'%';
  }
  function receive(text){
    let snapshot;try{snapshot=JSON.parse(text);}catch{return;}if(snapshot.version!==1)return;
    const opened=snapshot.visible&&!ui.visible;ui.visible=!!snapshot.visible;
    if(!ui.visible)closeSelect();
    const badge=root.querySelector('[data-fps-readout]');const ms=Number(snapshot.frameTimeMs)||0;
    badge.hidden=!!snapshot.embedded||!snapshot.settings?.counter;
    badge.textContent=ms>0?`${Math.round(1000/ms)} FPS  ${ms.toFixed(1)} ms`:'— FPS';
    if(snapshot.collections){const comparable=JSON.stringify([snapshot.title,snapshot.collections,snapshot.elements,snapshot.creation,snapshot.status]);ui.snapshot=snapshot;root.classList.toggle('superchargers',superchargers());if(!slotOrder().includes(ui.slot))ui.slot=0;if(comparable!==previous){previous=comparable;ui.coop=ui.coop||!!selected(3);render();}initializeSettings(snapshot.settings||{});updateHints();}
    if(snapshot.inputSequence!==ui.sequence){ui.sequence=snapshot.inputSequence;for(const key of snapshot.keys||[])if(key>0)navigate(key);}
    if(opened)setTimeout(enterPanel,0);
  }
  // Controller and keyboard navigation. Keys from the host: 1-4 up/down/left/right, 5 activate,
  // 6 close the overlay (Start/Select), 7 back (B), 8 left side: tab rail (LB), 9 right side: open panel (RB).
  const tabs=()=>[...root.querySelectorAll('.rail [data-view],.rail [data-quit]')];
  const currentTab=()=>tabs().find(node=>node.dataset.view===ui.view&&(!node.dataset.page||node.dataset.page===ui.page))||tabs()[0];
  const openPanel=()=>root.querySelector(ui.view==='portal'?'.portal-panel':'.settings-panel');
  const usable=node=>!node.disabled&&node.getClientRects().length&&!node.closest('[hidden]');
  // The corner X and the search box are mouse/keyboard only: a controller backs out with B.
  const targets=area=>[...area.querySelectorAll('button,input,select')].filter(node=>usable(node)&&!node.matches('[data-close],[data-search]'));
  const hints=root.querySelector('.pad-hints');
  // Button names match the prompts the game was started with, so menu and game always agree;
  // a changed "Button icons" setting takes effect for both after Apply and restart.
  const glyphs=()=>({xbox:{a:'A',b:'B',lb:'LB',rb:'RB',start:'Start'},nintendo:{a:'B',b:'A',lb:'L',rb:'R',start:'+'}})[ui.snapshot?.settings?.activeGlyphs]||{a:'✕',b:'○',lb:'L1',rb:'R1',start:'Options'};
  const remembered=new Map(); // panel → last focused control, restored by RB
  const identity=node=>node.id||node.getAttribute('aria-label')||node.textContent.trim();
  const panelKey=()=>ui.view==='portal'?'portal':'settings:'+ui.page;
  function updateHints(){
    const active=document.activeElement;const inRail=!!active?.closest('.rail');const g=glyphs();
    root.classList.toggle('zone-rail',inRail);root.classList.toggle('zone-panel',!inRail&&!!active?.closest('.portal-panel,.settings-panel'));
    const value=active instanceof HTMLSelectElement||active?.type==='range';
    const items=inRail?[['▲▼','Switch tab'],[g.a+' / '+g.rb,'Enter'],[g.b,'Close'],[g.start,'Close']]
      :[[value?'◀▶':'✚',value?'Change':'Move'],[g.a,value?'Next':'Select'],[g.lb,'Tabs'],[g.b,'Back'],[g.start,'Close']];
    hints.replaceChildren(...items.map(([button,label])=>{const item=document.createElement('span');const key=document.createElement('kbd');key.textContent=button;item.append(key,label);return item;}));
  }
  // The overlay window may not hold OS focus while the game does, so :focus is unreliable:
  // the controller highlight is a class on the current control.
  function mark(node){root.querySelectorAll('.pad-current').forEach(other=>other!==node&&other.classList.remove('pad-current'));node?.classList.add('pad-current');updateHints();}
  function focus(node){
    if(!node)return;root.classList.add('pad-focus');node.focus({preventScroll:true});mark(node);node.scrollIntoView({block:'nearest',inline:'nearest'});
    if(!node.closest('.rail'))remembered.set(panelKey(),identity(node));
  }
  function openTab(tab){if(!tab)return;if(!tab.matches('[data-quit]'))tab.click();focus(tab);}
  function enterPanel(){
    const area=openPanel();if(!area||area.hidden){focus(currentTab());return;}
    const list=targets(area);const last=remembered.get(panelKey());const pressed=area.querySelector('[aria-pressed="true"]');
    focus(list.find(node=>identity(node)===last)||(pressed&&usable(pressed)?pressed:list[0]));
  }
  function nearest(nodes,active,key){
    const rect=active.getBoundingClientRect();const x=rect.x+rect.width/2,y=rect.y+rect.height/2;let best=null,score=Infinity;
    // Sideways offset is the gap between the two spans (0 when they overlap), so a small
    // control just below a wide one is preferred over a centred one further away. Anything in
    // line (gap 0) beats every diagonal, so left/right stays in its row however far the next item is.
    const gap=(a0,a1,b0,b1)=>Math.max(0,Math.max(a0,b0)-Math.min(a1,b1));
    for(const node of nodes){if(node===active)continue;const r=node.getBoundingClientRect();const dx=r.x+r.width/2-x,dy=r.y+r.height/2-y;const forward=key===1?-dy:key===2?dy:key===3?-dx:dx;if(forward<4)continue;const cross=key<3?gap(rect.left,rect.right,r.left,r.right):gap(rect.top,rect.bottom,r.top,r.bottom);const candidate=(cross>0?1e6:0)+forward+cross*2.5;if(candidate<score){best=node;score=candidate;}}
    return best;
  }
  function adjust(node,step){
    if(node instanceof HTMLSelectElement){const count=node.options.length;if(!count)return;node.selectedIndex=(node.selectedIndex+step+count)%count;node.dispatchEvent(new Event('change',{bubbles:true}));}
    else if(node.type==='range'){const value=Math.min(Number(node.max),Math.max(Number(node.min),Number(node.value)+step*5));node.value=String(value);node.dispatchEvent(new Event('input',{bubbles:true}));node.dispatchEvent(new Event('change',{bubbles:true}));}
  }
  function back(){
    const creator=root.querySelector('.figure-creator');
    if(!creator.hidden&&creator.contains(document.activeElement)){creator.hidden=true;focus(root.querySelector('[data-add]'));return;}
    if(openPanel()?.contains(document.activeElement)){focus(currentTab());return;}
    send('close');
  }
  function navigate(key){
    if(selectPopup){if(key>=1&&key<=4)moveSelect(key===1||key===3?-1:1);else if(key===5)chooseSelect();else closeSelect();return;}
    if(key===6){send('close');return;}
    if(key===7){back();return;}
    if(key===8){focus(currentTab());return;}
    if(key===9){enterPanel();return;}
    const active=document.activeElement;const inRail=!!active?.closest('.rail');const area=openPanel();
    if(!active||active===document.body||!root.contains(active)){enterPanel();return;}
    if(inRail){
      if(key===1||key===2){const list=tabs();const index=list.indexOf(active);openTab(list[Math.min(list.length-1,Math.max(0,index+(key===2?1:-1)))]);return;}
      if(active.matches('[data-quit]')){if(key===5)active.click();return;}
      if(key===4||key===5)enterPanel();
      return;
    }
    const value=active instanceof HTMLSelectElement||active.type==='range';
    if(key===5){if(active instanceof HTMLSelectElement)adjust(active,1);else{active.click();updateHints();}return;}
    if(value&&(key===3||key===4)){adjust(active,key===4?1:-1);return;}
    const next=area?nearest(targets(area),active,key):null;
    if(next){focus(next);return;}
    if(key===3)focus(currentTab()); // past the panel's left edge: back to the tabs
  }
  root.querySelectorAll('[data-view]').forEach(node=>node.onclick=()=>{ui.view=node.dataset.view;if(node.dataset.page)ui.page=node.dataset.page;render();});
  // Quit to launcher asks for a second press, so a stray A on the rail cannot end the session.
  const quit=root.querySelector('[data-quit]');const quitLabel=quit.querySelector('.nav-label');
  quit.onclick=()=>{if(quit.dataset.armed){send('quit');return;}quit.dataset.armed='1';quitLabel.textContent='Press again to quit';setTimeout(()=>{delete quit.dataset.armed;quitLabel.textContent='Quit to launcher';},4000);};
  root.querySelectorAll('[data-close]').forEach(node=>node.onclick=()=>{ui.view='none';render();});
  root.querySelector('[data-coop]').onclick=()=>{ui.coop=!ui.coop;if(ui.coop)ui.slot=3;else{send('portal',7,0);if(ui.slot===3)ui.slot=0;}render();};
  root.querySelector('[data-remove-top]').onclick=()=>send('portal',ui.slot===3?16:15,0);
  root.querySelector('[data-remove-bottom]').onclick=()=>send('portal',ui.slot===3?14:13,0);
  root.querySelector('[data-remove]').onclick=()=>send('portal',ui.slot===9?18:ui.slot===1?4:ui.slot===2?9:ui.slot===3?7:3,0);
  root.querySelector('[data-add]').onclick=()=>{const panel=root.querySelector('.figure-creator');panel.hidden=!panel.hidden;};
  root.querySelector('[data-import]').onclick=()=>bridge?.importFigure(ui.slot===3?1:0);
  root.querySelector('[data-create-figure]').onclick=()=>{const choice=Number(root.querySelector('#trap-create-character').value);if(Number.isInteger(choice)&&choice>=0){send('portal',ui.slot===3?10:5,choice);root.querySelector('.figure-creator').hidden=true;}};
  search.oninput=()=>{figures();icon();};
  root.querySelectorAll('.settings-panel input,.settings-panel select').forEach(node=>node.addEventListener('change',()=>ui.dirty=true));
  root.querySelector('#trap-demo-glyphs').addEventListener('change',()=>root.querySelector('[data-settings-message]').textContent='Button icons change in the game and this menu after Apply settings and restart.');
  root.querySelector('#trap-demo-fps').onchange=event=>{ui.dirty=true;send('fps',event.target.selectedIndex);};
  root.querySelector('#trap-demo-audio').oninput=event=>{ui.dirty=true;root.querySelector('[data-volume]').textContent=event.target.value+'%';send('volume',event.target.value);};
  root.querySelector('#trap-demo-counter').onchange=event=>send('counter',Number(event.target.checked));
  root.querySelector('[data-apply]').onclick=()=>send('settings',root.querySelector('#trap-demo-res').selectedIndex,root.querySelector('#trap-demo-quality').selectedIndex,Number(root.querySelector('#trap-demo-fullscreen').checked),Number(root.querySelector('#trap-demo-counter').checked),root.querySelector('#trap-demo-pad').selectedIndex,root.querySelector('#trap-demo-glyphs').selectedIndex);
  document.addEventListener('keydown',event=>{
    if(selectPopup&&['ArrowUp','ArrowDown','Enter','Escape','Tab'].includes(event.key)){
      event.preventDefault();event.stopPropagation();
      if(event.key==='Enter')chooseSelect();else if(event.key==='Escape'||event.key==='Tab')closeSelect();else moveSelect(event.key==='ArrowUp'?-1:1);return;
    }
    if(event.key==='F10'){event.preventDefault();if(!event.repeat)send('minimize');return;}
    if(['F6','Insert'].includes(event.key)){event.preventDefault();send('close');return;}
    if(event.key==='Escape'){event.preventDefault();navigate(7);return;}
    if(event.key==='PageUp'||event.key==='PageDown'){event.preventDefault();navigate(event.key==='PageDown'?9:8);return;}
    const keys={ArrowUp:1,ArrowDown:2,ArrowLeft:3,ArrowRight:4};
    if(keys[event.key]&&!event.target.matches?.('[data-search]')){event.preventDefault();navigate(keys[event.key]);}
  });
  document.addEventListener('pointerdown',()=>root.classList.remove('pad-focus','zone-rail','zone-panel'));
  document.addEventListener('focusin',event=>{if(root.contains(event.target))mark(event.target);});
  window.portalReceive=receive;window.portalNavigate=navigate;
  icon();
  new QWebChannel(qt.webChannelTransport,channel=>{bridge=channel.objects.portal;bridge.changed.connect(receive);bridge.ready();bridge.snapshot(receive);});
})();
